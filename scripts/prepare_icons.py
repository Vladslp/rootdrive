from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'frontend/public/assets'
ICONS = ASSETS / 'icons'
GROUPS = {
    'folders': [['folder', 'lavender', 'yellow'], ['mint', 'cloud', 'drive']],
    'files': [['images', 'videos', 'audio'], ['documents', 'archives', 'pdf']],
    'extra': [['sheets', 'slides'], ['code', 'file']],
    'file-types': [['text', 'markdown', 'word', 'opendocument'], ['json', 'csv', 'python', 'javascript'], ['html', 'css', 'typescript', 'sql']],
    'storage-icons': [['storage-files', 'storage-trash', 'storage-versions'], ['storage-temporary', 'storage-system', 'storage-free']],
}


def save_icon(image: Image.Image, name: str, side: int = 320) -> None:
    image = image.resize((side, side), Image.Resampling.LANCZOS)
    image.save(ICONS / f'{name}.webp', format='WEBP', quality=92, method=6, exact=True)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    for group, rows in GROUPS.items():
        variants = [('', group)]
        if group == 'folders':
            variants.append(('empty-', 'empty-folders'))
        for prefix, source in variants:
            with Image.open(ASSETS / f'{source}.png') as image:
                for y, row in enumerate(rows):
                    for x, name in enumerate(row):
                        if group == 'file-types':
                            left, top = 68 + x * 342, 34 + y * 335
                            box = (left, top, left + 320, top + 342)
                        else:
                            width, height = image.width / len(row), image.height / len(rows)
                            box = tuple(round(value) for value in (x * width, y * height, (x + 1) * width, (y + 1) * height))
                        save_icon(image.crop(box), prefix + name, 192 if group == 'storage-icons' else 320)
    with Image.open(ASSETS / 'app-icon.png') as image:
        save_icon(image, 'app', 256)
    print(f'{len(list(ICONS.glob("*.webp")))} icons · {sum(path.stat().st_size for path in ICONS.glob("*.webp")) // 1024} KB')


if __name__ == '__main__':
    main()
