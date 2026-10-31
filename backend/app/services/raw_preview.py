from io import BytesIO
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException

RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2', '.raf'}


class JPEGCursor:
    def __init__(self):
        self.position = 2
        self.scanning = False

    def end(self, data):
        while self.position < len(data):
            position = self.position
            if self.scanning:
                position = data.find(b'\xff', position)
                if position < 0:
                    self.position = max(2, len(data) - 1)
                    return None
            elif data[position] != 255:
                raise ValueError('Invalid JPEG marker')
            code_position = position + 1
            while code_position < len(data) and data[code_position] == 255:
                code_position += 1
            if code_position >= len(data):
                self.position = position
                return None
            code = data[code_position]
            if self.scanning and (code == 0 or 208 <= code <= 215):
                self.position = code_position + 1
                continue
            if code == 217:
                return code_position + 1
            if code in {0, 216}:
                raise ValueError('Invalid JPEG marker')
            if code == 1 or 208 <= code <= 215:
                self.position = code_position + 1
                continue
            if code_position + 2 >= len(data):
                self.position = position
                return None
            length = int.from_bytes(data[code_position + 1:code_position + 3], 'big')
            if length < 2:
                raise ValueError('Invalid JPEG segment')
            end = code_position + 1 + length
            if end > len(data):
                self.position = position
                return None
            self.position = end
            self.scanning = code == 218
        return None


def preview_image(source, extension):
    if extension not in RAW_EXTENSIONS:
        return Image.open(source)
    best = None
    pixels = 0
    buffer = b''
    consumed = 0
    cursor = None
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
                cursor = None
                break
            if start:
                buffer = buffer[start:]
                cursor = None
            cursor = cursor or JPEGCursor()
            try:
                end = cursor.end(buffer)
            except ValueError:
                buffer, cursor = buffer[3:], None
                continue
            if end is None:
                if len(buffer) > maximum:
                    buffer, cursor = buffer[3:], None
                    continue
                break
            candidate = buffer[:end]
            buffer, cursor = buffer[end:], None
            try:
                with Image.open(BytesIO(candidate)) as image:
                    area = image.width * image.height
                    if image.format == 'JPEG' and area > pixels and area <= 50000000:
                        image.draft('RGB', (640, 640))
                        image.load()
                        best, pixels = candidate, area
            except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
                continue
    if best is None:
        raise HTTPException(415, 'No supported embedded JPEG preview was found in this RAW file')
    return Image.open(BytesIO(best))
