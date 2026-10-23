import hashlib
import os
from pathlib import Path
from threading import RLock
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener(decode_threads=1, thumbnails=True, depth_images=False, aux_images=False)


class Previews:
    def __init__(self, settings, filesystem):
        self.settings = settings
        self.filesystem = filesystem
        self.cache = settings.internal_path / 'previews'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def response(self, value: str, thumbnail: bool = False):
        with self.filesystem.lock, self.lock:
            source = self.filesystem.path(value, allow_root=False)
            if not source.is_file() or source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif'}:
                raise HTTPException(415, 'Image preview is not available')
            info = source.stat()
            side = 640 if thumbnail else 1920
            key = hashlib.sha256(f'{value}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_size}:{side}'.encode()).hexdigest()
            destination = self.cache / f'{key}.jpg'
            if not destination.exists():
                temporary = destination.with_suffix('.tmp')
                try:
                    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(descriptor, 'rb') as handle, Image.open(handle) as image:
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
                    temporary.replace(destination)
                    self.prune(destination)
                except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError):
                    raise HTTPException(415, 'Unable to preview this image. Download the original')
                finally:
                    temporary.unlink(missing_ok=True)
            return FileResponse(destination, media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    def prune(self, keep: Path):
        entries = sorted(self.cache.glob('*.jpg'), key=lambda path: path.stat().st_mtime)
        total = sum(path.stat().st_size for path in entries)
        maximum = self.settings.preview_cache_size_mb * 1024 * 1024
        for path in entries:
            if total <= maximum:
                break
            if path != keep:
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                total -= size
