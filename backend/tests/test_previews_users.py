import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.database import User
from app.services.security import hasher
from test_rootdrive import app, client, put


def image_bytes(format='PNG', size=(1000, 600), mode='RGB'):
    buffer = io.BytesIO()
    Image.new(mode, size, (70, 130, 190, 128) if mode == 'RGBA' else (70, 130, 190)).save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize('name,format', [('photo.png', 'PNG'), ('photo.jpg', 'JPEG'), ('photo.heic', 'HEIF')])
def test_photo_thumbnails_preserve_original(client, name, format):
    original = image_bytes(format)
    assert put(client, name, original).status_code == 201
    response = client.get('/api/files/thumbnail', params={'path': name})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/jpeg'
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (640, 384)
    assert client.get('/api/files/download', params={'path': name}).content == original
    if format == 'HEIF':
        preview = client.get('/api/files/preview', params={'path': name})
        assert preview.status_code == 200
        assert preview.headers['content-type'] == 'image/jpeg'


def test_thumbnail_cache_and_invalidation(client, app):
    put(client, 'photo.png', image_bytes())
    first = client.get('/api/files/thumbnail', params={'path': 'photo.png'})
    second = client.get('/api/files/thumbnail', params={'path': 'photo.png'})
    assert first.content == second.content
    assert len(list((app.state.settings.internal_path / 'previews').glob('*.jpg'))) == 1
    item = client.request('DELETE', '/api/files', json={'path': 'photo.png'}).json()
    assert client.get('/api/files/thumbnail', params={'path': 'photo.png'}).status_code == 404
    client.post('/api/trash/restore', json=item)
    assert client.get('/api/files/thumbnail', params={'path': 'photo.png'}).status_code == 200


def test_preview_limits_and_invalid_images(client, app):
    put(client, 'broken.heic', b'not an image')
    put(client, 'text.txt', b'text')
    assert client.get('/api/files/thumbnail', params={'path': 'broken.heic'}).status_code == 415
    assert client.get('/api/files/thumbnail', params={'path': 'text.txt'}).status_code == 415
    assert client.get('/api/files/thumbnail', params={'path': '../outside.png'}).status_code == 400
    put(client, 'large.png', image_bytes())
    app.state.settings.max_preview_pixels = 100
    assert client.get('/api/files/thumbnail', params={'path': 'large.png'}).status_code == 415
    assert list((app.state.settings.internal_path / 'previews').glob('*.tmp')) == []


def test_preview_symlink_protection(client, app, tmp_path):
    outside = tmp_path / 'outside.png'
    outside.write_bytes(image_bytes())
    (app.state.settings.storage_path / 'link.png').symlink_to(outside)
    assert client.get('/api/files/thumbnail', params={'path': 'link.png'}).status_code == 400


def test_rgba_thumbnail(client):
    put(client, 'transparent.png', image_bytes(mode='RGBA'))
    response = client.get('/api/files/thumbnail', params={'path': 'transparent.png'})
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.mode == 'RGB'


def test_user_list_access_and_pagination(client, app):
    assert client.get('/api/auth/users').status_code == 403
    app.state.settings.auth_enabled = True
    assert client.get('/api/auth/users').status_code == 401
    with app.state.db() as db:
        db.add(User(username='admin', password_hash=hasher.hash('long-password'), role='admin'))
        db.commit()
    client.post('/api/auth/login', json={'username': 'admin', 'password': 'long-password'})
    csrf = client.get('/api/auth/me').json()['csrf_token']
    client.headers['X-CSRF-Token'] = csrf
    assert client.post('/api/auth/users', json={'username': 'member', 'password': 'long-password'}).status_code == 201
    result = client.get('/api/auth/users', params={'limit': 1}).json()
    assert result['total'] == 2
    assert len(result['items']) == 1
    assert set(result['items'][0]) == {'id', 'username', 'role', 'created_at'}
    assert client.get('/api/auth/users', params={'offset': 1, 'limit': 1}).json()['items'][0]['username'] == 'member'
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'member', 'password': 'long-password'})
    assert client.get('/api/auth/users').status_code == 403
    assert client.get('/api/files/thumbnail', params={'path': 'missing.png'}).status_code == 404
    client.cookies.clear()
    assert client.get('/api/files/thumbnail', params={'path': 'missing.png'}).status_code == 401
