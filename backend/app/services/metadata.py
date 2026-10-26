import os
from fastapi import HTTPException
from PIL import ExifTags, Image, UnidentifiedImageError

FIELDS = [
    (271, 'Camera maker'), (272, 'Camera model'), (42035, 'Lens maker'),
    (42036, 'Lens model'), (42034, 'Lens specification'),
    (36867, 'Date taken'), (36868, 'Date digitized'), (36881, 'Time zone'),
    (33434, 'Shutter speed'), (33437, 'Aperture'), (34855, 'ISO'),
    (37386, 'Focal length'), (41989, '35 mm equivalent'),
    (37380, 'Exposure compensation'), (34850, 'Exposure program'),
    (41986, 'Exposure mode'), (37383, 'Metering mode'), (41987, 'White balance'),
    (37385, 'Flash'), (274, 'Orientation'), (40961, 'Color space'),
    (305, 'Software'), (315, 'Artist'), (33432, 'Copyright'),
    (270, 'Description'), (36864, 'EXIF version'),
]
ENUMS = {
    34850: {0: 'Not defined', 1: 'Manual', 2: 'Normal program', 3: 'Aperture priority', 4: 'Shutter priority', 5: 'Creative', 6: 'Action', 7: 'Portrait', 8: 'Landscape'},
    41986: {0: 'Auto', 1: 'Manual', 2: 'Auto bracket'},
    37383: {0: 'Unknown', 1: 'Average', 2: 'Center-weighted', 3: 'Spot', 4: 'Multi-spot', 5: 'Pattern', 6: 'Partial', 255: 'Other'},
    41987: {0: 'Auto', 1: 'Manual'},
    274: {1: 'Normal', 2: 'Mirrored', 3: 'Rotated 180°', 4: 'Mirrored vertically', 5: 'Mirrored and rotated 90°', 6: 'Rotated 90° clockwise', 7: 'Mirrored and rotated 270°', 8: 'Rotated 90° counterclockwise'},
    40961: {1: 'sRGB', 65535: 'Uncalibrated'},
}


def format_exif(tag, value):
    try:
        if tag == 42034 and isinstance(value, (tuple, list)) and len(value) == 4:
            minimum, maximum, wide, tele = [float(item) for item in value]
            focal = f'{minimum:g}' if minimum == maximum else f'{minimum:g}–{maximum:g}'
            aperture = '' if wide <= 0 or tele <= 0 else f' · f/{wide:g}' if wide == tele else f' · f/{wide:g}–{tele:g}'
            return f'{focal} mm{aperture}'
        if tag in ENUMS:
            return ENUMS[tag].get(int(value), str(value))
        if tag == 37385:
            return 'Fired' if int(value) & 1 else 'Did not fire'
        if tag == 33434:
            number = float(value)
            return f'1/{round(1 / number)} s' if 0 < number < 1 else f'{number:g} s'
        if tag == 33437:
            return f'f/{float(value):g}'
        if tag in {37386, 41989}:
            return f'{float(value):g} mm'
        if tag == 37380:
            return f'{float(value):+g} EV'
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace').strip('\x00 ')[:400]
        if isinstance(value, (tuple, list)):
            return ', '.join(f'{float(item):g}' if isinstance(item, (int, float)) or hasattr(item, 'numerator') else str(item) for item in value)[:400]
        return str(value).strip('\x00 ')[:400]
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return ''


def image_metadata(filesystem, value):
    with filesystem.lock:
        path = filesystem.path(value, allow_root=False)
        if not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif'}:
            raise HTTPException(415, 'Image metadata is not available')
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as handle, Image.open(handle) as image:
                exif = image.getexif()
                values = dict(exif)
                try:
                    values.update(exif.get_ifd(ExifTags.IFD.Exif))
                except (ValueError, TypeError, KeyError, SyntaxError, OSError):
                    pass
                fields = []
                for tag, label in FIELDS:
                    if tag in values:
                        formatted = format_exif(tag, values[tag])
                        if formatted:
                            fields.append({'label': label, 'value': formatted})
                return {'width': image.width, 'height': image.height, 'format': image.format, 'exif': fields}
        except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError, SyntaxError):
            raise HTTPException(415, 'Unable to read image metadata')
