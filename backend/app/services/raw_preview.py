from io import BytesIO
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException

RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2', '.raf'}


def preview_image(source, extension):
    if extension not in RAW_EXTENSIONS:
        return Image.open(source)
    best = None
    pixels = 0
    buffer = b''
    consumed = 0
    maximum = 16 * 1024 * 1024
    while consumed < 128 * 1024 * 1024:
        block = source.read(64 * 1024)
        if not block:
            break
        consumed += len(block)
        buffer += block
        while True:
            start = buffer.find(b'\xff\xd8\xff')
            if start < 0:
                buffer = buffer[-2:]
                break
            if start:
                buffer = buffer[start:]
            end = buffer.find(b'\xff\xd9', 3)
            if end < 0:
                if len(buffer) > maximum:
                    buffer = buffer[3:]
                    continue
                break
            candidate = buffer[:end + 2]
            buffer = buffer[end + 2:]
            try:
                with Image.open(BytesIO(candidate)) as image:
                    area = image.width * image.height
                    if image.format == 'JPEG' and area > pixels and area <= 50000000:
                        best, pixels = candidate, area
            except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
                continue
    if best is None:
        raise HTTPException(415, 'No supported embedded JPEG preview was found in this RAW file')
    return Image.open(BytesIO(best))
