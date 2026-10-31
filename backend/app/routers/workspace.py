import heapq
import os
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from ..database import ArchiveExport, Favorite, FileVersion, ItemMetadata, ItemTag, Tag
from ..schemas import CompressInput, FileEntry, BatchInput, FavoriteInput, ItemTagsInput, TagInput
from ..services.archives import compress_folder, write_zip
from ..services.security import require_access
from ..services.workspace import bulk_move, bulk_trash, enrich, install_file, item_record, normalize_paths, owner_key

router = APIRouter(prefix='/api')


@router.get('/collection')
def collection(request: Request, favorite: bool = False, tag: str = '', q: str = '', sort: str = Query('name', pattern='^(name|size|type|modified)$'), direction: str = Query('asc', pattern='^(asc|desc)$'), offset: int = Query(0, ge=0, le=100000), limit: int = Query(80, ge=1, le=200), user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        query = select(ItemMetadata)
        if favorite:
            query = query.join(Favorite).where(Favorite.owner == owner_key(user))
        if tag:
            query = query.join(ItemTag).where(ItemTag.tag_id == tag)
        total = 0

        def entries():
            nonlocal total
            for record in db.scalars(query.execution_options(yield_per=100)):
                if record.path.startswith(':trash:') or q.casefold() not in Path(record.path).name.casefold():
                    continue
                try:
                    path = fs.path(record.path, allow_root=False)
                    entry = fs.entry(path)
                except HTTPException:
                    continue
                if entry['type'] not in {'file', 'folder'}:
                    continue
                total += 1
                yield entry

        def key(entry):
            value = entry['name'].casefold() if sort == 'name' else entry['mime'] if sort == 'type' else entry[sort]
            return (entry['type'] != 'folder', value, entry['path'])

        picker = heapq.nlargest if direction == 'desc' else heapq.nsmallest
        items = picker(offset + limit, entries(), key=key)[offset:]
        return {'items': enrich(db, items, owner_key(user)), 'total': total}


@router.post('/favorites')
def set_favorite(body: FavoriteInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        for path in body.paths:
            source = fs.path(path, allow_root=False)
            record = item_record(db, fs.relative(source), create=True)
            favorite = db.get(Favorite, (owner_key(user), record.id))
            if body.favorite and favorite is None:
                db.add(Favorite(owner=owner_key(user), item_id=record.id))
            elif not body.favorite and favorite:
                db.delete(favorite)
        db.commit()
        return {'ok': True}


@router.get('/tags')
def tags(request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        return {'items': [{'id': tag.id, 'name': tag.name, 'color': tag.color} for tag in db.scalars(select(Tag).order_by(Tag.name))]}


@router.post('/tags', status_code=201)
def create_tag(body: TagInput, request: Request, user=Depends(require_access)):
    name = body.name.strip()
    if not name or any(ord(letter) < 32 for letter in name):
        raise HTTPException(400, 'Invalid tag name')
    with request.state.workspace.db() as db:
        if db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower())):
            raise HTTPException(409, 'This tag already exists')
        tag = Tag(id=uuid.uuid4().hex, name=name, color=body.color)
        db.add(tag)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, 'This tag already exists')
        return {'id': tag.id, 'name': tag.name, 'color': tag.color}


@router.patch('/tags/{identifier}')
def update_tag(identifier: str, body: TagInput, request: Request, user=Depends(require_access)):
    name = body.name.strip()
    if not name or any(ord(letter) < 32 for letter in name):
        raise HTTPException(400, 'Invalid tag name')
    with request.state.workspace.db() as db:
        tag = db.get(Tag, identifier)
        if not tag:
            raise HTTPException(404, 'Tag not found')
        other = db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower(), Tag.id != identifier))
        if other:
            raise HTTPException(409, 'This tag already exists')
        tag.name, tag.color = name, body.color
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, 'This tag already exists')
        return {'id': tag.id, 'name': tag.name, 'color': tag.color}


