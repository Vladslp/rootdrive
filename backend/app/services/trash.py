import hashlib
import os
import shutil
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from .workspace import restore_metadata
from ..database import FileVersion, ItemMetadata, TrashItem


def trash_revision(db):
    digest = hashlib.sha256()
    for identifier in db.scalars(select(TrashItem.id).order_by(TrashItem.id)).yield_per(200):
        digest.update(identifier.encode())
        digest.update(b'\x00')
    return digest.hexdigest()


def purge_items(fs, db, items):
    quarantine = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
    quarantine.mkdir()
    moved = []
    count = 0

    def stage(source):
        if source.exists() or source.is_symlink():
            target = quarantine / str(len(moved))
            os.rename(source, target)
            moved.append((source, target))

    try:
        for item in items:
            stage(fs.settings.internal_path / 'trash' / fs.name(item.stored_path))
            prefix = ':trash:' + item.id + '/'
            records = db.scalars(select(ItemMetadata).where(ItemMetadata.path.startswith(prefix, autoescape=True))).all()
            for record in records:
                for version in db.scalars(select(FileVersion).where(FileVersion.item_id == record.id)):
                    stage(fs.settings.internal_path / 'versions' / fs.name(version.stored_path))
                db.delete(record)
            db.delete(item)
            count += 1
        db.commit()
    except BaseException:
        db.rollback()
        for source, target in reversed(moved):
            os.rename(target, source)
        quarantine.rmdir()
        raise
    fs.invalidate()
    shutil.rmtree(quarantine)
    return {'count': count}

def restore_items(fs, db, identifiers):
    requested = set(identifiers)
    items = db.scalars(select(TrashItem).where(TrashItem.id.in_(requested))).all()
    if len(items) != len(requested):
        raise HTTPException(409, 'Selected items changed. Refresh Trash and try again')
    items.sort(key=lambda item: (item.original_path.count('/'), item.original_path, item.id))
    moved = []
    try:
        for item in items:
            destination = fs.path(item.original_path, exists=False, allow_root=False)
            fs.free_destination(destination)
            if not destination.parent.is_dir():
                raise HTTPException(409, f'Restore the parent folder first: {item.original_path}')
            source = fs.settings.internal_path / 'trash' / fs.name(item.stored_path)
            if source.is_symlink() or not source.exists():
                raise HTTPException(409, 'A selected Trash item is unavailable')
            os.rename(source, destination)
            moved.append((source, destination))
            restore_metadata(db, item.id)
            db.delete(item)
        db.commit()
    except BaseException:
        db.rollback()
        for source, destination in reversed(moved):
            os.rename(destination, source)
        raise
    fs.invalidate()
    return {'count': len(moved)}
