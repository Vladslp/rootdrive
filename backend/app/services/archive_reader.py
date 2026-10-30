import mimetypes
import os
import shutil
import stat
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import PurePosixPath
from fastapi import HTTPException
from .io import open_regular
from .transfers import publish_directory


@contextmanager
def open_archive(fs, value):
    try:
        with open_regular(fs, value) as (path, handle):
            if path.suffix.lower() != '.zip':
                raise HTTPException(415, 'Choose a ZIP archive')
            with zipfile.ZipFile(handle) as archive:
                yield archive, archive_members(fs, archive)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise HTTPException(415, 'This ZIP is damaged, encrypted or unsupported')


def archive_members(fs, archive):
    infos = archive.infolist()
    if len(infos) > 10000:
        raise HTTPException(413, 'The archive contains too many items')
    total = 0
    members = {}
    directories = set()
    for info in infos:
        name = info.filename.rstrip('/')
        if not name or info.filename.startswith('/') or '\\' in name or '\x00' in name:
            raise HTTPException(400, 'The archive contains an unsafe path')
        parts = name.split('/')
        for part in parts:
            fs.name(part)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not stat.S_ISREG(mode) and not stat.S_ISDIR(mode)):
            raise HTTPException(400, 'Archive links and special files are not supported')
        if name in members or info.flag_bits & 1:
            raise HTTPException(415, 'Duplicate or encrypted archive entries are unsupported')
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise HTTPException(415, 'This ZIP compression method is unsupported')
        if info.file_size > fs.settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(413, 'An archive member exceeds the file size limit')
        total += info.file_size
        if total > fs.settings.max_archive_expanded_mb * 1024 * 1024 or (info.file_size > 1024 * 1024 and info.file_size > max(1, info.compress_size) * 1000):
            raise HTTPException(413, 'The expanded archive exceeds safety limits')
        members[name] = info
        for index in range(1, len(parts)):
            directories.add('/'.join(parts[:index]))
        if info.is_dir():
            directories.add(name)
    if any(name in directories and not info.is_dir() for name, info in members.items()):
        raise HTTPException(400, 'Archive files and folders have conflicting paths')
    return members


def archive_listing(fs, value, prefix='', offset=0, limit=100):
    with fs.lock, open_archive(fs, value) as (_, members):
        if prefix and prefix not in {name for member in members for name in [str(PurePosixPath(member).parent), member]}:
            if not any(name.startswith(prefix + '/') for name in members):
                raise HTTPException(404, 'Archive folder not found')
        entries = {}
        for name, info in members.items():
            if prefix and not name.startswith(prefix + '/'):
                continue
            relative = name[len(prefix) + 1:] if prefix else name
            if not relative:
                continue
            first, _, rest = relative.partition('/')
            path = prefix + '/' + first if prefix else first
            folder = bool(rest) or info.is_dir()
            previous = entries.get(path)
            if previous is None:
                previous = {'name': first, 'path': path, 'type': 'folder' if folder else 'file', 'size': 0, 'mime': 'inode/directory' if folder else mimetypes.guess_type(first)[0] or 'application/octet-stream'}
                entries[path] = previous
            previous['size'] += info.file_size
        items = sorted(entries.values(), key=lambda item: (item['type'] != 'folder', item['name'].casefold(), item['path']))
        return {'items': items[offset:offset + limit], 'total': len(items), 'prefix': prefix}


def extract_archive(fs, value, destination, name=None, selected=None):
    with fs.lock:
        source = fs.path(value, allow_root=False)
        parent = fs.path(destination)
        if not parent.is_dir():
            raise HTTPException(400, 'Choose a destination folder')
        name = name or source.stem.encode()[:220].decode('utf-8', errors='ignore') + ' extracted'
        target = parent / fs.name(name)
        fs.free_destination(target)
        stage = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
        stage.mkdir()
        try:
            with open_archive(fs, value) as (archive, members):
                if selected:
                    for selected_name in selected:
                        if selected_name not in members and not any(item.startswith(selected_name + '/') for item in members):
                            raise HTTPException(404, 'A selected archive member is missing')
                for member, info in members.items():
                    if selected and not any(member == item or member.startswith(item + '/') for item in selected):
                        continue
                    output = stage.joinpath(*member.split('/'))
                    if info.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                    else:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        written = 0
                        with archive.open(info) as original, output.open('xb') as saved:
                            while block := original.read(1024 * 1024):
                                written += len(block)
                                if written > info.file_size:
                                    raise HTTPException(413, 'An archive member exceeds its declared size')
                                saved.write(block)
            publish_directory(stage, target)
            fs.invalidate()
            return fs.entry(target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
