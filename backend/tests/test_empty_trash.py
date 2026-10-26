import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import FileVersion, ItemMetadata, TrashItem, User
from app.services.security import hasher
from test_rootdrive import app, client, put


def clear(client, revision=None):
    if revision is None:
        revision = client.get('/api/trash').json()['revision']
    return client.request('DELETE', '/api/trash/all', json={'revision': revision})


def test_remove_all_clears_all_pages_and_preserves_live_files(client, app):
    put(client, 'keep.txt')
    for index in range(65):
        (app.state.fs.root / f'{index}.txt').write_text('deleted')
    assert client.post('/api/files/batch/trash', json={'paths': [f'{index}.txt' for index in range(65)]}).status_code == 200
    listing = client.get('/api/trash', params={'limit': 10}).json()
    assert listing['total'] == 65 and len(listing['items']) == 10
    response = clear(client, listing['revision'])
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 65
    assert client.get('/api/trash').json()['total'] == 0
    assert clear(client).json()['count'] == 0
    assert (app.state.fs.root / 'keep.txt').read_bytes() == b'hello'
    assert not list((app.state.settings.internal_path / 'trash').iterdir())
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_remove_all_rejects_a_changed_confirmation(client):
    put(client, 'one.txt')
    client.request('DELETE', '/api/files', json={'path': 'one.txt'})
    revision = client.get('/api/trash').json()['revision']
    put(client, 'two.txt')
    client.request('DELETE', '/api/files', json={'path': 'two.txt'})
    assert clear(client, revision).status_code == 409
    assert client.get('/api/trash').json()['total'] == 2
    assert client.request('DELETE', '/api/trash/all', json={}).status_code == 422


def test_remove_all_requires_authentication_and_csrf(client, app):
    revision = client.get('/api/trash').json()['revision']
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add(User(username='editor', password_hash=hasher.hash('test-password-123'), role='user'))
        db.commit()
    assert clear(client, revision).status_code == 401
    login = client.post('/api/auth/login', json={'username': 'editor', 'password': 'test-password-123'})
    assert login.status_code == 200
    assert clear(client, revision).status_code == 403
    client.headers['X-CSRF-Token'] = login.json()['csrf_token']
    assert clear(client, revision).status_code == 200


@pytest.mark.parametrize('failure', ['database', 'rename'])
def test_remove_all_rolls_back_files_metadata_and_versions(client, app, monkeypatch, failure):
    put(client, 'note.txt')
    data = client.get('/api/editor', params={'path': 'note.txt'}).json()
    assert client.post('/api/editor', json={'path': 'note.txt', 'revision': data['revision'], 'kind': 'text', 'mode': 'original', 'text': 'new'}).status_code == 200
    client.request('DELETE', '/api/files', json={'path': 'note.txt'})
    revision = client.get('/api/trash').json()['revision']
    files = {path.relative_to(app.state.settings.internal_path): path.read_bytes() for location in ['trash', 'versions'] for path in (app.state.settings.internal_path / location).iterdir()}
    if failure == 'database':
        def fail(self):
            raise RuntimeError('simulated database failure')
        monkeypatch.setattr(Session, 'commit', fail)
        with pytest.raises(RuntimeError):
            clear(client, revision)
    else:
        from app.services import trash
        original = trash.os.rename
        calls = 0
        def fail(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated rename failure')
            return original(source, destination)
        monkeypatch.setattr(trash.os, 'rename', fail)
        assert clear(client, revision).status_code == 503
    assert client.get('/api/trash').json()['total'] == 1
    assert all((app.state.settings.internal_path / path).read_bytes() == content for path, content in files.items())
    with app.state.db() as db:
        assert db.scalar(select(func.count()).select_from(FileVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ItemMetadata)) == 1
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_remove_all_purges_nested_versions_and_metadata(client, app):
    client.post('/api/folders', json={'name': 'Trip'})
    (app.state.fs.root / 'Trip' / 'note.txt').write_text('original')
    data = client.get('/api/editor', params={'path': 'Trip/note.txt'}).json()
    client.post('/api/editor', json={'path': 'Trip/note.txt', 'revision': data['revision'], 'kind': 'text', 'mode': 'original', 'text': 'edited'})
    client.post('/api/favorites', json={'paths': ['Trip/note.txt'], 'favorite': True})
    client.request('DELETE', '/api/files', json={'path': 'Trip'})
    assert clear(client).status_code == 200
    with app.state.db() as db:
        for model in [FileVersion, ItemMetadata, TrashItem]:
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert not list((app.state.settings.internal_path / 'versions').iterdir())


def test_remove_selected_uses_distinct_trash_ids_for_duplicate_paths(client, app):
    ids = []
    for content in [b'first', b'second', b'third']:
        put(client, 'same.txt', content)
        ids.append(client.request('DELETE', '/api/files', json={'path': 'same.txt'}).json()['id'])
    response = client.request('DELETE', '/api/trash/batch', json={'ids': ids[:2]})
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 2
    remaining = client.get('/api/trash').json()
    assert remaining['total'] == 1 and remaining['items'][0]['id'] == ids[2]
    assert client.post('/api/trash/restore', json={'id': ids[2]}).status_code == 200
    assert (app.state.fs.root / 'same.txt').read_bytes() == b'third'


def test_remove_selected_is_atomic_if_an_item_was_restored(client):
    ids = []
    for name in ['one.txt', 'two.txt']:
        put(client, name)
        ids.append(client.request('DELETE', '/api/files', json={'path': name}).json()['id'])
    assert client.post('/api/trash/restore', json={'id': ids[0]}).status_code == 200
    assert client.request('DELETE', '/api/trash/batch', json={'ids': ids}).status_code == 409
    assert client.get('/api/trash').json()['total'] == 1
    assert client.request('DELETE', '/api/trash/batch', json={'ids': []}).status_code == 422
