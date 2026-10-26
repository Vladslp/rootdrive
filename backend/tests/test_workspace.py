import io
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.database import UploadJob, User
from app.main import create_app
from app.services.security import hasher
from test_rootdrive import app, client, put


def start(client, path='photo.txt', content=b'new', **values):
    return client.post('/api/uploads', json={'relative_path': path, 'size': len(content), **values})


def upload(client, path='photo.txt', content=b'new', **values):
    response = start(client, path, content, **values)
    assert response.status_code == 201, response.text
    identifier = response.json()['id']
    if content:
        assert client.put('/api/uploads/' + identifier, params={'offset': 0}, content=content).status_code == 200
    result = client.post('/api/uploads/' + identifier + '/complete')
    assert result.status_code == 200, result.text
    return identifier


def test_folder_upload_and_resume_across_restart(client, app):
    job = start(client, 'Trip/Day 1/photo.txt', b'abcdef', last_modified=1234).json()
    identifier = job['id']
    url = '/api/uploads/' + identifier
    assert client.put(url, params={'offset': 0}, content=b'abc').json()['received'] == 3
    assert client.post(url + '/complete').status_code == 409
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as second:
        assert second.get('/api/uploads').json()['items'][0]['received'] == 3
        assert second.post(url + '/verify', content=b'bad').status_code == 409
        assert second.post(url + '/verify', content=b'abc').status_code == 200
        assert second.put(url, params={'offset': 0}, content=b'def').status_code == 409
        assert second.put(url, params={'offset': 3}, content=b'def').json()['received'] == 6
        assert second.post(url + '/complete').status_code == 200
        assert second.post(url + '/complete').status_code == 200
        assert second.get('/api/files/download', params={'path': 'Trip/Day 1/photo.txt'}).content == b'abcdef'
        assert second.get('/api/uploads').json()['items'] == []


def test_resume_discards_uncommitted_chunk(client, app):
    job = start(client, content=b'abcd').json()
    stage = app.state.settings.internal_path / 'uploads' / job['id']
    stage.write_bytes(b'uncommitted')
    response = client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'abcd')
    assert response.status_code == 200
    assert stage.read_bytes() == b'abcd'


def test_cancel_and_empty_upload(client, app):
    upload(client, 'empty.txt', b'')
    assert client.get('/api/files/download', params={'path': 'empty.txt'}).content == b''
    job = start(client).json()
    assert client.delete('/api/uploads/' + job['id']).status_code == 200
    assert not (app.state.settings.internal_path / 'uploads' / job['id']).exists()
    assert client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'new').status_code == 409


@pytest.mark.parametrize('path', ['../escape.txt', '/tmp/escape.txt', 'a//b.txt', 'a/../b.txt', 'a\\b.txt', 'a/:trash:x.txt'])
def test_nested_upload_path_validation(client, path):
    assert start(client, path).status_code == 400


def test_nested_upload_symlink_and_file_parent(client, app, tmp_path):
    (app.state.fs.root / 'escape').symlink_to(tmp_path)
    assert start(client, 'escape/out.txt').status_code == 400
    put(client, 'parent')
    assert start(client, 'parent/file.txt').status_code == 409


def test_resumable_upload_limits(client, app):
    app.state.settings.max_upload_size_mb = 1
    assert start(client, size=1024 * 1024 + 1).status_code == 413
    job = start(client, content=b'abc').json()
    url = '/api/uploads/' + job['id']
    assert client.put(url, params={'offset': 0}, content=b'abcd').status_code == 413
    assert client.put(url, params={'offset': 0}, content=b'x' * (4 * 1024 * 1024 + 1)).status_code == 413
    assert client.get(url).json()['received'] == 0


