import errno
import io
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.database import User
from app.services import archives
from app.services.security import hasher
from test_rootdrive import app, client, put

DEFAULT_FOLDERS = {'Documents', 'Photos', 'Videos', 'Audio'}


def settings_for(tmp_path, **values):
    return Settings(storage_path=tmp_path / 'storage', database_path=tmp_path / 'data/app.db', internal_path=tmp_path / 'internal', _env_file=None, **values)


def test_default_folders_are_created_once_and_stay_removed_after_restart(tmp_path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        listing = client.get('/api/files').json()['items']
        assert {item['name'] for item in listing} == DEFAULT_FOLDERS
        assert all(item['size'] == 0 and item['child_count'] == 0 for item in listing)
        assert client.request('DELETE', '/api/files', json={'path': 'Photos'}).status_code == 200
        assert client.patch('/api/files/rename', json={'path': 'Audio', 'name': 'Music'}).status_code == 200
    with TestClient(create_app(settings)) as client:
        assert {item['name'] for item in client.get('/api/files').json()['items']} == {'Documents', 'Music', 'Videos'}


def test_existing_names_and_symlinks_are_preserved(tmp_path):
    settings = settings_for(tmp_path)
    settings.prepare()
    (settings.storage_path / 'Documents').write_text('Existing file')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (settings.storage_path / 'Photos').symlink_to(outside, target_is_directory=True)
    (settings.storage_path / 'Videos').mkdir()
    (settings.storage_path / 'Videos' / 'keep.txt').write_text('Keep me')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/files', params={'path': 'Photos'}).status_code == 400
    assert (settings.storage_path / 'Documents').read_text() == 'Existing file'
    assert (settings.storage_path / 'Videos/keep.txt').read_text() == 'Keep me'
    assert list(outside.iterdir()) == []
    assert (settings.storage_path / 'Audio').is_dir()


def test_default_folders_can_be_disabled_and_initialized_for_a_new_storage_path(tmp_path):
    settings = settings_for(tmp_path, create_default_folders=False)
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/files').json()['total'] == 0
    settings.create_default_folders = True
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/files').json()['total'] == 4
    settings.storage_path = tmp_path / 'other-storage'
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/files').json()['total'] == 4


def test_zip_is_saved_beside_the_folder_with_nested_and_empty_directories(client, app, tmp_path):
    client.post('/api/folders', json={'name': 'Parent'})
    client.post('/api/folders', json={'path': 'Parent', 'name': 'Album'})
    client.post('/api/folders', json={'path': 'Parent/Album', 'name': 'Empty'})
    put(client, 'hello.txt', b'hello' * 10000, 'Parent/Album')
    put(client, 'data.bin', bytes(range(256)) * 4096, 'Parent/Album')
    put(client, '.DS_Store', b'hidden', 'Parent/Album')
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret')
    (app.state.fs.root / 'Parent/Album/link').symlink_to(outside)
    result = client.post('/api/files/compress', json={'path': 'Parent/Album'})
    assert result.status_code == 201, result.text
    assert result.json()['path'] == 'Parent/Album.zip'
    assert result.json()['mime'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(client.get('/api/files/download', params={'path': result.json()['path']}).content)) as archive:
        assert set(archive.namelist()) == {'Album/', 'Album/Empty/', 'Album/hello.txt', 'Album/data.bin'}
        assert archive.read('Album/hello.txt') == b'hello' * 10000
        assert archive.read('Album/data.bin') == bytes(range(256)) * 4096
        assert archive.testzip() is None
    assert (app.state.fs.root / 'Parent/Album/hello.txt').read_bytes() == b'hello' * 10000
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []


def test_empty_folder_zip_and_name_conflicts(client):
    client.post('/api/folders', json={'name': 'Empty'})
    first = client.post('/api/files/compress', json={'path': 'Empty', 'name': 'My archive'})
    assert first.status_code == 201
    assert first.json()['name'] == 'My archive.zip'
    content = client.get('/api/files/download', params={'path': 'My archive.zip'}).content
    assert zipfile.ZipFile(io.BytesIO(content)).namelist() == ['Empty/']
    assert client.post('/api/files/compress', json={'path': 'Empty', 'name': 'My archive.zip'}).status_code == 409
    assert client.get('/api/files/download', params={'path': 'My archive.zip'}).content == content


@pytest.mark.parametrize('value', ['', '../outside', '/etc', 'a/../b', 'Folder\\bad'])
def test_zip_rejects_unsafe_source_paths(client, value):
    assert client.post('/api/files/compress', json={'path': value}).status_code == 400


@pytest.mark.parametrize('name', ['../evil.zip', '/evil.zip', 'bad\\evil.zip', 'x\ny.zip'])
def test_zip_rejects_unsafe_names(client, name):
    client.post('/api/folders', json={'name': 'Folder'})
    assert client.post('/api/files/compress', json={'path': 'Folder', 'name': name}).status_code == 400


def test_zip_rejects_regular_files_and_symlink_roots(client, app, tmp_path):
    put(client)
    (app.state.fs.root / 'Escape').symlink_to(tmp_path, target_is_directory=True)
    assert client.post('/api/files/compress', json={'path': 'hello.txt'}).status_code == 400
    assert client.post('/api/files/compress', json={'path': 'Escape'}).status_code == 400


def test_zip_failure_removes_staging_and_preserves_the_source(client, app, monkeypatch):
    client.post('/api/folders', json={'name': 'Folder'})
    put(client, path='Folder')
    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'Full')
    monkeypatch.setattr(archives.shutil, 'copyfileobj', fail)
    assert client.post('/api/files/compress', json={'path': 'Folder'}).status_code == 503
    assert not (app.state.fs.root / 'Folder.zip').exists()
    assert (app.state.fs.root / 'Folder/hello.txt').read_bytes() == b'hello'
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []


