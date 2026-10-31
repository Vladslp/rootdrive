import io
from urllib.parse import urlsplit, parse_qs
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.database import User
from app.main import create_app
from app.services.security import hasher
from test_rootdrive import app, client, put


@pytest.fixture
def accounts(app):
    with app.state.db() as db:
        db.add_all([User(username=name, password_hash=hasher.hash('test-password'), role='admin' if name == 'alice' else 'user') for name in ['alice', 'bob', 'eve']])
        db.commit()
    app.state.settings.auth_enabled = True
    app.state.settings.enable_public_shares = True
    connections = []
    for name in ['alice', 'bob', 'eve']:
        connection = TestClient(app)
        login = connection.post('/api/auth/login', json={'username': name, 'password': 'test-password'})
        assert login.status_code == 200
        connection.headers['X-CSRF-Token'] = login.json()['csrf_token']
        connection.personal = connection.get('/api/spaces').json()['personal']
        connections.append(connection)
    yield connections
    for connection in connections:
        connection.close()


def select(connection, identifier):
    result = connection.post('/api/spaces/select', json={'id': identifier})
    assert result.status_code == 200, result.text
    return result


def test_personal_files_metadata_trash_and_previews_are_isolated(app, accounts):
    alice, bob, eve = accounts
    select(alice, alice.personal)
    select(bob, bob.personal)
    put(alice, 'same.txt', b'alice private')
    put(bob, 'same.txt', b'bob private')
    assert alice.get('/api/files/download?path=same.txt').content == b'alice private'
    assert bob.get('/api/files/download?path=same.txt').content == b'bob private'
    alice.post('/api/folders', json={'name': 'Secrets'})
    alice.post('/api/library/pins', json={'path': 'Secrets'})
    assert bob.get('/api/library/pins').json()['items'] == []
    assert eve.get('/api/files').json()['total'] == 0
    for connection, color in [(alice, 'red'), (bob, 'blue')]:
        data = io.BytesIO()
        Image.new('RGB', (30, 20), color).save(data, format='PNG')
        put(connection, 'photo.png', data.getvalue())
    first = alice.get('/api/files/thumbnail?path=photo.png')
    second = bob.get('/api/files/thumbnail?path=photo.png')
    assert first.status_code == second.status_code == 200
    assert first.content != second.content
    trash = alice.request('DELETE', '/api/files', json={'path': 'same.txt'}).json()
    assert bob.get('/api/trash').json()['total'] == 0
    assert bob.post('/api/trash/restore', json=trash).status_code == 404
    assert alice.post('/api/trash/restore', json=trash).status_code == 200
    assert alice.get('/api/auth/me').json()['space']['id'] == alice.personal
    assert app.state.fs.listing('', '', False, 'name', 'asc', 0, 60)['total'] == 0
    assert alice.get('/api/storage/stats').json()['file_count'] == 2


def test_membership_reader_permissions_and_revocation(app, accounts):
    alice, bob, eve = accounts
    shared = alice.post('/api/spaces', json={'name': 'Team'}).json()['id']
    select(alice, shared)
    put(alice, 'note.txt', b'team')
    assert alice.post('/api/spaces/' + shared + '/members', json={'username': 'bob', 'role': 'reader'}).status_code == 200
    select(bob, shared)
    assert bob.get('/api/files/download?path=note.txt').content == b'team'
    assert put(bob).status_code == 403
    mutations = [('/api/folders', 'POST', {'name': 'No'}), ('/api/files/copy', 'POST', {'paths': ['note.txt'], 'destination': ''}), ('/api/files', 'DELETE', {'path': 'note.txt'}), ('/api/shares', 'POST', {'path': 'note.txt'}), ('/api/archives/extract', 'POST', {'path': 'note.zip'}), ('/api/albums', 'POST', {'name': 'No'}), ('/api/library/pins', 'POST', {'path': 'No'}), ('/api/studio/export', 'POST', {'paths': ['note.txt']})]
    for url, method, body in mutations:
        assert bob.request(method, url, json=body).status_code == 403, url
    assert bob.post('/api/discovery/duplicates').status_code == 200
    archive = bob.post('/api/files/archive', json={'paths': ['note.txt']})
    assert archive.status_code == 201
    assert bob.get(archive.json()['url']).status_code == 200
    assert eve.get(archive.json()['url']).status_code == 404
    assert eve.post('/api/spaces/select', json={'id': shared}).status_code == 403
    assert bob.post('/api/spaces/' + shared + '/members', json={'username': 'eve', 'role': 'editor'}).status_code == 403
    alice.post('/api/spaces/' + shared + '/members', json={'username': 'bob', 'role': 'editor'})
    assert put(bob, 'edit.txt', b'allowed').status_code == 201
    member = next(item for item in alice.get('/api/spaces/' + shared + '/members').json()['items'] if item['username'] == 'bob')
    alice.delete('/api/spaces/' + shared + '/members/' + str(member['id']))
    assert bob.get('/api/files').status_code == 403
    assert bob.get('/api/files/preview?path=note.txt').status_code == 403
    select(bob, 'shared')
    assert bob.get('/api/files').json()['total'] == 0


