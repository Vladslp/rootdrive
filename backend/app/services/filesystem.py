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
        self.folder_cache = {}

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

    def folder_details(self, path: Path) -> dict:
        now = time.monotonic()
        key = (self.relative(path), path.stat(follow_symlinks=False).st_mtime_ns)
        cached = self.folder_cache.get(key)
        if cached and now - cached[0] < 30:
            return cached[1]
        pending = [(path, False)]
        totals = {}
        children = {}
        while pending:
            current, visited = pending.pop()
            if visited:
                size, count, folders = children.pop(current)
                totals[current] = {'size': size + sum(totals[folder]['size'] for folder in folders), 'child_count': count}
                continue
            count, size, folders = 0, 0, []
            with os.scandir(current) as entries:
                for item in entries:
                    if item.name == '.DS_Store' or item.is_symlink():
                        continue
                    try:
                        if item.is_file(follow_symlinks=False):
                            size += item.stat(follow_symlinks=False).st_size
                            count += 1
                        elif item.is_dir(follow_symlinks=False):
                            folders.append(Path(item.path))
                            count += 1
                    except FileNotFoundError:
                        continue
            children[current] = (size, count, folders)
            pending.append((current, True))
            pending.extend((folder, False) for folder in folders)
        if len(self.folder_cache) + len(totals) > 4096:
            self.folder_cache.clear()
        for folder, details in list(totals.items())[-4096:]:
            self.folder_cache[(self.relative(folder), folder.stat(follow_symlinks=False).st_mtime_ns)] = (now, details)
        return totals[path]

    def entry(self, path: Path, folder_details: bool = True) -> dict:
        info = path.stat(follow_symlinks=False)
        folder = stat.S_ISDIR(info.st_mode)
        entry = {'name': path.name, 'path': self.relative(path), 'type': 'folder' if folder else 'file', 'size': 0 if folder else info.st_size, 'modified': info.st_mtime, 'mime': 'inode/directory' if folder else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream')}
        if folder and folder_details:
            entry.update(self.folder_details(path))
        return entry

    def walk(self, directory: Path, recursive: bool):
        with os.scandir(directory) as entries:
            for item in entries:
                if item.name == '.DS_Store' or item.is_symlink():
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
                    entry = self.entry(item, folder_details=sort == 'size')
                except FileNotFoundError:
                    continue
                total += 1
                yield entry

        def key(item):
            value = item['name'].casefold() if sort == 'name' else item['mime'] if sort == 'type' else item['modified'] if sort == 'modified' else item['size']
            return (item['type'] != 'folder', value, item['path'])

        select = heapq.nlargest if direction == 'desc' else heapq.nsmallest
        page = select(offset + limit, candidates(), key=key)[offset:]
        for entry in page:
            if entry['type'] == 'folder' and 'child_count' not in entry:
                entry.update(self.folder_details(self.root / entry['path']))
        return {'items': page, 'total': total, 'offset': offset, 'limit': limit, 'path': path}

    def free_destination(self, destination: Path):
        if destination.exists() or destination.is_symlink():
            raise HTTPException(409, 'A file or folder with this name already exists')

    def invalidate(self):
        self.stats_time = 0
        self.folder_cache.clear()

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
                internal_sizes = {}
                for key, directory in [('trash_bytes', 'trash'), ('versions_bytes', 'versions'), ('uploads_bytes', 'uploads'), ('cache_bytes', 'previews'), ('exports_bytes', 'exports')]:
                    location = self.settings.internal_path / directory
                    internal_sizes[key] = sum(path.stat().st_size for path in self.walk(location, True) if path.is_file()) if location.is_dir() else 0
                disk = shutil.disk_usage(self.root)
                self.stats_cache = {'file_count': count, 'stored_bytes': size, 'disk_free': disk.free, 'disk_total': disk.total, 'disk_used': disk.used, **internal_sizes, 'system_bytes': max(0, disk.used - size - sum(internal_sizes.values())), 'disk_percent': round(disk.used / disk.total * 100, 1), 'categories': categories}
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
