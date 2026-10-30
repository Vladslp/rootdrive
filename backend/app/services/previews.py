import hashlib
import os
import time
import uuid
from pathlib import Path
from threading import BoundedSemaphore, RLock
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from .raw_preview import RAW_EXTENSIONS, preview_image

register_heif_opener(decode_threads=1, thumbnails=True, depth_images=False, aux_images=False)


class Previews:
    def __init__(self, settings, filesystem):
        self.settings = settings
        self.filesystem = filesystem
        self.cache = settings.internal_path / 'previews'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.conversions = BoundedSemaphore(2)
        self.key_locks = [RLock() for _ in range(32)]
        self.last_prune = 0.0
        self.generated_bytes = 0

    def response(self, value: str, thumbnail: bool = False, if_none_match: str | None = None):
        with self.filesystem.lock:
            source = self.filesystem.path(value, allow_root=False)
            if not source.is_file() or source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif'} | RAW_EXTENSIONS:
                raise HTTPException(415, 'Image preview is not available')
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            side = 640 if thumbnail else 1920
            key = hashlib.sha256(f'{value}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_size}:{side}'.encode()).hexdigest()
            etag = f'"{key}"'
            headers = {'Cache-Control': 'private, no-cache', 'ETag': etag, 'Vary': 'Cookie', 'X-Content-Type-Options': 'nosniff'}
            if if_none_match and any(tag.strip().removeprefix('W/') in {etag, '*'} for tag in if_none_match.split(',')):
                return Response(status_code=304, headers=headers)
            destination = self.cache / f'{key}.jpg'
            with self.key_locks[int(key[:2], 16) % len(self.key_locks)]:
                with self.lock:
                    cached = destination.open('rb') if destination.exists() else None
                if cached is None:
                    with self.conversions:
                        temporary = self.cache / f'{uuid.uuid4().hex}.tmp'
                        try:
                            with preview_image(handle, source.suffix.lower()) as image:
                                if image.width * image.height > self.settings.max_preview_pixels:
                                    raise HTTPException(415, 'Image is too large to preview. Download the original')
                                image.draft('RGB', (side, side))
                                image.thumbnail((side, side), Image.Resampling.LANCZOS)
                                ImageOps.exif_transpose(image, in_place=True)
                                if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
                                    rgba = image.convert('RGBA')
                                    canvas = Image.new('RGB', rgba.size, 'white')
                                    canvas.paste(rgba, mask=rgba.getchannel('A'))
                                    canvas.save(temporary, format='JPEG', quality=85)
                                else:
                                    image.convert('RGB').save(temporary, format='JPEG', quality=85)
                            with self.lock:
                                temporary.replace(destination)
                                cached = destination.open('rb')
                                self.generated_bytes += os.fstat(cached.fileno()).st_size
                                self.prune(destination)
                        except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError):
                            if cached is not None:
                                cached.close()
                            raise HTTPException(415, 'Unable to preview this image. Download the original')
                        finally:
                            temporary.unlink(missing_ok=True)
            headers['Content-Length'] = str(os.fstat(cached.fileno()).st_size)

        def chunks():
            try:
                while block := cached.read(64 * 1024):
                    yield block
            finally:
                cached.close()

        return StreamingResponse(chunks(), media_type='image/jpeg', headers=headers, background=BackgroundTask(cached.close))

    def prune(self, keep: Path):
        maximum = self.settings.preview_cache_size_mb * 1024 * 1024
        if time.monotonic() - self.last_prune < 30 and self.generated_bytes < max(1, maximum // 8):
            return
        entries = []
        for path in self.cache.glob('*.jpg'):
            info = path.stat()
            entries.append((info.st_mtime, info.st_size, path))
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total <= maximum:
                break
            if path != keep:
                path.unlink(missing_ok=True)
                total -= size
        self.last_prune = time.monotonic()
        self.generated_bytes = 0
