import heapq
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from ..database import ItemMetadata, PinnedFolder, Playlist, PlaylistItem
from ..services.security import require_access
from ..services.workspace import item_record, owner_key

router = APIRouter(prefix='/api/library', dependencies=[Depends(require_access)])


class PathInput(BaseModel):
    path: str = Field(max_length=4096)


class PlaylistInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PlaylistPaths(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)


def owned_playlist(db, identifier, user):
    playlist = db.get(Playlist, identifier)
    if not playlist or playlist.owner != owner_key(user):
        raise HTTPException(404, 'Playlist not found')
    return playlist


@router.get('/pins')
def pins(request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        items = []
        for path in db.scalars(select(ItemMetadata.path).join(PinnedFolder).where(PinnedFolder.owner == owner_key(user)).limit(40)):
            if path.startswith(':trash:'):
                continue
            try:
                source = fs.path(path, allow_root=False)
                if source.is_dir():
                    items.append({'path': path, 'name': source.name})
            except HTTPException:
                continue
        return {'items': items}


@router.post('/pins')
def pin(body: PathInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        source = fs.path(body.path, allow_root=False)
        if not source.is_dir():
            raise HTTPException(400, 'Pin a folder')
        record = item_record(db, body.path, create=True)
        if not db.get(PinnedFolder, (owner_key(user), record.id)):
            count = db.scalar(select(func.count()).select_from(PinnedFolder).where(PinnedFolder.owner == owner_key(user)))
            if count >= 40:
                raise HTTPException(409, 'You can pin up to 40 folders')
            db.add(PinnedFolder(owner=owner_key(user), item_id=record.id))
        db.commit()
    return {'ok': True}


@router.delete('/pins')
def unpin(body: PathInput, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        record = item_record(db, body.path)
        relation = db.get(PinnedFolder, (owner_key(user), record.id)) if record else None
        if relation:
            db.delete(relation)
            db.commit()
    return {'ok': True}


@router.get('/playlists')
def playlists(request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        return {'items': [{'id': item.id, 'name': item.name} for item in db.scalars(select(Playlist).where(Playlist.owner == owner_key(user)).order_by(Playlist.name))]}


@router.post('/playlists', status_code=201)
def create_playlist(body: PlaylistInput, request: Request, user=Depends(require_access)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'Give the playlist a name')
    with request.state.workspace.db() as db:
        playlist = Playlist(id=uuid.uuid4().hex, owner=owner_key(user), name=name)
        db.add(playlist)
        db.commit()
        return {'id': playlist.id, 'name': name}


@router.delete('/playlists/{identifier}')
def delete_playlist(identifier: str, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        db.delete(owned_playlist(db, identifier, user))
        db.commit()
    return {'ok': True}


@router.post('/playlists/{identifier}/items')
def add_tracks(identifier: str, body: PlaylistPaths, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        owned_playlist(db, identifier, user)
        position = db.scalar(select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == identifier)) or 0
        for value in body.paths:
            source = fs.path(value, allow_root=False)
            if not source.is_file() or not fs.entry(source)['mime'].startswith('audio/'):
                raise HTTPException(415, 'Playlists contain audio files only')
            record = item_record(db, value, create=True)
            if not db.get(PlaylistItem, (identifier, record.id)):
                position += 1
                db.add(PlaylistItem(playlist_id=identifier, item_id=record.id, position=position))
        db.commit()
    return {'ok': True}


@router.delete('/playlists/{identifier}/items')
def remove_tracks(identifier: str, body: PlaylistPaths, request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        owned_playlist(db, identifier, user)
        for value in body.paths:
            record = item_record(db, value)
            item = db.get(PlaylistItem, (identifier, record.id)) if record else None
            if item:
                db.delete(item)
        db.commit()
    return {'ok': True}


@router.get('/audio')
def audio(request: Request, playlist: str = '', offset: int = Query(0, ge=0, le=100000), limit: int = Query(60, ge=1, le=120), user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        total = 0
        if playlist:
            owned_playlist(db, playlist, user)
            values = db.scalars(select(ItemMetadata.path).join(PlaylistItem).where(PlaylistItem.playlist_id == playlist).order_by(PlaylistItem.position))
            def playlist_paths():
                for value in values:
                    if value.startswith(':trash:'):
                        continue
                    try:
                        yield fs.path(value, allow_root=False)
                    except HTTPException:
                        continue
            paths = playlist_paths()
        else:
            paths = fs.walk(fs.root, True)
        def candidates():
            nonlocal total
            for source in paths:
                if not source.is_file():
                    continue
                entry = fs.entry(source)
                if entry['mime'].startswith('audio/'):
                    total += 1
                    yield entry
        if playlist:
            items = [item for index, item in enumerate(candidates()) if offset <= index < offset + limit]
        else:
            items = heapq.nsmallest(offset + limit, candidates(), key=lambda item: item['name'].casefold())[offset:]
        return {'items': items, 'total': total}
