import os
import time
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import User
from app.main import create_app
from app.services.security import hasher
from app.services.smart import LARGE_BYTES
from test_rootdrive import app, client, put


def smart(client, kind, **params):
    response = client.get('/api/smart-files', params={'kind': kind, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_smart_folders_find_nested_files_without_moving_them(client, app):
    client.post('/api/folders', json={'name': 'Nested'})
    put(client, 'PHOTO.HEIC', path='Nested')
    put(client, 'Raw.CR3', path='Nested')
    put(client, 'report.docx', path='Nested')
    put(client, 'song.mp3', path='Nested')
    put(client, 'style.css', path='Nested')
    assert {entry['path'] for entry in smart(client, 'photos')['items']} == {'Nested/PHOTO.HEIC', 'Nested/Raw.CR3'}
    assert {entry['path'] for entry in smart(client, 'documents')['items']} == {'Nested/report.docx'}
    assert smart(client, 'recent')['total'] == 5
    assert smart(client, 'large')['total'] == 0
    assert {path.name for path in app.state.fs.root.iterdir()} == {'Nested'}
    assert client.get('/api/files', params={'path': 'Nested'}).json()['total'] == 5


def test_recent_files_use_modified_time_and_large_files_use_inclusive_threshold(client, app):
    root = app.state.fs.root
    (root / 'old.txt').write_text('old')
    old = time.time() - 8 * 86400
    os.utime(root / 'old.txt', (old, old))
    for name, size in [('exact.bin', LARGE_BYTES), ('small.bin', LARGE_BYTES - 1), ('bigger.bin', LARGE_BYTES + 1)]:
        with (root / name).open('wb') as file:
            file.truncate(size)
    assert {item['name'] for item in smart(client, 'recent')['items']} == {'exact.bin', 'small.bin', 'bigger.bin'}
    assert [item['name'] for item in smart(client, 'large', sort='size', direction='desc')['items']] == ['bigger.bin', 'exact.bin']


@pytest.mark.parametrize('sort', ['name', 'size', 'type', 'modified'])
@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_smart_search_sort_and_pagination(client, app, sort, direction):
    root = app.state.fs.root
    for index, name in enumerate(['Travel C.JPG', 'Travel a.png', 'Travel b.webp', 'Other.gif']):
        (root / name).write_bytes(b'x' * (index + 1))
        os.utime(root / name, (1700000000 + index, 1700000000 + index))
    full = smart(client, 'photos', q='TRAVEL', sort=sort, direction=direction)
    assert full['total'] == 3
    entries = full['items']
    values = [(entry['name'].casefold() if sort == 'name' else entry['mime'] if sort == 'type' else entry[sort], entry['path']) for entry in entries]
    assert values == sorted(values, reverse=direction == 'desc')
    assert smart(client, 'photos', q='travel', sort=sort, direction=direction, offset=1, limit=1)['items'] == entries[1:2]
    assert smart(client, 'photos', offset=100)['items'] == []


def test_smart_folders_omit_trash_internal_files_symlinks_and_hidden_finder_files(client, app, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.jpg').write_bytes(b'secret')
    (app.state.fs.root / 'external').symlink_to(outside, target_is_directory=True)
    (app.state.fs.root / 'link.jpg').symlink_to(outside / 'secret.jpg')
    (app.state.fs.root / '.DS_Store').write_bytes(b'hidden')
    put(client, 'trashed.jpg')
    client.request('DELETE', '/api/files', json={'path': 'trashed.jpg'})
    (app.state.settings.internal_path / 'uploads' / 'staged.jpg').write_bytes(b'staged')
    assert smart(client, 'photos')['total'] == 0
    assert smart(client, 'recent')['total'] == 0


def test_smart_cache_invalidates_on_mutations_and_does_not_cache_user_metadata(client, app):
    put(client, 'first.jpg')
    assert smart(client, 'photos')['total'] == 1
    client.post('/api/favorites', json={'paths': ['first.jpg'], 'favorite': True})
    assert smart(client, 'photos')['items'][0]['favorite'] is True
    client.post('/api/favorites', json={'paths': ['first.jpg'], 'favorite': False})
    assert smart(client, 'photos')['items'][0]['favorite'] is False
    put(client, 'second.jpg')
    assert smart(client, 'photos')['total'] == 2
    client.patch('/api/files/rename', json={'path': 'first.jpg', 'name': 'first.txt'})
    assert smart(client, 'photos')['total'] == 1
    client.request('DELETE', '/api/files', json={'path': 'second.jpg'})
    assert smart(client, 'photos')['total'] == 0
    assert all(not entry.get('favorite') for _, listing in app.state.fs.smart_cache.values() for entry in listing['items'])


def test_smart_cache_is_bounded_and_expires(client, app, monkeypatch):
    from app.services import smart as service
    calls = []
    walk = app.state.fs.walk

    def tracked(*args):
        calls.append(args)
        yield from walk(*args)

    monkeypatch.setattr(app.state.fs, 'walk', tracked)
    smart(client, 'photos')
    smart(client, 'photos')
    assert len(calls) == 1
    clock = service.time.monotonic
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock() + 16)
    smart(client, 'photos')
    assert len(calls) == 2
    for index in range(20):
        smart(client, 'photos', q=str(index))
    assert len(app.state.fs.smart_cache) == 12


@pytest.mark.parametrize('params', [{'kind': 'unknown'}, {'kind': '../photos'}, {'kind': 'photos', 'sort': 'unsafe'}, {'kind': 'recent', 'offset': -1}, {'kind': 'large', 'limit': 201}])
def test_smart_parameters_are_validated(client, params):
    assert client.get('/api/smart-files', params=params).status_code == 422


def test_smart_files_require_login_and_keep_favorites_per_user(tmp_path):
    settings = Settings(auth_enabled=True, create_default_folders=False, storage_path=tmp_path / 'storage', database_path=tmp_path / 'db/app.db', internal_path=tmp_path / 'internal', _env_file=None)
    application = create_app(settings)
    (settings.storage_path / 'photo.jpg').write_bytes(b'photo')
    with application.state.db() as db:
        db.add_all([User(username=name, password_hash=hasher.hash('passphrase123'), role='user') for name in ['alice', 'bob']])
        db.commit()
    with TestClient(application) as client:
        assert client.get('/api/smart-files', params={'kind': 'photos'}).status_code == 401
        client.post('/api/auth/login', json={'username': 'alice', 'password': 'passphrase123'})
        csrf = client.get('/api/auth/me').json()['csrf_token']
        client.post('/api/favorites', json={'paths': ['photo.jpg'], 'favorite': True}, headers={'X-CSRF-Token': csrf})
        assert smart(client, 'photos')['items'][0]['favorite'] is True
        client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        client.post('/api/auth/login', json={'username': 'bob', 'password': 'passphrase123'})
        assert smart(client, 'photos')['items'][0]['favorite'] is False
