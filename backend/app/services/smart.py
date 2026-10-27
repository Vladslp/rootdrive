import heapq
import mimetypes
import time
from copy import deepcopy
from fastapi import HTTPException

RECENT_SECONDS = 7 * 24 * 60 * 60
LARGE_BYTES = 100 * 1024 * 1024
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif', '.tif', '.tiff', '.bmp', '.dng', '.cr2', '.cr3', '.nef', '.arw', '.raf', '.orf', '.rw2'}
DOCUMENT_EXTENSIONS = {'.txt', '.md', '.markdown', '.rtf', '.pdf', '.doc', '.docx', '.odt', '.xls', '.xlsx', '.ods', '.csv', '.ppt', '.pptx', '.odp', '.pages', '.numbers', '.key', '.epub'}


def smart_listing(fs, kind, query, sort, direction, offset, limit):
    key = (kind, query.casefold(), sort, direction, offset, limit)
    now = time.monotonic()
    cached = fs.smart_cache.get(key)
    if cached and now - cached[0] < 15:
        return deepcopy(cached[1])
    cutoff = time.time() - RECENT_SECONDS
    total = 0

    def candidates():
        nonlocal total
        for candidate in fs.walk(fs.root, True):
            if query.casefold() not in candidate.name.casefold():
                continue
            try:
                path = fs.path(fs.relative(candidate), allow_root=False)
                entry = fs.entry(path, folder_details=False)
            except FileNotFoundError:
                continue
            except HTTPException as error:
                if error.status_code in {400, 404}:
                    continue
                raise
            if entry['type'] != 'file':
                continue
            suffix = path.suffix.lower()
            mime = mimetypes.guess_type(path.name)[0] or ''
            matches = (
                (kind == 'recent' and entry['modified'] >= cutoff)
                or (kind == 'photos' and suffix in PHOTO_EXTENSIONS)
                or (kind == 'documents' and (suffix in DOCUMENT_EXTENSIONS or mime.startswith('text/plain')))
                or (kind == 'large' and entry['size'] >= LARGE_BYTES)
            )
            if matches:
                total += 1
                yield entry

    def order(entry):
        value = entry['name'].casefold() if sort == 'name' else entry['mime'] if sort == 'type' else entry[sort]
        return value, entry['path']

    picker = heapq.nlargest if direction == 'desc' else heapq.nsmallest
    result = {'items': picker(offset + limit, candidates(), key=order)[offset:], 'total': total, 'offset': offset, 'limit': limit, 'path': ''}
    fs.smart_cache.pop(key, None)
    fs.smart_cache[key] = (now, deepcopy(result))
    if len(fs.smart_cache) > 12:
        del fs.smart_cache[next(iter(fs.smart_cache))]
    return result
