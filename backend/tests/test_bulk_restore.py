import pytest
from sqlalchemy.orm import Session
from app.database import User
from app.services.security import hasher
from test_rootdrive import app, client, put


def discard(client, name):
    return client.request('DELETE', '/api/files', json={'path': name}).json()['id']


def restore(client, ids):
    return client.post('/api/trash/restore/batch', json={'ids': ids})


def test_bulk_restore_parent_before_selected_child_and_keep_contents(client, app):
    client.post('/api/folders', json={'name': 'Folder'})
    put(client, 'note.txt', b'hello', 'Folder')
    child = discard(client, 'Folder/note.txt')
    parent = discard(client, 'Folder')
    assert restore(client, [child, parent, child]).json() == {'count': 2}
    assert client.get('/api/files/download', params={'path': 'Folder/note.txt'}).content == b'hello'
    assert client.get('/api/trash').json()['total'] == 0


def test_bulk_restore_conflicts_roll_back_every_item(client, app):
    put(client, 'a.txt', b'a')
    put(client, 'b.txt', b'b')
    ids = [discard(client, name) for name in ['a.txt', 'b.txt']]
    put(client, 'b.txt', b'keep')
    assert restore(client, ids).status_code == 409
    assert not (app.state.fs.root / 'a.txt').exists()
    assert (app.state.fs.root / 'b.txt').read_bytes() == b'keep'
    assert client.get('/api/trash').json()['total'] == 2
    assert restore(client, [ids[0], 'missing']).status_code == 409
    assert not (app.state.fs.root / 'a.txt').exists()


def test_bulk_restore_database_failure_rolls_back_files_and_metadata(client, app, monkeypatch):
    put(client, 'a.txt')
    client.post('/api/favorites', json={'paths': ['a.txt'], 'favorite': True})
    identifier = discard(client, 'a.txt')
    def fail(self):
        raise RuntimeError('Database failed')
    monkeypatch.setattr(Session, 'commit', fail)
    with pytest.raises(RuntimeError):
        restore(client, [identifier])
    assert not (app.state.fs.root / 'a.txt').exists()
    assert client.get('/api/trash').json()['total'] == 1
    assert client.get('/api/collection', params={'favorite': True}).json()['total'] == 0


def test_bulk_restore_rejects_symlink_destinations_and_requires_csrf(client, app, tmp_path):
    client.post('/api/folders', json={'name': 'Folder'})
    put(client, 'a.txt', path='Folder')
    identifier = discard(client, 'Folder/a.txt')
    (app.state.fs.root / 'Folder').rmdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (app.state.fs.root / 'Folder').symlink_to(outside, target_is_directory=True)
    assert restore(client, [identifier]).status_code == 400
    assert not list(outside.iterdir())
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add(User(username='user', password_hash=hasher.hash('test-passphrase'), role='user'))
        db.commit()
    assert restore(client, [identifier]).status_code == 401
    login = client.post('/api/auth/login', json={'username': 'user', 'password': 'test-passphrase'})
    assert login.status_code == 200
    assert restore(client, [identifier]).status_code == 403
