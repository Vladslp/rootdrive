import secrets
import time
from collections import defaultdict, deque
from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from ..database import Session, User
from ..release import RELEASE
from ..schemas import LoginInput, UserInput, PasswordChangeInput
from ..services.security import DUMMY_HASH, current_session, digest, hasher, require_access, verify_password

router = APIRouter(prefix='/api/auth')


@router.get('/me')
def me(request: Request):
    settings = request.app.state.settings
    result = {**RELEASE, 'auth_enabled': settings.auth_enabled, 'shares_enabled': settings.enable_public_shares, 'max_upload_size_mb': settings.max_upload_size_mb, 'user': None, 'csrf_token': None}
    if settings.auth_enabled:
        with request.app.state.db() as db:
            session = current_session(request, db)
            if session and (user := db.get(User, session.user_id)):
                result.update(user={'id': user.id, 'username': user.username, 'role': user.role}, csrf_token=session.csrf_token)
                try:
                    result['space'] = request.app.state.spaces.selected(request, user.id)
                except HTTPException:
                    result['space'] = {'id': request.cookies.get('rootdrive_space', 'shared'), 'name': 'Unavailable space', 'role': 'reader', 'owner': False, 'kind': 'unavailable'}
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
        response.delete_cookie('rootdrive_space', path='/')
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
    response.delete_cookie('rootdrive_space', path='/')
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


@router.get('/users')
def list_users(request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    user = require_access(request)
    if not user or user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required')
    with request.app.state.db() as db:
        users = db.scalars(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit))
        return {'items': [{'id': account.id, 'username': account.username, 'role': account.role, 'created_at': account.created_at} for account in users], 'total': db.scalar(select(func.count()).select_from(User))}

@router.post('/password')
def change_password(body: PasswordChangeInput, request: Request, response: Response):
    access = require_access(request)
    if access is None:
        raise HTTPException(404, 'Authentication is disabled')
    with request.app.state.fs.lock, request.app.state.db() as db:
        session = current_session(request, db)
        if session is None:
            raise HTTPException(401, 'Please sign in')
        attempts = request.app.state.login_attempts['password:' + str(access['id'])]
        now = time.monotonic()
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, 'Too many attempts. Try again in five minutes')
        attempts.append(now)
        user = db.get(User, session.user_id)
        if user is None or not verify_password(body.current_password, user.password_hash):
            raise HTTPException(400, 'Current password is incorrect')
        if body.current_password == body.new_password:
            raise HTTPException(400, 'Choose a different password')
        user.password_hash = hasher.hash(body.new_password)
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.execute(delete(Session).where(Session.user_id == user.id))
        settings = request.app.state.settings
        db.add(Session(user_id=user.id, session_hash=digest(token), csrf_token=csrf, expires_at=time.time() + settings.session_hours * 3600))
        db.commit()
        attempts.clear()
        response.set_cookie('rootdrive_session', token, httponly=True, secure=settings.cookie_secure, samesite='strict', max_age=settings.session_hours * 3600, path='/')
        return {'ok': True, 'csrf_token': csrf}