def test_conflicts_never_overwrite_silently(client):
    put(client, 'photo.txt', b'old')
    assert start(client).status_code == 409
    pending = start(client, 'other.txt', b'changed').json()
    put(client, 'other.txt', b'keep')
    client.put('/api/uploads/' + pending['id'], params={'offset': 0}, content=b'changed')
    assert client.post('/api/uploads/' + pending['id'] + '/complete').status_code == 409
    assert client.get('/api/files/download', params={'path': 'other.txt'}).content == b'keep'


def test_version_history_restore_and_rename(client):
    upload(client, content=b'first')
    upload(client, content=b'second', overwrite=True)
    versions = client.get('/api/files/versions', params={'path': 'photo.txt'}).json()['items']
    assert len(versions) == 1
    identifier = versions[0]['id']
    assert client.get('/api/versions/' + identifier + '/download').content == b'first'
    client.patch('/api/files/rename', json={'path': 'photo.txt', 'name': 'renamed.txt'})
    assert client.post('/api/versions/' + identifier + '/restore').status_code == 200
    assert client.get('/api/files/download', params={'path': 'renamed.txt'}).content == b'first'
    versions = client.get('/api/files/versions', params={'path': 'renamed.txt'}).json()['items']
    assert len(versions) == 2
    assert client.get('/api/versions/' + versions[0]['id'] + '/download').content == b'second'
    assert client.get('/api/files').json()['items'][0]['version_count'] == 2


def test_replace_rejects_changed_original(client, app):
    put(client, 'photo.txt', b'first')
    job = start(client, content=b'new', overwrite=True).json()
    (app.state.fs.root / 'photo.txt').write_bytes(b'changed externally')
    client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'new')
    assert client.post('/api/uploads/' + job['id'] + '/complete').status_code == 409
    assert (app.state.fs.root / 'photo.txt').read_bytes() == b'changed externally'


def test_metadata_follows_move_trash_and_restore(client, app):
    upload(client, 'Folder/a.txt', b'first')
    upload(client, 'Folder/a.txt', b'second', overwrite=True)
    tag = client.post('/api/tags', json={'name': 'Travel', 'color': 'green'}).json()
    assert client.post('/api/files/tags', json={'paths': ['Folder/a.txt'], 'tag_ids': [tag['id']]}).status_code == 200
    client.post('/api/favorites', json={'paths': ['Folder/a.txt']})
    client.patch('/api/files/rename', json={'path': 'Folder', 'name': 'Trip'})
    item = client.get('/api/collection', params={'favorite': True}).json()['items'][0]
    assert item['path'] == 'Trip/a.txt' and item['favorite'] and item['version_count'] == 1
    assert item['tags'][0]['name'] == 'Travel'
    trash = client.request('DELETE', '/api/files', json={'path': 'Trip'}).json()
    assert client.get('/api/collection', params={'favorite': True}).json()['total'] == 0
    assert client.post('/api/trash/restore', json=trash).status_code == 200
    assert client.get('/api/collection', params={'tag': tag['id']}).json()['items'][0]['path'] == 'Trip/a.txt'
    trash = client.request('DELETE', '/api/files', json={'path': 'Trip'}).json()
    assert client.request('DELETE', '/api/trash', json=trash).status_code == 200
    assert list((app.state.settings.internal_path / 'versions').iterdir()) == []


def test_bulk_move_prevalidation_and_overlap(client):
    upload(client, 'A/a.txt', b'a')
    upload(client, 'B/a.txt', b'b')
    client.post('/api/folders', json={'name': 'Target'})
    assert client.post('/api/files/batch/move', json={'paths': ['A/a.txt', 'B/a.txt'], 'destination': 'Target'}).status_code == 409
    assert client.get('/api/files/download', params={'path': 'A/a.txt'}).content == b'a'
    result = client.post('/api/files/batch/move', json={'paths': ['A', 'A/a.txt'], 'destination': 'Target'})
    assert result.json()['count'] == 1
    assert client.post('/api/files/batch/move', json={'paths': ['Target'], 'destination': 'Target/A'}).status_code == 400
    assert client.post('/api/files/batch/trash', json={'paths': ['Target', 'Target/A/a.txt', 'B']}).json()['count'] == 2
    assert client.get('/api/trash').json()['total'] == 2


