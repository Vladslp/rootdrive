import hashlib
import os
import shutil
import uuid
from sqlalchemy import select
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
