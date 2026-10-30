import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session as DatabaseSession
from app.database import User, Session
from app.services.security import hasher, verify_password
from test_rootdrive import app, client


def sign_in(client):
    result = client.post('/api/auth/login', json={'username': 'member', 'password': 'original-password'})
    assert result.status_code == 200
    client.headers['X-CSRF-Token'] = result.json()['csrf_token']
    return client.cookies.get('rootdrive_session')


def enable(app):
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add(User(username='member', password_hash=hasher.hash('original-password'), role='user'))
        db.commit()


def change(client, **values):
    return client.post('/api/auth/password', json={'current_password': 'original-password', 'new_password': 'new-passphrase-123', **values})


def test_password_change_rotates_cookie_csrf_and_revokes_other_sessions(client, app):
    enable(app)
    old_cookie = sign_in(client)
    old_csrf = client.headers['X-CSRF-Token']
    with TestClient(app) as other:
        sign_in(other)
        result = change(client)
        assert result.status_code == 200, result.text
        assert client.cookies.get('rootdrive_session') != old_cookie
        assert result.json()['csrf_token'] != old_csrf
        assert 'httponly' in result.headers['set-cookie'].lower()
        assert 'samesite=strict' in result.headers['set-cookie'].lower()
        assert other.get('/api/files').status_code == 401
    assert client.get('/api/files').status_code == 200
    assert client.post('/api/folders', json={'name': 'old csrf'}).status_code == 403
    client.headers['X-CSRF-Token'] = result.json()['csrf_token']
    assert client.post('/api/folders', json={'name': 'new csrf'}).status_code == 201
    with app.state.db() as db:
        user = db.scalar(select(User))
        assert verify_password('new-passphrase-123', user.password_hash)
        assert not verify_password('original-password', user.password_hash)
        assert db.scalar(select(func.count()).select_from(Session)) == 1
    client.cookies.clear()
    assert sign_in_old_fails(client)
    assert client.post('/api/auth/login', json={'username': 'member', 'password': 'new-passphrase-123'}).status_code == 200


def sign_in_old_fails(client):
    return client.post('/api/auth/login', json={'username': 'member', 'password': 'original-password'}).status_code == 401


def test_password_change_requires_auth_csrf_and_current_password(client, app):
    assert change(client).status_code == 404
    enable(app)
    assert change(client).status_code == 401
    sign_in(client)
    csrf = client.headers.pop('X-CSRF-Token')
    assert change(client).status_code == 403
    client.headers['X-CSRF-Token'] = csrf
    assert change(client, current_password='wrong').status_code == 400
    assert change(client, new_password='short').status_code == 422
    assert change(client, new_password='original-password').status_code == 400
    assert client.get('/api/files').status_code == 200


def test_password_change_throttles_wrong_current_password(client, app):
    enable(app)
    sign_in(client)
    for _ in range(5):
        assert change(client, current_password='wrong').status_code == 400
    assert change(client).status_code == 429

def test_failed_password_transaction_keeps_the_original_password_and_session(client, app, monkeypatch):
    enable(app)
    original_cookie = sign_in(client)
    def fail(self):
        raise RuntimeError('Database failed')
    with monkeypatch.context() as patcher:
        patcher.setattr(DatabaseSession, 'commit', fail)
        with pytest.raises(RuntimeError):
            change(client)
    assert client.cookies.get('rootdrive_session') == original_cookie
    assert client.get('/api/files').status_code == 200
    with app.state.db() as db:
        assert verify_password('original-password', db.scalar(select(User)).password_hash)
        assert db.scalar(select(func.count()).select_from(Session)) == 1
