import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import Settings
from app.database import Share, User
from app.main import create_app
from app.services.security import hasher


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(create_default_folders=False, storage_path=tmp_path / 'storage', database_path=tmp_path / 'metadata/database.db', internal_path=tmp_path / 'internal', _env_file=None))


@pytest.fixture
def client(app):
    with TestClient(app) as connection:
        yield connection


def put(client, name='hello.txt', content=b'hello', path=''):
    return client.post('/api/files/upload', params={'path': path}, files={'files': (name, content)})


def test_file_lifecycle(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/api/files').json()['total'] == 0
    assert client.post('/api/folders', json={'name': 'Photos'}).status_code == 201
    assert put(client).status_code == 201
    assert client.get('/api/files/download', params={'path': 'hello.txt'}).content == b'hello'
    assert client.patch('/api/files/rename', json={'path': 'hello.txt', 'name': 'renamed.txt'}).status_code == 200
    assert client.post('/api/files/move', json={'path': 'renamed.txt', 'destination': 'Photos'}).status_code == 200
    assert client.get('/api/files', params={'path': 'Photos'}).json()['items'][0]['name'] == 'renamed.txt'
    deleted = client.request('DELETE', '/api/files', json={'path': 'Photos'}).json()
    assert client.get('/api/files').json()['total'] == 0
    assert client.get('/api/trash').json()['total'] == 1
    assert client.post('/api/trash/restore', json=deleted).status_code == 200
    assert client.get('/api/files/download', params={'path': 'Photos/renamed.txt'}).content == b'hello'
    assert client.get('/api/trash').json()['total'] == 0


def test_conflicts_and_safe_restore(client):
    put(client)
    assert put(client, content=b'changed').status_code == 409
    assert client.get('/api/files/download', params={'path': 'hello.txt'}).content == b'hello'
    item = client.request('DELETE', '/api/files', json={'path': 'hello.txt'}).json()
    put(client, content=b'new')
    assert client.post('/api/trash/restore', json=item).status_code == 409
    assert client.get('/api/trash').json()['total'] == 1
    assert client.request('DELETE', '/api/trash', json=item).status_code == 200
    assert client.get('/api/trash').json()['total'] == 0


@pytest.mark.parametrize('path', ['../secrets', '/etc/passwd', 'a/../../secret', '..', 'a\\b', 'a//b', 'a/./b', 'x\x00y'])
def test_traversal(client, path):
    assert client.get('/api/files', params={'path': path}).status_code == 400
    assert client.get('/api/files/download', params={'path': path}).status_code == 400
    assert client.post('/api/folders', json={'path': path, 'name': 'bad'}).status_code == 400


@pytest.mark.parametrize('name', ['../bad', '..', '.', 'a/b', 'a\\b', ' bad', 'x\ny', 'x:y'])
def test_invalid_names(client, name):
    assert client.post('/api/folders', json={'name': name}).status_code == 400


def test_symlink_isolation(client, app, tmp_path):
    secret = tmp_path / 'outside'
    secret.mkdir()
    (secret / 'private.txt').write_text('secret')
    (app.state.settings.storage_path / 'escape').symlink_to(secret, target_is_directory=True)
    assert client.get('/api/files').json()['total'] == 0
    assert client.get('/api/files/download', params={'path': 'escape/private.txt'}).status_code == 400
    assert put(client, path='escape').status_code == 400
    assert client.post('/api/files/move', json={'path': 'escape', 'destination': ''}).status_code == 400


def test_upload_limit_and_cleanup(client, app):
    app.state.settings.max_upload_size_mb = 1
    response = put(client, content=b'x' * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert client.get('/api/files').json()['total'] == 0
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []


def test_multiple_uploads_rollback(client, app):
    app.state.settings.max_upload_size_mb = 1
    response = client.post('/api/files/upload', files=[('files', ('a.txt', b'ok')), ('files', ('b.txt', b'x' * (1024 * 1024 + 1)))])
    assert response.status_code == 413
    assert client.get('/api/files').json()['total'] == 0
    assert client.post('/api/files/upload', files=[('files', ('a.txt', b'a')), ('files', ('b.txt', b'b'))]).status_code == 201


def test_search_sort_pagination(client):
    client.post('/api/folders', json={'name': 'Folder'})
    put(client, 'Picture.PNG', b'image', path='Folder')
    put(client, 'beta.txt', b'12')
    put(client, 'alpha.txt', b'123')
    assert client.get('/api/search', params={'q': 'picture'}).json()['total'] == 0
    results = client.get('/api/search', params={'q': 'pICTUre', 'recursive': True}).json()
    assert results['items'][0]['path'] == 'Folder/Picture.PNG'
    results = client.get('/api/files', params={'sort': 'name', 'limit': 1, 'offset': 1}).json()
    assert results['total'] == 3
    assert results['items'][0]['name'] == 'alpha.txt'
    assert client.get('/api/files', params={'sort': 'bad'}).status_code == 422


def test_previews(client):
    put(client, 'photo.png', b'png')
    put(client, 'file.pdf', b'%PDF')
    put(client, 'script.html', b'<script></script>')
    assert client.get('/api/files/preview', params={'path': 'photo.png'}).headers['content-type'] == 'image/png'
    assert client.get('/api/files/preview', params={'path': 'file.pdf'}).status_code == 200
    assert client.get('/api/files/preview', params={'path': 'script.html'}).status_code == 415
    response = client.get('/api/files/download', params={'path': 'script.html'})
    assert response.headers['content-disposition'].startswith('attachment')
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_storage_stats(client):
    put(client, content=b'12345')
    stats = client.get('/api/storage/stats').json()
    assert stats['file_count'] == 1
    assert stats['stored_bytes'] == 5
    assert stats['disk_total'] >= stats['disk_free']
    client.request('DELETE', '/api/files', json={'path': 'hello.txt'})
    assert client.get('/api/storage/stats').json()['file_count'] == 0


def test_auth_disabled(client):
    assert client.get('/api/auth/me').json()['auth_enabled'] is False
    assert client.get('/api/files').status_code == 200
    assert client.post('/api/auth/users', json={'username': 'attacker', 'password': '1234567890'}).status_code == 403
    assert client.post('/api/auth/login', json={'username': 'x', 'password': 'x'}).status_code == 404


def test_auth_sessions_csrf_and_users(app):
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add(User(username='admin', password_hash=hasher.hash('correct-password'), role='admin'))
        db.commit()
    with TestClient(app) as client:
        assert client.get('/api/files').status_code == 401
        assert client.get('/api/files/download', params={'path': 'hello.txt'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'}).status_code == 401
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'correct-password'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie']
        assert 'SameSite=strict' in response.headers['set-cookie']
        assert client.get('/api/files').status_code == 200
        assert client.post('/api/folders', json={'name': 'private'}).status_code == 403
        csrf = response.json()['csrf_token']
        client.headers['X-CSRF-Token'] = csrf
        assert client.post('/api/folders', json={'name': 'private'}).status_code == 201
        assert client.post('/api/auth/users', json={'username': 'member', 'password': 'long-password'}).status_code == 201
        assert client.post('/api/auth/users', json={'username': 'member', 'password': 'long-password'}).status_code == 409
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/files').status_code == 401
        assert client.post('/api/auth/login', json={'username': 'member', 'password': 'long-password'}).status_code == 200
        client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf_token']
        assert client.post('/api/auth/users', json={'username': 'bad', 'password': 'long-password'}).status_code == 403


def test_sharing_disabled(client):
    assert client.get('/api/shares').status_code == 404
    assert client.get('/api/public/anything').status_code == 404


def test_share_lifecycle(client, app):
    app.state.settings.enable_public_shares = True
    put(client)
    share = client.post('/api/shares', json={'path': 'hello.txt', 'expires_hours': 1}).json()
    assert client.get(share['url']).content == b'hello'
    assert client.get('/api/public/invalid').status_code == 404
    client.patch('/api/files/rename', json={'path': 'hello.txt', 'name': 'new.txt'})
    assert client.get(share['url']).content == b'hello'
    assert client.delete('/api/shares/' + share['id']).status_code == 200
    assert client.get(share['url']).status_code == 404
    expired = client.post('/api/shares', json={'path': 'new.txt'}).json()
    with app.state.db() as db:
        item = db.get(Share, expired['id'])
        item.expires_at = time.time() - 1
        db.commit()
    assert client.get(expired['url']).status_code == 404
    assert client.post('/api/shares', json={'path': '../secret'}).status_code == 400


def test_share_works_without_login_and_revokes_on_trash(client, app):
    app.state.settings.enable_public_shares = True
    put(client)
    share = client.post('/api/shares', json={'path': 'hello.txt'}).json()
    app.state.settings.auth_enabled = True
    assert client.get('/api/files/download', params={'path': 'hello.txt'}).status_code == 401
    assert client.get(share['url']).status_code == 200
    app.state.settings.auth_enabled = False
    trash = client.request('DELETE', '/api/files', json={'path': 'hello.txt'}).json()
    client.post('/api/trash/restore', json=trash)
    assert client.get(share['url']).status_code == 404


def test_move_rejects_self_and_conflict(client):
    client.post('/api/folders', json={'name': 'A'})
    client.post('/api/folders', json={'name': 'child', 'path': 'A'})
    assert client.post('/api/files/move', json={'path': 'A', 'destination': 'A/child'}).status_code == 400
    put(client)
    put(client, path='A')
    assert client.post('/api/files/move', json={'path': 'hello.txt', 'destination': 'A'}).status_code == 409


def test_cross_origin_protection(client):
    assert client.post('/api/folders', headers={'Origin': 'https://evil.example'}, json={'name': 'bad'}).status_code == 403
    assert client.post('/api/folders', headers={'Sec-Fetch-Site': 'cross-site'}, json={'name': 'bad'}).status_code == 403


def test_persistence(app):
    with TestClient(app) as client:
        put(client)
        deleted = client.request('DELETE', '/api/files', json={'path': 'hello.txt'}).json()
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as client:
        assert client.get('/api/trash').json()['total'] == 1
        assert client.post('/api/trash/restore', json=deleted).status_code == 200
        assert client.get('/api/files/download', params={'path': 'hello.txt'}).content == b'hello'


def test_storage_cannot_contain_secrets(tmp_path):
    with pytest.raises(ValueError):
        create_app(Settings(create_default_folders=False, storage_path=tmp_path, database_path=tmp_path / 'private.db', internal_path=tmp_path / 'internal', _env_file=None))
