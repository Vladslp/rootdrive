import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import User
from app.main import create_app
from app.services.security import hasher


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(create_default_folders=False, storage_path=tmp_path / 'storage', database_path=tmp_path / 'data/app.db', internal_path=tmp_path / 'internal', _env_file=None))


@pytest.fixture
def client(app):
    with TestClient(app) as connection:
        yield connection


@pytest.mark.parametrize('extension', ['txt', 'md', 'json', 'csv', 'py', 'js', 'html', 'css'])
def test_create_text_file_and_open_editor(client, app, extension):
    assert client.post('/api/folders', json={'name': 'Notes'}).status_code == 201
    response = client.post('/api/files', json={'path': 'Notes', 'name': 'Untitled.' + extension})
    assert response.status_code == 201, response.text
    path = response.json()['path']
    assert path == 'Notes/Untitled.' + extension
    raw = client.get('/api/files/download', params={'path': path}).content
    assert raw == (b'{}\n' if extension == 'json' else b'')
    editor = client.get('/api/editor', params={'path': path})
    assert editor.status_code == 200
    assert editor.json()['kind'] == 'text'
    assert editor.json()['text'] == raw.decode()
    assert client.get('/api/storage/stats').json()['file_count'] == 1
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


@pytest.mark.parametrize('extension', ['docx', 'odt'])
def test_create_valid_office_document_and_save_copy(client, extension):
    response = client.post('/api/files', json={'name': 'Document.' + extension})
    assert response.status_code == 201
    path = response.json()['path']
    raw = client.get('/api/files/download', params={'path': path}).content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if extension == 'docx':
            assert {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'} <= set(archive.namelist())
        else:
            assert archive.infolist()[0].filename == 'mimetype'
            assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
            assert archive.read('mimetype') == b'application/vnd.oasis.opendocument.text'
            assert 'META-INF/manifest.xml' in archive.namelist()
    data = client.get('/api/editor', params={'path': path}).json()
    assert data['kind'] == 'document'
    assert data['paragraphs'] == [{'id': 0, 'text': '', 'editable': True, 'heading': False}]
    saved = client.post('/api/editor', json={'path': path, 'kind': 'document', 'revision': data['revision'], 'paragraphs': [{'id': 0, 'text': 'First paragraph\nSecond line'}]})
    assert saved.status_code == 200, saved.text
    assert saved.json()['entry']['path'] == 'Document (edited).' + extension
    assert saved.json()['paragraphs'][0]['text'] == 'First paragraph\nSecond line'
    assert client.get('/api/files/download', params={'path': path}).content == raw


@pytest.mark.parametrize('name,path', [('../bad.txt', ''), ('/bad.txt', ''), ('bad.txt', '../'), ('bad.txt', '/etc'), ('bad.txt', 'a//b'), ('bad\x00.txt', '')])
def test_create_file_rejects_unsafe_paths(client, name, path):
    assert client.post('/api/files', json={'path': path, 'name': name}).status_code == 400
    assert client.get('/api/files').json()['total'] == 0


def test_create_file_conflicts_and_symlink_escape(client, app, tmp_path):
    assert client.post('/api/files', json={'name': 'keep.txt'}).status_code == 201
    source = app.state.settings.storage_path / 'keep.txt'
    source.write_text('keep contents')
    assert client.post('/api/files', json={'name': 'keep.txt'}).status_code == 409
    assert source.read_text() == 'keep contents'
    assert client.post('/api/folders', json={'name': 'folder.txt'}).status_code == 201
    assert client.post('/api/files', json={'name': 'folder.txt'}).status_code == 409
    (app.state.settings.storage_path / 'escape').symlink_to(tmp_path, target_is_directory=True)
    assert client.post('/api/files', json={'path': 'escape', 'name': 'bad.txt'}).status_code == 400
    assert client.post('/api/files', json={'name': 'photo.jpg'}).status_code == 415
    assert client.post('/api/files', json={'name': 'app.exe'}).status_code == 415
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_create_file_rollback_on_database_failure(client, app, monkeypatch):
    from sqlalchemy.orm import Session
    def fail_commit(self):
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(Session, 'commit', fail_commit)
    with pytest.raises(RuntimeError):
        client.post('/api/files', json={'name': 'rollback.txt'})
    assert not (app.state.settings.storage_path / 'rollback.txt').exists()
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_create_file_requires_login_and_csrf(tmp_path):
    app = create_app(Settings(create_default_folders=False, auth_enabled=True, storage_path=tmp_path / 'storage', database_path=tmp_path / 'data/app.db', internal_path=tmp_path / 'internal', _env_file=None))
    with app.state.db() as db:
        db.add(User(username='writer', password_hash=hasher.hash('valid-test-password'), role='user'))
        db.commit()
    with TestClient(app) as client:
        assert client.post('/api/files', json={'name': 'new.txt'}).status_code == 401
        login = client.post('/api/auth/login', json={'username': 'writer', 'password': 'valid-test-password'})
        assert login.status_code == 200
        assert client.post('/api/files', json={'name': 'new.txt'}).status_code == 403
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        assert client.post('/api/files', json={'name': 'new.txt'}).status_code == 201
