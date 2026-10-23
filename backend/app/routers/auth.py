import secrets
import time
from collections import defaultdict, deque
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from ..database import Session, User
from ..schemas import LoginInput, UserInput
from ..services.security import DUMMY_HASH, current_session, digest, hasher, require_access, verify_password

router = APIRouter(prefix='/api/auth')


@router.get('/me')
def me(request: Request):
    settings = request.app.state.settings
    result = {'auth_enabled': settings.auth_enabled, 'shares_enabled': settings.enable_public_shares, 'max_upload_size_mb': settings.max_upload_size_mb, 'user': None, 'csrf_token': None}
    if settings.auth_enabled:
        with request.app.state.db() as db:
            session = current_session(request, db)
            if session and (user := db.get(User, session.user_id)):
                result.update(user={'id': user.id, 'username': user.username, 'role': user.role}, csrf_token=session.csrf_token)
    return result


@router.post('/login')
def login(body: LoginInput, request: Request, response: Response):
    settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(404, 'Authentication is disabled')
    address = request.client.host if request.client else 'unknown'
    with request.app.state.fs.lock:
        attempts = request.app.state.login_attempts[address]
        now = time.monotonic()
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, 'Too many attempts. Try again in five minutes')
        attempts.append(now)
    with request.app.state.db() as db:
        user = db.scalar(select(User).where(User.username == body.username))
        valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(401, 'Incorrect username or password')
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.execute(delete(Session).where(Session.expires_at < time.time()))
        db.add(Session(user_id=user.id, session_hash=digest(token), csrf_token=csrf, expires_at=time.time() + settings.session_hours * 3600))
        db.commit()
        response.set_cookie('rootdrive_session', token, httponly=True, secure=settings.cookie_secure, samesite='strict', max_age=settings.session_hours * 3600, path='/')
        return {'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'csrf_token': csrf}


@router.post('/logout')
def logout(request: Request, response: Response):
    require_access(request)
    with request.app.state.db() as db:
        session = current_session(request, db)
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie('rootdrive_session', path='/')
    return {'ok': True}


@router.post('/users', status_code=201)
def create_user(body: UserInput, request: Request):
    user = require_access(request)
    if not user or user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required')
    with request.app.state.db() as db:
        account = User(username=body.username, password_hash=hasher.hash(body.password), role=body.role)
        db.add(account)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'This username already exists')
        return {'id': account.id, 'username': account.username, 'role': account.role}