def test_tags_colors_and_filtering(client):
    put(client)
    client.post('/api/folders', json={'name': 'Photos'})
    tag = client.post('/api/tags', json={'name': 'Travel', 'color': 'green'}).json()
    assert client.post('/api/tags', json={'name': 'travel'}).status_code == 409
    second = client.post('/api/tags', json={'name': '100%'}).json()
    assert second['id']
    assert client.post('/api/files/tags', json={'paths': ['Photos'], 'tag_ids': [tag['id']], 'color': 'mint'}).status_code == 200
    assert client.get('/api/files').json()['items'][0]['color'] == 'mint'
    assert client.post('/api/files/tags', json={'paths': ['hello.txt'], 'tag_ids': [tag['id']]}).status_code == 200
    assert client.get('/api/collection', params={'tag': tag['id'], 'q': 'HELLO'}).json()['total'] == 1
    assert client.patch('/api/tags/' + tag['id'], json={'name': 'Holiday', 'color': 'rose'}).status_code == 200
    assert client.get('/api/files').json()['items'][1]['tags'][0]['name'] == 'Holiday'
    assert client.delete('/api/tags/' + tag['id']).status_code == 200
    assert client.get('/api/files').json()['items'][1]['tags'] == []


def test_zip_selected_folders_empty_dirs_and_symlinks(client, app, tmp_path):
    upload(client, 'Photos/a.txt', b'a')
    client.post('/api/folders', json={'path': 'Photos', 'name': 'Empty'})
    secret = tmp_path / 'outside.txt'
    secret.write_bytes(b'secret')
    (app.state.fs.root / 'Photos' / 'secret').symlink_to(secret)
    response = client.post('/api/files/archive', json={'paths': ['Photos', 'Photos/a.txt']})
    assert response.status_code == 201, response.text
    download = client.get(response.json()['url'])
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert set(archive.namelist()) == {'Photos/', 'Photos/Empty/', 'Photos/a.txt'}
        assert archive.read('Photos/a.txt') == b'a'
    assert client.post('/api/files/archive', json={'paths': ['../outside.txt']}).status_code == 400
    assert client.post('/api/files/archive', json={'paths': ['Photos/secret']}).status_code == 400


def test_media_ranges_and_protection(client):
    put(client, 'song.mp3', b'0123456789')
    response = client.get('/api/files/media', params={'path': 'song.mp3'}, headers={'Range': 'bytes=2-5'})
    assert response.status_code == 206 and response.content == b'2345'
    assert response.headers['content-range'] == 'bytes 2-5/10'
    assert client.get('/api/files/media', params={'path': 'song.mp3'}, headers={'Range': 'bytes=-3'}).content == b'789'
    assert client.head('/api/files/media', params={'path': 'song.mp3'}).headers['content-length'] == '10'
    assert client.get('/api/files/media', params={'path': 'song.mp3'}, headers={'Range': 'bytes=99-'}).status_code == 416
    assert client.get('/api/files/media', params={'path': '../song.mp3'}).status_code == 400
    put(client, 'script.html', b'<script>')
    assert client.get('/api/files/media', params={'path': 'script.html'}).status_code == 415


def test_storage_separates_system_trash_versions(client):
    upload(client, content=b'first')
    upload(client, content=b'second', overwrite=True)
    before = client.get('/api/storage/stats').json()
    assert before['stored_bytes'] == 6 and before['versions_bytes'] == 5
    assert before['system_bytes'] == max(0, before['disk_used'] - 11)
    trash = client.request('DELETE', '/api/files', json={'path': 'photo.txt'}).json()
    after = client.get('/api/storage/stats').json()
    assert after['stored_bytes'] == 0 and after['trash_bytes'] == 6 and after['versions_bytes'] == 5
    client.request('DELETE', '/api/trash', json=trash)
    final = client.get('/api/storage/stats').json()
    assert final['trash_bytes'] == 0 and final['versions_bytes'] == 0