def test_stale_tab_bindings_upload_guard_and_admin_privacy(app, accounts):
    alice, bob, eve = accounts
    select(alice, alice.personal)
    assert alice.post('/api/folders', json={'name': 'Wrong'}, headers={'X-RootDrive-Space': 'shared'}).status_code == 409
    assert alice.get('/api/files/download', params={'path': 'same.txt', 'workspace': 'shared'}).status_code == 409
    job = alice.post('/api/uploads', json={'path': '', 'relative_path': 'pending.txt', 'size': 12}).json()
    assert alice.post('/api/spaces/select', json={'id': 'shared'}).status_code == 409
    assert bob.get('/api/uploads/' + job['id']).status_code == 404
    alice.delete('/api/uploads/' + job['id'])
    select(alice, 'shared')
    assert alice.post('/api/spaces/select', json={'id': bob.personal}).status_code == 403
    assert alice.get('/api/spaces/' + bob.personal + '/members').status_code == 403
    assert alice.post('/api/spaces/select', json={'id': alice.personal}, headers={'X-CSRF-Token': 'invalid'}).status_code == 403


def test_public_links_use_their_own_namespace_not_browser_cookie(app, accounts):
    alice, bob, eve = accounts
    select(alice, alice.personal)
    select(bob, bob.personal)
    put(alice, 'file.txt', b'alice public copy')
    put(bob, 'file.txt', b'bob private')
    link = alice.post('/api/shares', json={'path': 'file.txt'}).json()
    assert '?space=' + alice.personal in link['url']
    assert bob.get(link['url']).content == b'alice public copy'
    assert bob.get(urlsplit(link['url']).path).status_code == 404
    with TestClient(app) as public:
        assert public.get(link['url']).content == b'alice public copy'
        secure = alice.post('/api/shares', json={'path': 'file.txt', 'password': 'password123'}).json()
        parts = urlsplit(secure['url'])
        base = '/api/public/' + parts.path.rsplit('/', 1)[1]
        params = {'space': alice.personal}
        assert public.get(base + '/info', params=params).json()['locked'] is True
        assert public.post(base + '/unlock', params=params, json={'password': 'password123'}).status_code == 200
        assert public.get(base, params=params).content == b'alice public copy'
        alice.delete('/api/shares/' + secure['id'])
        assert public.get(base, params=params).status_code == 404
    assert bob.get('/api/files/download?path=file.txt').content == b'bob private'


def test_spaces_survive_restart_and_auth_disabled_stays_shared(app, accounts):
    alice, bob, eve = accounts
    select(alice, alice.personal)
    put(alice, 'persist.txt', b'persisted')
    restarted = create_app(app.state.settings.model_copy())
    with TestClient(restarted) as connection:
        login = connection.post('/api/auth/login', json={'username': 'alice', 'password': 'test-password'}).json()
        connection.headers['X-CSRF-Token'] = login['csrf_token']
        assert connection.get('/api/spaces').json()['personal'] == alice.personal
        select(connection, alice.personal)
        assert connection.get('/api/files/download?path=persist.txt').content == b'persisted'
    app.state.settings.auth_enabled = False
    assert alice.get('/api/files').json()['total'] == 0
    assert alice.get('/api/spaces').json()['active'] == 'shared'
    assert alice.post('/api/spaces', json={'name': 'Disabled'}).status_code == 403


def test_unauthenticated_requests_cannot_use_space_cookie_to_bypass_login(app, accounts):
    alice, bob, eve = accounts
    select(alice, alice.personal)
    put(alice, 'private.txt', b'secret')
    with TestClient(app) as stranger:
        stranger.cookies.set('rootdrive_space', alice.personal)
        for endpoint in ['/api/files', '/api/files/download?path=private.txt', '/api/editor?path=private.txt', '/api/files/thumbnail?path=private.txt', '/api/trash', '/api/shares', '/api/gallery', '/api/library/pins', '/api/library/audio']:
            assert stranger.get(endpoint).status_code == 401, endpoint
