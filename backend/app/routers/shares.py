import secrets
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from ..database import Share
from ..schemas import ShareInput
from ..services.security import digest, require_access

router = APIRouter(prefix='/api')


def enabled(request):
    if not request.app.state.settings.enable_public_shares:
        raise HTTPException(404, 'Public sharing is disabled')


@router.get('/shares', dependencies=[Depends(require_access)])
def list_shares(request: Request, offset: int = Query(0, ge=0), limit: int = Query(80, ge=1, le=200)):
    enabled(request)
    with request.app.state.db() as db:
        query = select(Share).where(Share.revoked_at.is_(None)).order_by(Share.created_at.desc()).offset(offset).limit(limit)
        return {'items': [{'id': share.id, 'path': share.file_path, 'name': share.file_path.split('/')[-1], 'expires_at': share.expires_at, 'created_at': share.created_at} for share in db.scalars(query)], 'total': db.scalar(select(func.count()).select_from(Share).where(Share.revoked_at.is_(None)))}


@router.post('/shares', status_code=201, dependencies=[Depends(require_access)])
def create_share(body: ShareInput, request: Request):
    enabled(request)
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        path = fs.path(body.path, allow_root=False)
        if not path.is_file():
            raise HTTPException(400, 'Share an individual file')
        token = secrets.token_urlsafe(32)
        share = Share(id=uuid.uuid4().hex, token_hash=digest(token), file_path=body.path, expires_at=time.time() + body.expires_hours * 3600 if body.expires_hours else None)
        db.add(share)
        db.commit()
        return {'id': share.id, 'url': f'/api/public/{token}', 'expires_at': share.expires_at}


@router.delete('/shares/{identifier}', dependencies=[Depends(require_access)])
def revoke_share(identifier: str, request: Request):
    enabled(request)
    with request.app.state.db() as db:
        share = db.get(Share, identifier)
        if not share:
            raise HTTPException(404, 'Share not found')
        share.revoked_at = time.time()
        db.commit()
        return {'ok': True}


@router.get('/public/{token}')
def public_file(token: str, request: Request):
    enabled(request)
    with request.app.state.fs.lock, request.app.state.db() as db:
        share = db.scalar(select(Share).where(Share.token_hash == digest(token), Share.revoked_at.is_(None)))
        if not share or (share.expires_at is not None and share.expires_at <= time.time()):
            raise HTTPException(404, 'This link has expired or is unavailable')
        return request.app.state.fs.response(share.file_path)
