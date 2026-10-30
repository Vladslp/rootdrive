import io
import os
import uuid
from threading import BoundedSemaphore
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from ..services.security import require_access
from ..services.io import open_regular
from ..services.raw_preview import preview_image
from ..services.transfers import available_name

router = APIRouter(prefix='/api/studio', dependencies=[Depends(require_access)])
processing = BoundedSemaphore(1)


class ExportInput(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=20)
    format: Literal['jpeg', 'png', 'webp'] = 'jpeg'
    quality: int = Field(default=88, ge=10, le=100)
    width: int = Field(default=2560, ge=1, le=20000)
    height: int = Field(default=2560, ge=1, le=20000)
    strip_metadata: bool = True
    watermark: str = Field(default='', max_length=120)
    logo: str = Field(default='', max_length=4096)
    opacity: float = Field(default=0.65, ge=0.05, le=1)
    position: Literal['bottom-right', 'bottom-left', 'top-right', 'top-left', 'center'] = 'bottom-right'


def source_image(fs, value):
    with open_regular(fs, value) as (path, source):
        if os.fstat(source.fileno()).st_size > 512 * 1024 * 1024:
            raise HTTPException(413, 'Photos over 512 MB cannot be exported')
        try:
            with preview_image(source, path.suffix.lower()) as image:
                if image.width * image.height > fs.settings.max_preview_pixels:
                    raise HTTPException(413, 'This image exceeds the pixel limit')
                if getattr(image, 'n_frames', 1) > 1:
                    raise HTTPException(415, 'Animated images are kept as originals')
                exif = image.getexif()
                transposed = ImageOps.exif_transpose(image)
                try:
                    transposed.load()
                    return path, transposed.convert('RGBA'), exif
                finally:
                    transposed.close()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
            raise HTTPException(415, 'Unable to read this photo')


def render(fs, value, body):
    path, image, exif = source_image(fs, value)
    image.thumbnail((body.width, body.height), Image.Resampling.LANCZOS)
    mark = None
    if body.logo:
        _, mark, _ = source_image(fs, body.logo)
        mark.thumbnail((max(1, image.width // 4), max(1, image.height // 4)), Image.Resampling.LANCZOS)
    elif body.watermark:
        font = ImageFont.load_default(size=max(12, round(min(image.size) * 0.035)))
        bounds = font.getbbox(body.watermark)
        mark = Image.new('RGBA', (max(1, bounds[2] - bounds[0] + 12), max(1, bounds[3] - bounds[1] + 12)))
        ImageDraw.Draw(mark).text((6 - bounds[0], 6 - bounds[1]), body.watermark, font=font, fill='white', stroke_width=1, stroke_fill=(0, 0, 0, 160))
        mark.thumbnail((max(1, int(image.width * .9)), max(1, int(image.height * .9))), Image.Resampling.LANCZOS)
    if mark:
        try:
            alpha = mark.getchannel('A').point(lambda value: round(value * body.opacity))
            mark.putalpha(alpha)
            margin = max(1, round(min(image.size) * .025))
            x = margin if 'left' in body.position else max(0, image.width - mark.width - margin)
            y = margin if 'top' in body.position else max(0, image.height - mark.height - margin)
            if body.position == 'center':
                x, y = (image.width - mark.width) // 2, (image.height - mark.height) // 2
            image.alpha_composite(mark, (x, y))
        finally:
            mark.close()
    exif.pop(274, None)
    return path, image, exif


def encode(image, destination, body, exif):
    options = {'format': body.format.upper(), 'quality': body.quality}
    if not body.strip_metadata and exif:
        options['exif'] = exif.tobytes()
    if body.format == 'jpeg':
        background = Image.new('RGB', image.size, 'white')
        try:
            background.paste(image, mask=image.getchannel('A'))
            background.save(destination, **options)
        finally:
            background.close()
    else:
        image.save(destination, **options)


@router.post('/preview')
def export_preview(body: ExportInput, request: Request):
    fs = request.app.state.fs
    with processing:
        _, image, exif = render(fs, body.paths[0], body)
        try:
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            encode(image, output, body, exif)
            return Response(output.getvalue(), media_type='image/' + body.format, headers={'Cache-Control': 'no-store'})
        finally:
            image.close()


@router.post('/export', status_code=201)
def export_photos(body: ExportInput, request: Request):
    fs = request.app.state.fs
    installed = []
    staged = []
    entries = []
    with processing, fs.lock:
        try:
            for value in dict.fromkeys(body.paths):
                path, image, exif = render(fs, value, body)
                temporary = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
                staged.append(temporary)
                try:
                    encode(image, temporary, body, exif)
                finally:
                    image.close()
                if temporary.stat().st_size > fs.settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, 'An exported copy exceeds the upload limit')
                name = path.stem + '.' + ('jpg' if body.format == 'jpeg' else body.format)
                destination = available_name(fs, path.parent, name, 'export')
                os.link(temporary, destination, follow_symlinks=False)
                installed.append(destination)
                entries.append(fs.entry(destination))
            fs.invalidate()
            return {'items': entries}
        except BaseException:
            for destination in reversed(installed):
                destination.unlink(missing_ok=True)
            fs.invalidate()
            raise
        finally:
            for temporary in staged:
                temporary.unlink(missing_ok=True)
