import heapq
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from ..database import Album, AlbumItem, ItemMetadata
from ..services.security import require_access
from ..services.workspace import item_record, owner_key

router = APIRouter(prefix='/api', dependencies=[Depends(require_access)])
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif', '.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2', '.raf'}


class AlbumInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AlbumPaths(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)


def owned_album(db, identifier, user):
    album = db.get(Album, identifier)
    if not album or album.owner != owner_key(user):
        raise HTTPException(404, 'Album not found')
    return album


@router.get('/albums')
def albums(request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        return {'items': [{'id': item.id, 'name': item.name} for item in db.scalars(select(Album).where(Album.owner == owner_key(user)).order_by(Album.created_at))]}


@router.post('/albums', status_code=201)
def create_album(body: AlbumInput, request: Request, user=Depends(require_access)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'Give the album a name')
    with request.state.workspace.db() as db:
        album = Album(id=uuid.uuid4().hex, owner=owner_key(user), name=name)
        db.add(album)
        db.commit()
        return {'id': album.id, 'name': album.name}


@router.delete('/albums/{identifier}')
def delete_album(identifier: str, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        db.delete(owned_album(db, identifier, user))
        db.commit()
    return {'ok': True}


@router.post('/albums/{identifier}/items')
def add_photos(identifier: str, body: AlbumPaths, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        owned_album(db, identifier, user)
        for value in body.paths:
            path = fs.path(value, allow_root=False)
            if not path.is_file() or path.suffix.lower() not in PHOTO_EXTENSIONS:
                raise HTTPException(415, 'Albums contain photos only')
            item = item_record(db, value, create=True)
            if db.get(AlbumItem, (identifier, item.id)) is None:
                db.add(AlbumItem(album_id=identifier, item_id=item.id))
        db.commit()
    return {'ok': True}


@router.delete('/albums/{identifier}/items')
def remove_photos(identifier: str, body: AlbumPaths, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        owned_album(db, identifier, user)
        for value in body.paths:
            item = item_record(db, value, create=False)
            relation = db.get(AlbumItem, (identifier, item.id)) if item else None
            if relation:
                db.delete(relation)
        db.commit()
    return {'ok': True}


@router.get('/gallery')
def gallery(request: Request, album: str = '', offset: int = Query(0, ge=0, le=100000), limit: int = Query(60, ge=1, le=120), user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        if album:
            owned_album(db, album, user)
            values = db.scalars(select(ItemMetadata.path).join(AlbumItem, AlbumItem.item_id == ItemMetadata.id).where(AlbumItem.album_id == album))
            def album_paths():
                for value in values:
                    if value.startswith(':trash:'):
                        continue
                    try:
                        yield fs.path(value, allow_root=False)
                    except HTTPException:
                        continue
            paths = album_paths()
        else:
            paths = fs.walk(fs.root, True)
        count = 0
        def photos():
            nonlocal count
            for path in paths:
                try:
                    if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS:
                        count += 1
                        yield fs.entry(path)
                except FileNotFoundError:
                    continue
        items = heapq.nsmallest(offset + limit, photos(), key=lambda item: (-item['modified'], item['path']))
        return {'items': items[offset:], 'total': count}