def test_new_endpoints_auth_csrf_and_owner_isolation(app):
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add_all([User(username='one', password_hash=hasher.hash('long-password')), User(username='two', password_hash=hasher.hash('long-password'))])
        db.commit()
    with TestClient(app) as first, TestClient(app) as second:
        for route in ['/api/uploads', '/api/tags', '/api/collection', '/api/files/versions?path=x', '/api/files/media?path=x']:
            assert first.get(route).status_code == 401
        login = first.post('/api/auth/login', json={'username': 'one', 'password': 'long-password'}).json()
        assert start(first).status_code == 403
        first.headers['X-CSRF-Token'] = login['csrf_token']
        upload(first)
        first.post('/api/favorites', json={'paths': ['photo.txt']})
        job = start(first, 'other.txt').json()
        archive = first.post('/api/files/archive', json={'paths': ['photo.txt']}).json()
        login = second.post('/api/auth/login', json={'username': 'two', 'password': 'long-password'}).json()
        second.headers['X-CSRF-Token'] = login['csrf_token']
        assert second.get('/api/uploads/' + job['id']).status_code == 404
        assert second.delete('/api/uploads/' + job['id']).status_code == 404
        assert second.get(archive['url']).status_code == 404
        assert second.get('/api/collection', params={'favorite': True}).json()['total'] == 0
        assert first.get('/api/collection', params={'favorite': True}).json()['total'] == 1


def test_replacement_upload_preserves_original_source_name(client):
    upload(client, content=b'first')
    job = start(client, content=b'second', overwrite=True, source_name='Replacement.txt').json()
    assert job['source_name'] == 'Replacement.txt'
    assert client.get('/api/uploads').json()['items'][0]['source_name'] == 'Replacement.txt'


def test_upload_completion_revalidates_destination_symlinks(client, app, tmp_path):
    job = start(client, 'Nested/file.txt', b'data').json()
    client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'data')
    (app.state.fs.root / 'Nested').symlink_to(tmp_path)
    assert client.post('/api/uploads/' + job['id'] + '/complete').status_code == 400
    assert not (tmp_path / 'file.txt').exists()


def test_version_commit_failure_keeps_original(client, app, monkeypatch):
    from sqlalchemy.orm import Session
    put(client, 'photo.txt', b'old')
    job = start(client, content=b'new', overwrite=True).json()
    client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'new')
    def fail_commit(self):
        raise OSError('simulated database failure')
    with monkeypatch.context() as context:
        context.setattr(Session, 'commit', fail_commit)
        assert client.post('/api/uploads/' + job['id'] + '/complete').status_code == 503
    assert client.get('/api/files/download', params={'path': 'photo.txt'}).content == b'old'
    assert client.get('/api/uploads/' + job['id']).json()['status'] == 'open'
    assert client.post('/api/uploads/' + job['id'] + '/complete').status_code == 200


def test_bulk_move_commit_failure_rolls_back(client, app, monkeypatch):
    from sqlalchemy.orm import Session
    put(client, 'one.txt', b'one')
    put(client, 'two.txt', b'two')
    client.post('/api/folders', json={'name': 'Target'})
    client.post('/api/favorites', json={'paths': ['one.txt']})
    def fail_commit(self):
        raise OSError('simulated database failure')
    with monkeypatch.context() as context:
        context.setattr(Session, 'commit', fail_commit)
        assert client.post('/api/files/batch/move', json={'paths': ['one.txt', 'two.txt'], 'destination': 'Target'}).status_code == 503
    assert client.get('/api/collection', params={'favorite': True}).json()['items'][0]['path'] == 'one.txt'
    assert client.get('/api/files/download', params={'path': 'two.txt'}).content == b'two'
