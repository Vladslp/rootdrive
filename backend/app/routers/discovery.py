import hashlib
import os
import zipfile
from lxml import etree
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete
from ..database import ContentHash
from ..services.security import require_access
from ..services.io import open_regular
from ..services.editors import OfficeDocument, TEXT_LIMIT, read_text

router = APIRouter(prefix='/api/discovery', dependencies=[Depends(require_access)])
TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.yaml', '.yml', '.toml', '.log', '.html', '.css', '.js', '.ts', '.tsx', '.jsx', '.py', '.sh', '.sql', '.xml', '.ini', '.conf'}


def signature(info):
    return f'{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}'


@router.post('/duplicates')
def duplicates(request: Request):
    fs = request.app.state.fs
    sizes = defaultdict(list)
    deadline = time.monotonic() + 30
    incomplete = False
    scanned = 0
    for path in fs.walk(fs.root, True):
        try:
            if not path.is_file():
                continue
            scanned += 1
            if scanned > 100000 or time.monotonic() > deadline:
                incomplete = True
                break
            info = path.stat(follow_symlinks=False)
            sizes[info.st_size].append(fs.relative(path))
        except FileNotFoundError:
            continue
    groups = defaultdict(list)
    hashed = 0
    with request.app.state.db() as db:
        db.execute(delete(ContentHash).where(ContentHash.path.like(':trash:%')))
        for size, values in sizes.items():
            if len(values) < 2:
                continue
            for value in values:
                if time.monotonic() > deadline:
                    incomplete = True
                    break
                try:
                    with open_regular(fs, value) as (path, source):
                        info = os.fstat(source.fileno())
                        stamp = signature(info)
                        cached = db.get(ContentHash, value)
                        if cached is not None and cached.signature == stamp:
                            checksum = cached.digest
                        else:
                            digest = hashlib.sha256()
                            while block := source.read(1024 * 1024):
                                digest.update(block)
                                if time.monotonic() > deadline:
                                    incomplete = True
                                    break
                            if incomplete:
                                break
                            checksum = digest.hexdigest()
                            if signature(os.fstat(source.fileno())) != stamp or signature(path.stat(follow_symlinks=False)) != stamp:
                                continue
                            if cached is None:
                                db.add(ContentHash(path=value, signature=stamp, digest=checksum))
                            else:
                                cached.signature, cached.digest = stamp, checksum
                            hashed += 1
                        groups[(size, checksum)].append(fs.entry(path))
                except (HTTPException, FileNotFoundError):
                    continue
            if incomplete:
                break
        db.commit()
    matches = [{'size': size, 'items': items} for (size, checksum), items in groups.items() if len(items) > 1]
    matches.sort(key=lambda group: group['size'] * (len(group['items']) - 1), reverse=True)
    return {'groups': matches[:200], 'scanned': scanned, 'hashed': hashed, 'incomplete': incomplete or len(matches) > 200}


@router.get('/content')
def search_content(request: Request, q: str = Query(min_length=2, max_length=200), path: str = '', limit: int = Query(60, ge=1, le=100)):
    fs = request.app.state.fs
    directory = fs.path(path)
    if not directory.is_dir():
        raise HTTPException(400, 'Choose a folder')
    query = q.casefold()
    result = []
    scanned = skipped = 0
    incomplete = False
    deadline = time.monotonic() + 15
    for candidate in fs.walk(directory, True):
        suffix = candidate.suffix.lower()
        if suffix not in TEXT_EXTENSIONS | {'.docx', '.odt'} or not candidate.is_file():
            continue
        if scanned >= 2000 or time.monotonic() > deadline:
            incomplete = True
            break
        scanned += 1
        try:
            with open_regular(fs, fs.relative(candidate)) as (original, source):
                if suffix in {'.docx', '.odt'}:
                    document = OfficeDocument(source, suffix)
                    try:
                        text = '\n'.join(item['text'] for item in document.data())
                    finally:
                        document.close()
                else:
                    if candidate.stat().st_size > TEXT_LIMIT:
                        skipped += 1
                        continue
                    text, _ = read_text(source)
                if len(text) > TEXT_LIMIT:
                    skipped += 1
                    continue
                for line_number, line in enumerate(text.splitlines(), 1):
                    location = line.casefold().find(query)
                    if location >= 0:
                        start = max(0, location - 70)
                        result.append({'entry': fs.entry(original), 'line': line_number, 'excerpt': line[start:start + 240]})
                        break
                if len(result) >= limit:
                    incomplete = True
                    break
        except (HTTPException, ValueError, KeyError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError):
            skipped += 1
    return {'items': result, 'scanned': scanned, 'skipped': skipped, 'incomplete': incomplete}
