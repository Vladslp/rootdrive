import heapq
import mimetypes
import os
import shutil
import stat
import time
from pathlib import Path
from threading import RLock
from urllib.parse import quote
from fastapi import HTTPException
from starlette.responses import StreamingResponse

PREVIEW_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf'}


class Filesystem:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.storage_path
        self.lock = RLock()
        self.stats_cache = None
        self.stats_time = 0.0

    def name(self, value: str) -> str:
        if not value or value in {'.', '..'} or value != value.strip() or len(value.encode()) > 240:
            raise HTTPException(400, 'Invalid name')
        if any(ord(c) < 32 or c in '/\\\x7f<>:"|?*' for c in value):
            raise HTTPException(400, 'Unsafe name')
        return value

    def path(self, value: str = '', exists: bool = True, allow_root: bool = True) -> Path:
        if '\\' in value or value.startswith('/') or '\x00' in value:
            raise HTTPException(400, 'Unsafe path')
        parts = value.split('/') if value else []
        current = self.root
        for part in parts:
            self.name(part)
            current = current / part
            if current.is_symlink():
                raise HTTPException(400, 'Symbolic links are not accessible')
        if current == self.root and not allow_root:
            raise HTTPException(400, 'Choose a file or folder')
        if exists and not current.exists():
            raise HTTPException(404, 'File or folder not found')
        if not current.resolve().is_relative_to(self.root):
            raise HTTPException(400, 'Path leaves the storage workspace')
        return current

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def entry(self, path: Path) -> dict:
        info = path.stat(follow_symlinks=False)
        folder = stat.S_ISDIR(info.st_mode)
        return {'name': path.name, 'path': self.relative(path), 'type': 'folder' if folder else 'file', 'size': 0 if folder else info.st_size, 'modified': info.st_mtime, 'mime': 'inode/directory' if folder else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream')}

    def walk(self, directory: Path, recursive: bool):
        with os.scandir(directory) as entries:
            for item in entries:
                if item.is_symlink():
                    continue
                if not item.is_dir(follow_symlinks=False) and not item.is_file(follow_symlinks=False):
                    continue
                path = Path(item.path)
                yield path
                if recursive and item.is_dir(follow_symlinks=False):
                    yield from self.walk(path, True)

    def listing(self, path, query, recursive, sort, direction, offset, limit):
        directory = self.path(path)
        if not directory.is_dir():
            raise HTTPException(400, 'This location is not a folder')
        total = 0

        def candidates():
            nonlocal total
            for item in self.walk(directory, recursive):
                if query.casefold() not in item.name.casefold():
                    continue
                try:
                    entry = self.entry(item)
                except FileNotFoundError:
                    continue
                total += 1
                yield entry

        def key(item):
            value = item['name'].casefold() if sort == 'name' else item['mime'] if sort == 'type' else item['modified'] if sort == 'modified' else item['size']
            return (item['type'] != 'folder', value, item['path'])

        select = heapq.nlargest if direction == 'desc' else heapq.nsmallest
        page = select(offset + limit, candidates(), key=key)[offset:]
        return {'items': page, 'total': total, 'offset': offset, 'limit': limit, 'path': path}

    def free_destination(self, destination: Path):
        if destination.exists() or destination.is_symlink():
            raise HTTPException(409, 'A file or folder with this name already exists')

    def invalidate(self):
        self.stats_time = 0

    def stats(self):
        with self.lock:
            if self.stats_cache is None or time.monotonic() - self.stats_time > 30:
                count, size = 0, 0
                categories = {'images': 0, 'videos': 0, 'documents': 0, 'other': 0}
                for path in self.walk(self.root, True):
                    if path.is_file():
                        count += 1
                        amount = path.stat().st_size
                        size += amount
                        mime = mimetypes.guess_type(path.name)[0] or ''
                        category = 'images' if mime.startswith('image/') else 'videos' if mime.startswith('video/') else 'documents' if mime.startswith('text/') or mime == 'application/pdf' else 'other'
                        categories[category] += amount
                disk = shutil.disk_usage(self.root)
                self.stats_cache = {'file_count': count, 'stored_bytes': size, 'disk_free': disk.free, 'disk_total': disk.total, 'disk_used': disk.used, 'disk_percent': round(disk.used / disk.total * 100, 1), 'categories': categories}
                self.stats_time = time.monotonic()
            return self.stats_cache

    def response(self, value, preview=False):
        with self.lock:
            path = self.path(value, allow_root=False)
            if not path.is_file():
                raise HTTPException(400, 'Choose a regular file')
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if preview and mime not in PREVIEW_TYPES:
                raise HTTPException(415, 'Preview is not available for this file')
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            handle = os.fdopen(descriptor, 'rb')
            size = os.fstat(descriptor).st_size

        def chunks():
            try:
                while block := handle.read(256 * 1024):
                    yield block
            finally:
                handle.close()

        disposition = 'inline' if preview else 'attachment'
        return StreamingResponse(chunks(), media_type=mime, headers={'Content-Length': str(size), 'Content-Disposition': f"{disposition}; filename*=UTF-8''{quote(path.name)}", 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store', 'Content-Security-Policy': "sandbox; default-src 'none'"})
