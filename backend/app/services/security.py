import hashlib
import secrets
import time
from fastapi import HTTPException, Request
from sqlalchemy import select
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from ..database import Session, User

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def current_session(request: Request, db):
    token = request.cookies.get('rootdrive_session', '')
    return db.scalar(select(Session).where(Session.session_hash == digest(token), Session.expires_at > time.time()))


def require_access(request: Request):
    if not request.app.state.settings.auth_enabled:
        return None
    with request.app.state.db() as db:
        session = current_session(request, db)
        if not session:
            raise HTTPException(401, 'Please sign in')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.csrf_token):
                raise HTTPException(403, 'Invalid security token. Refresh and try again')
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, 'Account not found')
        return {'id': user.id, 'username': user.username, 'role': user.role}


def verify_password(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except VerificationError:
        return False