@router.delete('/tags/{identifier}')
def delete_tag(identifier: str, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        tag = db.get(Tag, identifier)
        if not tag:
            raise HTTPException(404, 'Tag not found')
        db.delete(tag)
        db.commit()
        return {'ok': True}


@router.post('/files/tags')
def assign_tags(body: ItemTagsInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        for identifier in body.tag_ids:
            if db.get(Tag, identifier) is None:
                raise HTTPException(404, 'Tag not found')
        for path in body.paths:
            source = fs.path(path, allow_root=False)
            record = item_record(db, fs.relative(source), create=True)
            if body.color is not None:
                if not source.is_dir():
                    raise HTTPException(400, 'Folder colors apply to folders')
                record.color = body.color
            if body.mode == 'replace':
                db.execute(delete(ItemTag).where(ItemTag.item_id == record.id))
            for identifier in set(body.tag_ids):
                if db.get(ItemTag, (record.id, identifier)) is None:
                    db.add(ItemTag(item_id=record.id, tag_id=identifier))
        db.commit()
        return {'ok': True}


@router.post('/files/batch/move')
def move_many(body: BatchInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        return bulk_move(fs, db, body.paths, body.destination)


@router.post('/files/batch/trash')
def trash_many(body: BatchInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        return bulk_trash(fs, db, body.paths)


@router.post('/files/archive', status_code=201)
def make_archive(body: BatchInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        directory = fs.settings.internal_path / 'exports'
        directory.mkdir(exist_ok=True)
        for expired in db.scalars(select(ArchiveExport).where(ArchiveExport.created_at < time.time() - 3600)):
            (directory / expired.id).unlink(missing_ok=True)
            db.delete(expired)
        sources = normalize_paths(fs, body.paths)
        identifier = uuid.uuid4().hex
        target = directory / identifier
        name = (sources[0].name if len(sources) == 1 else 'RootDrive files') + '.zip'
        try:
            write_zip(fs, sources, target)
            db.add(ArchiveExport(id=identifier, owner=owner_key(user), name=name))
            db.commit()
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        fs.invalidate()
        return {'url': '/api/exports/' + identifier, 'name': name}


@router.post('/files/compress', status_code=201, response_model=FileEntry)
def save_folder_zip(body: CompressInput, request: Request, user=Depends(require_access)):
    return compress_folder(request.state.workspace.fs, body.path, body.name)


@router.get('/exports/{identifier}')
def download_archive(identifier: str, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        export = db.get(ArchiveExport, identifier)
        if export is None or export.owner != owner_key(user) or export.created_at < time.time() - 3600:
            raise HTTPException(404, 'Archive expired. Create it again')
        target = request.state.workspace.settings.internal_path / 'exports' / export.id
        if not target.is_file():
            raise HTTPException(404, 'Archive is unavailable')
        return FileResponse(target, media_type='application/zip', filename=export.name)


@router.get('/files/versions')
def file_versions(request: Request, path: str, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        source = fs.path(path, allow_root=False)
        if not source.is_file():
            raise HTTPException(400, 'Choose a file')
        item = item_record(db, path)
        versions = db.scalars(select(FileVersion).where(FileVersion.item_id == item.id).order_by(FileVersion.created_at.desc())) if item else []
        return {'items': [{'id': version.id, 'size': version.size, 'modified': version.modified, 'created_at': version.created_at} for version in versions]}


def find_version(fs, db, identifier):
    version = db.get(FileVersion, identifier)
    item = db.get(ItemMetadata, version.item_id) if version else None
    if not item or item.path.startswith(':trash:'):
        raise HTTPException(404, 'Version not found')
    source = fs.path(item.path, allow_root=False)
    if not source.is_file():
        raise HTTPException(404, 'Current file is unavailable')
    return version, source


@router.get('/versions/{identifier}/download')
def download_version(identifier: str, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        version, source = find_version(fs, db, identifier)
        target = fs.settings.internal_path / 'versions' / version.stored_path
        if not target.is_file():
            raise HTTPException(404, 'Version data is unavailable')
        return FileResponse(target, media_type='application/octet-stream', filename=source.name)


@router.post('/versions/{identifier}/restore')
def restore_version(identifier: str, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        version, source = find_version(fs, db, identifier)
        saved = fs.settings.internal_path / 'versions' / version.stored_path
        if not saved.is_file():
            raise HTTPException(404, 'Version data is unavailable')
        staged = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
        try:
            with saved.open('rb') as original, staged.open('xb') as output:
                shutil.copyfileobj(original, output, 1024 * 1024)
            return install_file(fs, db, staged, source, overwrite=True)
        finally:
            staged.unlink(missing_ok=True)


@router.api_route('/files/media', methods=['GET', 'HEAD'])
def media(request: Request, path: str, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock:
        source = fs.path(path, allow_root=False)
        entry = fs.entry(source)
        if entry['type'] != 'file' or not (entry['mime'].startswith(('audio/', 'video/')) or entry['mime'] == 'application/pdf'):
            raise HTTPException(415, 'Media playback is not available for this file')
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        handle = os.fdopen(descriptor, 'rb')
        size = os.fstat(descriptor).st_size
    start, end, status = 0, size - 1, 200
    headers = {'Accept-Ranges': 'bytes', 'Content-Disposition': "inline; filename*=UTF-8''" + quote(source.name)}
    requested = request.headers.get('range')
    if requested:
        try:
            if not requested.startswith('bytes=') or ',' in requested:
                raise ValueError
            left, right = requested[6:].split('-', 1)
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                suffix = int(right)
                if suffix <= 0:
                    raise ValueError
                start = max(0, size - suffix)
            if start < 0 or start > end or start >= size:
                raise ValueError
        except ValueError:
            handle.close()
            return Response(status_code=416, headers={'Content-Range': f'bytes */{size}', 'Accept-Ranges': 'bytes'})
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    length = max(0, end - start + 1)
    headers['Content-Length'] = str(length)
    if request.method == 'HEAD':
        handle.close()
        return Response(status_code=status, media_type=entry['mime'], headers=headers)

    def chunks():
        remaining = length
        try:
            handle.seek(start)
            while remaining:
                block = handle.read(min(256 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block
        finally:
            handle.close()

    return StreamingResponse(chunks(), status_code=status, media_type=entry['mime'], headers=headers)
