import os
import shutil
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import func, select
from ..database import Favorite, FileVersion, ItemMetadata, ItemTag, Share, Tag, TrashItem


def owner_key(user):
    return str(user['id']) if user else 'workspace'


def item_record(db, path, create=False):
    item = db.scalar(select(ItemMetadata).where(ItemMetadata.path == path))
    if item is None and create:
        item = ItemMetadata(id=uuid.uuid4().hex, path=path)
        db.add(item)
        db.flush()
    return item


def relocate_metadata(db, old, new):
    for item in db.scalars(select(ItemMetadata)):
        if item.path == old or item.path.startswith(old + '/'):
            item.path = new + item.path[len(old):]
    for share in db.scalars(select(Share).where(Share.revoked_at.is_(None))):
        if share.file_path == old or share.file_path.startswith(old + '/'):
            share.file_path = new + share.file_path[len(old):]


def trash_metadata(db, old, identifier):
    for item in db.scalars(select(ItemMetadata)):
        if item.path == old or item.path.startswith(old + '/'):
            item.path = ':trash:' + identifier + '/' + item.path
    for share in db.scalars(select(Share)):
        if share.file_path == old or share.file_path.startswith(old + '/'):
            share.revoked_at = time.time()


def restore_metadata(db, identifier):
    prefix = ':trash:' + identifier + '/'
    for item in db.scalars(select(ItemMetadata)):
        if item.path.startswith(prefix):
            item.path = item.path[len(prefix):]


def purge_metadata(db, identifier, settings):
    prefix = ':trash:' + identifier + '/'
    for item in db.scalars(select(ItemMetadata)):
        if item.path.startswith(prefix):
            for version in db.scalars(select(FileVersion).where(FileVersion.item_id == item.id)):
                (settings.internal_path / 'versions' / version.stored_path).unlink(missing_ok=True)
            db.delete(item)


def enrich(db, entries, owner):
    records = {record.path: record for record in db.scalars(select(ItemMetadata).where(ItemMetadata.path.in_([entry['path'] for entry in entries])))} if entries else {}
    ids = [record.id for record in records.values()]
    favorites = set(db.scalars(select(Favorite.item_id).where(Favorite.owner == owner, Favorite.item_id.in_(ids)))) if ids else set()
    tags = {}
    if ids:
        for item_id, tag in db.execute(select(ItemTag.item_id, Tag).join(Tag, Tag.id == ItemTag.tag_id).where(ItemTag.item_id.in_(ids)).order_by(Tag.name)):
            tags.setdefault(item_id, []).append({'id': tag.id, 'name': tag.name, 'color': tag.color})
    versions = dict(db.execute(select(FileVersion.item_id, func.count()).where(FileVersion.item_id.in_(ids)).group_by(FileVersion.item_id)).all()) if ids else {}
    for entry in entries:
        record = records.get(entry['path'])
        entry.update(favorite=bool(record and record.id in favorites), tags=tags.get(record.id, []) if record else [], color=record.color if record else None, version_count=versions.get(record.id, 0) if record else 0)
    return entries


def normalize_paths(fs, paths):
    unique = sorted(set(paths), key=lambda value: (value.count('/'), value))
    selected = []
    for value in unique:
        source = fs.path(value, allow_root=False)
        if any(source.is_relative_to(parent) for parent in selected):
            continue
        selected.append(source)
    return selected


def snapshot(fs, db, source):
    record = item_record(db, fs.relative(source), create=True)
    identifier = uuid.uuid4().hex
    target = fs.settings.internal_path / 'versions' / identifier
    target.parent.mkdir(parents=True, exist_ok=True)
    info = source.stat()
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as original, target.open('xb') as output:
            shutil.copyfileobj(original, output, 1024 * 1024)
        shutil.copystat(source, target, follow_symlinks=False)
        version = FileVersion(id=identifier, item_id=record.id, stored_path=identifier, size=info.st_size, modified=info.st_mtime)
        db.add(version)
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def install_file(fs, db, staged, destination, overwrite=False, original_mtime=None, original_size=None):
    fs.path(fs.relative(destination), exists=False, allow_root=False)
    if destination.exists() and not overwrite:
        raise HTTPException(409, 'A file with this name already exists')
    if destination.exists() and not destination.is_file():
        raise HTTPException(409, 'A folder already uses this name')
    if original_mtime is not None:
        if not destination.exists() or str(destination.stat().st_mtime_ns) != original_mtime or destination.stat().st_size != original_size:
            raise HTTPException(409, 'The original file changed. Start a new upload before replacing it')
    created_dirs = []
    parent = destination.parent
    while parent != fs.root and not parent.exists():
        created_dirs.append(parent)
        parent = parent.parent
    backup = None
    installed = False
    try:
        if destination.exists():
            backup = snapshot(fs, db, destination)
        for directory in reversed(created_dirs):
            directory.mkdir()
        os.replace(staged, destination)
        installed = True
        db.commit()
    except BaseException:
        db.rollback()
        if installed:
            os.replace(destination, staged)
            if backup:
                shutil.copy2(backup, destination)
        if backup:
            backup.unlink(missing_ok=True)
        for directory in created_dirs:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    fs.invalidate()
    return fs.entry(destination)


def bulk_move(fs, db, paths, destination):
    sources = normalize_paths(fs, paths)
    parent = fs.path(destination)
    if not parent.is_dir():
        raise HTTPException(400, 'Destination must be a folder')
    moves = [(source, parent / source.name) for source in sources if source.parent != parent]
    if len({target.name for _, target in moves}) != len(moves):
        raise HTTPException(409, 'Selected files have duplicate names')
    for source, target in moves:
        fs.free_destination(target)
        if source.is_dir() and target.is_relative_to(source):
            raise HTTPException(400, 'Cannot move a folder inside itself')
    completed = []
    try:
        for source, target in moves:
            os.rename(source, target)
            completed.append((source, target))
            relocate_metadata(db, fs.relative(source), fs.relative(target))
        db.commit()
    except BaseException:
        db.rollback()
        for source, target in reversed(completed):
            os.rename(target, source)
        raise
    fs.invalidate()
    return {'count': len(moves)}


def bulk_trash(fs, db, paths):
    sources = normalize_paths(fs, paths)
    completed = []
    try:
        for source in sources:
            identifier = uuid.uuid4().hex
            target = fs.settings.internal_path / 'trash' / identifier
            entry = fs.entry(source)
            os.rename(source, target)
            completed.append((source, target))
            db.add(TrashItem(id=identifier, original_path=entry['path'], stored_path=identifier, item_type=entry['type'], size=entry['size']))
            trash_metadata(db, entry['path'], identifier)
        db.commit()
    except BaseException:
        db.rollback()
        for source, target in reversed(completed):
            os.rename(target, source)
        raise
    fs.invalidate()
    return {'count': len(completed)}