def test_zip_never_overwrites_a_destination_created_during_compression(client, app, monkeypatch):
    client.post('/api/folders', json={'name': 'Folder'})
    original = archives.write_zip
    def race(fs, sources, target, base=None):
        original(fs, sources, target, base)
        (fs.root / 'Folder.zip').write_bytes(b'Another file')
    monkeypatch.setattr(archives, 'write_zip', race)
    assert client.post('/api/files/compress', json={'path': 'Folder'}).status_code == 409
    assert (app.state.fs.root / 'Folder.zip').read_bytes() == b'Another file'
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []


def test_zip_requires_login_and_csrf(app):
    app.state.settings.auth_enabled = True
    (app.state.fs.root / 'Folder').mkdir()
    with app.state.db() as db:
        db.add(User(username='owner', password_hash=hasher.hash('password12345'), role='admin'))
        db.commit()
    with TestClient(app) as client:
        assert client.post('/api/files/compress', json={'path': 'Folder'}).status_code == 401
        result = client.post('/api/auth/login', json={'username': 'owner', 'password': 'password12345'})
        token = result.json()['csrf_token']
        assert client.post('/api/files/compress', json={'path': 'Folder'}).status_code == 403
        client.headers['X-CSRF-Token'] = token
        assert client.post('/api/files/compress', json={'path': 'Folder'}).status_code == 201


def test_zip_default_name_fits_unicode_filename_limits(client):
    name = "é" * 120
    assert client.post('/api/folders', json={'name': name}).status_code == 201
    result = client.post('/api/files/compress', json={'path': name})
    assert result.status_code == 201
    assert len(result.json()['name'].encode()) <= 240
    assert result.json()['name'].endswith('.zip')


def test_zip_reports_cross_filesystem_configuration_and_cleans_staging(client, app, monkeypatch):
    client.post('/api/folders', json={'name': 'Folder'})
    def cross_device(*args, **kwargs):
        raise OSError(errno.EXDEV, 'Cross-device link')
    monkeypatch.setattr(archives.os, 'link', cross_device)
    result = client.post('/api/files/compress', json={'path': 'Folder'})
    assert result.status_code == 503
    assert 'same filesystem' in result.json()['error']['message']
    assert not (app.state.fs.root / 'Folder.zip').exists()
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []
