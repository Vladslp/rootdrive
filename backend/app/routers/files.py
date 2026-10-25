import os
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from ..database import TrashItem
from ..schemas import CreateFileInput, FileEntry, FileListing, FolderInput, MoveInput, PathInput, RenameInput, StorageStats, TrashInput
from ..services.creation import create_file_contents
from ..services.security import require_access
from ..services.metadata import image_metadata
from ..services.workspace import install_file, enrich, owner_key, relocate_metadata, trash_metadata, restore_metadata, purge_metadata

router = APIRouter(prefix='/api', dependencies=[Depends(require_access)])


@router.get('/files', response_model=FileListing)
@router.get('/search', response_model=FileListing)
def list_files(request: Request, path: str = '', q: str = '', recursive: bool = False, sort: str = Query('name', pattern='^(name|size|type|modified)$'), direction: str = Query('asc', pattern='^(asc|desc)$'), offset: int = Query(0, ge=0, le=100000), limit: int = Query(80, ge=1, le=200), user=Depends(require_access)):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        listing = fs.listing(path, q, recursive, sort, direction, offset, limit)
        enrich(db, listing['items'], owner_key(user))
        return listing


@router.post('/files', status_code=201, response_model=FileEntry)
def create_file(body: CreateFileInput, request: Request):
    fs = request.app.state.fs
    staged = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
    try:
        with fs.lock, request.app.state.db() as db:
            parent = fs.path(body.path)
            if not parent.is_dir():
                raise HTTPException(400, 'Destination must be a folder')
            destination = parent / fs.name(body.name)
            fs.free_destination(destination)
            create_file_contents(staged, destination)
            return install_file(fs, db, staged, destination)
    finally:
        staged.unlink(missing_ok=True)


@router.post('/folders', status_code=201, response_model=FileEntry)
def create_folder(body: FolderInput, request: Request):
    fs = request.app.state.fs
    with fs.lock:
        parent = fs.path(body.path)
        if not parent.is_dir():
            raise HTTPException(400, 'Destination must be a folder')
        destination = parent / fs.name(body.name)
        fs.free_destination(destination)
        destination.mkdir()
        fs.invalidate()
        return fs.entry(destination)


@router.post('/files/upload', status_code=201)
def upload_files(request: Request, path: str = '', files: list[UploadFile] = File(...)):
    fs = request.app.state.fs
    if len(files) > 20:
        raise HTTPException(400, 'Upload up to 20 files per request')
    created, staged = [], []
    with fs.lock:
        try:
            parent = fs.path(path)
            if not parent.is_dir():
                raise HTTPException(400, 'Destination must be a folder')
            names = [fs.name(file.filename or '') for file in files]
            if len(set(names)) != len(names):
                raise HTTPException(409, 'Duplicate filenames in this upload')
            for name in names:
                fs.free_destination(parent / name)
            for file, name in zip(files, names):
                temporary = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
                staged.append(temporary)
                size = 0
                with temporary.open('xb') as output:
                    while block := file.file.read(1024 * 1024):
                        size += len(block)
                        if size > fs.settings.max_upload_size_mb * 1024 * 1024:
                            raise HTTPException(413, f'{name} exceeds the upload limit')
                        output.write(block)
                destination = parent / name
                try:
                    with destination.open('xb') as output, temporary.open('rb') as source:
                        created.append(destination)
                        while block := source.read(1024 * 1024):
                            output.write(block)
                except FileExistsError:
                    raise HTTPException(409, 'A file with this name already exists')
            fs.invalidate()
            return {'items': [fs.entry(path) for path in created]}
        except BaseException:
            for destination in created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            for temporary in staged:
                temporary.unlink(missing_ok=True)
            for file in files:
                file.file.close()


@router.get('/files/download')
def download_file(request: Request, path: str):
    return request.app.state.fs.response(path)


@router.get('/files/preview')
def preview_file(request: Request, path: str):
    if Path(path).suffix.lower() in {'.heic', '.heif', '.avif'}:
        return request.app.state.previews.response(path)
    return request.app.state.fs.response(path, preview=True)


@router.get('/files/thumbnail')
def thumbnail_file(request: Request, path: str):
    return request.app.state.previews.response(path, thumbnail=True)


def relocate(fs, db, source, destination):
    fs.free_destination(destination)
    if source.is_dir() and destination.is_relative_to(source):
        raise HTTPException(400, 'Cannot move a folder inside itself')
    old = fs.relative(source)
    os.rename(source, destination)
    try:
        relocate_metadata(db, old, fs.relative(destination))
        db.commit()
    except BaseException:
        os.rename(destination, source)
        raise
    fs.invalidate()
    return fs.entry(destination)


@router.patch('/files/rename', response_model=FileEntry)
def rename_file(body: RenameInput, request: Request):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        source = fs.path(body.path, allow_root=False)
        return relocate(fs, db, source, source.parent / fs.name(body.name))


@router.post('/files/move', response_model=FileEntry)
def move_file(body: MoveInput, request: Request):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        source = fs.path(body.path, allow_root=False)
        destination = fs.path(body.destination)
        if not destination.is_dir():
            raise HTTPException(400, 'Destination must be a folder')
        return relocate(fs, db, source, destination / source.name)


@router.delete('/files')
def delete_file(body: PathInput, request: Request):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        source = fs.path(body.path, allow_root=False)
        identifier = uuid.uuid4().hex
        destination = fs.settings.internal_path / 'trash' / identifier
        item = TrashItem(id=identifier, original_path=body.path, stored_path=identifier, item_type='folder' if source.is_dir() else 'file', size=0 if source.is_dir() else source.stat().st_size)
        os.rename(source, destination)
        try:
            db.add(item)
            trash_metadata(db, body.path, identifier)
            db.commit()
        except BaseException:
            os.rename(destination, source)
            raise
        fs.invalidate()
        return {'id': identifier}


@router.get('/trash')
def list_trash(request: Request, offset: int = Query(0, ge=0), limit: int = Query(80, ge=1, le=200)):
    from sqlalchemy import func
    with request.app.state.db() as db:
        items = db.scalars(select(TrashItem).order_by(TrashItem.deleted_at.desc()).offset(offset).limit(limit))
        return {'items': [{'id': item.id, 'name': Path(item.original_path).name, 'path': item.original_path, 'type': item.item_type, 'size': item.size, 'modified': item.deleted_at} for item in items], 'total': db.scalar(select(func.count()).select_from(TrashItem))}


@router.post('/trash/restore')
def restore_trash(body: TrashInput, request: Request):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        item = db.get(TrashItem, body.id)
        if not item:
            raise HTTPException(404, 'Trash item not found')
        destination = fs.path(item.original_path, exists=False, allow_root=False)
        fs.free_destination(destination)
        if not destination.parent.is_dir():
            raise HTTPException(409, 'Restore the parent folder first')
        source = fs.settings.internal_path / 'trash' / item.stored_path
        os.rename(source, destination)
        try:
            restore_metadata(db, item.id)
            db.delete(item)
            db.commit()
        except BaseException:
            os.rename(destination, source)
            raise
        fs.invalidate()
        return fs.entry(destination)


@router.delete('/trash')
def remove_trash(body: TrashInput, request: Request):
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        item = db.get(TrashItem, body.id)
        if not item:
            raise HTTPException(404, 'Trash item not found')
        source = fs.settings.internal_path / 'trash' / item.stored_path
        if source.is_dir():
            shutil.rmtree(source)
        else:
            source.unlink(missing_ok=True)
        purge_metadata(db, item.id, fs.settings)
        db.delete(item)
        db.commit()
        fs.invalidate()
        return {'ok': True}


@router.get('/storage/stats', response_model=StorageStats)
def storage_stats(request: Request):
    return request.app.state.fs.stats()


@router.get('/files/metadata')
def file_metadata(request: Request, path: str):
    return image_metadata(request.app.state.fs, path)
