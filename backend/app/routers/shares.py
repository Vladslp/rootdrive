import secrets
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, func
from ..database import Share, ShareProtection, ShareGrant
from ..schemas import ShareInput
from ..services.security import digest, require_access, hasher, verify_password

router = APIRouter(prefix='/api')


def enabled(request):
    if not request.app.state.settings.enable_public_shares:
        raise HTTPException(404, 'Public sharing is disabled')


def load_share(db, token):
    if not 20 <= len(token) <= 128:
        raise HTTPException(404, 'This link is unavailable')
    share = db.scalar(select(Share).where(Share.token_hash == digest(token), Share.revoked_at.is_(None)))
    if not share or (share.expires_at is not None and share.expires_at <= time.time()):
        raise HTTPException(404, 'This link has expired or is unavailable')
    return share


def cookie_name(token):
    return 'rd_share_' + digest(token)[:16]


def authorized(db, share, token, request):
    if db.get(ShareProtection, share.id) is None:
        return True
    grant = db.get(ShareGrant, digest(request.cookies.get(cookie_name(token), '')))
    return grant is not None and grant.share_id == share.id and grant.expires_at > time.time()


def public_target(fs, share, member):
    root = fs.path(share.file_path, allow_root=False)
    if not root.exists():
        raise HTTPException(404, 'This file is unavailable')
    if not member:
        return root
    if not root.is_dir() or member.startswith('/') or '\\' in member:
        raise HTTPException(400, 'Invalid shared path')
    for part in member.split('/'):
        fs.name(part)
    target = fs.path(share.file_path + '/' + member, allow_root=False)
    if root not in target.parents:
        raise HTTPException(400, 'Invalid shared path')
    return target


@router.get('/shares', dependencies=[Depends(require_access)])
def list_shares(request: Request, offset: int = Query(0, ge=0), limit: int = Query(80, ge=1, le=200)):
    enabled(request)
    with request.app.state.db() as db:
        query = select(Share).where(Share.revoked_at.is_(None)).order_by(Share.created_at.desc()).offset(offset).limit(limit)
        return {'items': [{'id': share.id, 'path': share.file_path, 'name': share.file_path.split('/')[-1], 'expires_at': share.expires_at, 'created_at': share.created_at, 'password_protected': db.get(ShareProtection, share.id) is not None} for share in db.scalars(query)], 'total': db.scalar(select(func.count()).select_from(Share).where(Share.revoked_at.is_(None)))}


@router.post('/shares', status_code=201, dependencies=[Depends(require_access)])
def create_share(body: ShareInput, request: Request):
    enabled(request)
    fs = request.app.state.fs
    password_hash = hasher.hash(body.password) if body.password else None
    with fs.lock, request.app.state.db() as db:
        path = fs.path(body.path, allow_root=False)
        if not path.is_file() and not path.is_dir():
            raise HTTPException(404, 'File or folder not found')
        token = secrets.token_urlsafe(32)
        share = Share(id=uuid.uuid4().hex, token_hash=digest(token), file_path=fs.relative(path), expires_at=time.time() + body.expires_hours * 3600 if body.expires_hours else None)
        db.add(share)
        db.flush()
        if password_hash:
            db.add(ShareProtection(share_id=share.id, password_hash=password_hash))
        db.commit()
        url = f'/share/{token}' if path.is_dir() or password_hash else f'/api/public/{token}'
        return {'id': share.id, 'url': url, 'expires_at': share.expires_at}


@router.delete('/shares/{identifier}', dependencies=[Depends(require_access)])
def revoke_share(identifier: str, request: Request):
    enabled(request)
    with request.app.state.db() as db:
        share = db.get(Share, identifier)
        if not share:
            raise HTTPException(404, 'Share not found')
        share.revoked_at = time.time()
        db.execute(delete(ShareGrant).where(ShareGrant.share_id == identifier))
        db.commit()
        return {'ok': True}


class UnlockInput(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post('/public/{token}/unlock')
def unlock(token: str, body: UnlockInput, request: Request, response: Response):
    enabled(request)
    address = request.client.host if request.client else 'unknown'
    key = 'share:' + address
    with request.app.state.fs.lock:
        attempts = request.app.state.login_attempts[key]
        now = time.monotonic()
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, 'Too many attempts. Try again in five minutes')
        attempts.append(now)
    with request.app.state.db() as db:
        share = load_share(db, token)
        protection = db.get(ShareProtection, share.id)
        if protection and not verify_password(body.password, protection.password_hash):
            raise HTTPException(403, 'Incorrect link password')
        grant = secrets.token_urlsafe(32)
        expires = min(time.time() + 3600, share.expires_at or float('inf'))
        db.execute(delete(ShareGrant).where(ShareGrant.expires_at < time.time()))
        db.add(ShareGrant(token_hash=digest(grant), share_id=share.id, expires_at=expires))
        db.commit()
        response.set_cookie(cookie_name(token), grant, httponly=True, secure=request.app.state.settings.cookie_secure, samesite='strict', max_age=max(1, int(expires - time.time())), path=f'/api/public/{token}')
    return {'ok': True}


@router.get('/public/{token}/info')
def public_info(token: str, request: Request):
    enabled(request)
    with request.app.state.fs.lock, request.app.state.db() as db:
        share = load_share(db, token)
        path = public_target(request.app.state.fs, share, '')
        return {'name': path.name, 'type': 'folder' if path.is_dir() else 'file', 'locked': not authorized(db, share, token, request), 'expires_at': share.expires_at}


@router.get('/public/{token}/list')
def public_listing(token: str, request: Request, path: str = '', offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=120)):
    enabled(request)
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        share = load_share(db, token)
        if not authorized(db, share, token, request):
            raise HTTPException(403, 'Unlock this link first')
        target = public_target(fs, share, path)
        result = fs.listing(fs.relative(target), '', False, 'name', 'asc', offset, limit)
        prefix = share.file_path + '/'
        for item in result['items']:
            item['path'] = item['path'].removeprefix(prefix)
        return result


@router.get('/public/{token}')
def public_file(token: str, request: Request, path: str = ''):
    enabled(request)
    fs = request.app.state.fs
    with fs.lock, request.app.state.db() as db:
        share = load_share(db, token)
        if not authorized(db, share, token, request):
            raise HTTPException(403, 'Unlock this link first')
        target = public_target(fs, share, path)
        return fs.response(fs.relative(target))
