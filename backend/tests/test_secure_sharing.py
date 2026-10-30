import time
from fastapi.testclient import TestClient
from app.database import Share, ShareProtection
from test_rootdrive import app, client, put


def test_folder_share_is_scoped_and_survives_rename(client, app):
    app.state.settings.enable_public_shares = True
    client.post('/api/folders', json={'name': 'Shared'})
    client.post('/api/folders', json={'path': 'Shared', 'name': 'Nested'})
    put(client, 'inside.txt', b'allowed', 'Shared/Nested')
    put(client, 'secret.txt', b'secret')
    share = client.post('/api/shares', json={'path': 'Shared'}).json()
    token = share['url'].rsplit('/', 1)[1]
    root = f'/api/public/{token}'
    assert client.get(root + '/info').json()['type'] == 'folder'
    assert client.get(root + '/list').json()['items'][0]['path'] == 'Nested'
    assert client.get(root + '/list', params={'path': 'Nested'}).json()['items'][0]['path'] == 'Nested/inside.txt'
    assert client.get(root, params={'path': 'Nested/inside.txt'}).content == b'allowed'
    for unsafe in ['../secret.txt', '/secret.txt', 'Nested/../../secret.txt', 'Nested\\inside.txt']:
        assert client.get(root, params={'path': unsafe}).status_code == 400
    assert client.patch('/api/files/rename', json={'path': 'Shared', 'name': 'Renamed'}).status_code == 200
    assert client.get(root, params={'path': 'Nested/inside.txt'}).content == b'allowed'
    assert client.delete('/api/shares/' + share['id']).status_code == 200
    assert client.get(root + '/info').status_code == 404


def test_password_grants_are_hashed_expire_and_do_not_unlock_other_links(client, app):
    app.state.settings.enable_public_shares = True
    put(client, 'private.txt', b'private')
    first = client.post('/api/shares', json={'path': 'private.txt', 'password': 'correct horse'}).json()
    second = client.post('/api/shares', json={'path': 'private.txt', 'password': 'another password'}).json()
    base = '/api/public/' + first['url'].rsplit('/', 1)[1]
    other = '/api/public/' + second['url'].rsplit('/', 1)[1]
    assert client.get(base + '/info').json()['locked'] is True
    assert client.get(base).status_code == 403
    assert client.post(base + '/unlock', json={'password': 'wrong'}).status_code == 403
    result = client.post(base + '/unlock', json={'password': 'correct horse'})
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie']
    assert client.get(base).content == b'private'
    assert client.get(other).status_code == 403
    with TestClient(app) as stranger:
        assert stranger.get(base).status_code == 403
    with app.state.db() as db:
        protection = db.get(ShareProtection, first['id'])
        assert protection.password_hash.startswith('$argon2id$')
        share = db.get(Share, first['id'])
        share.expires_at = time.time() - 1
        db.commit()
    assert client.get(base).status_code == 404


def test_public_share_rejects_cross_origin_unlock_and_symlink(client, app, tmp_path):
    app.state.settings.enable_public_shares = True
    client.post('/api/folders', json={'name': 'Folder'})
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret')
    (app.state.fs.root / 'Folder/link.txt').symlink_to(outside)
    share = client.post('/api/shares', json={'path': 'Folder', 'password': 'password123'}).json()
    base = '/api/public/' + share['url'].rsplit('/', 1)[1]
    assert client.post(base + '/unlock', json={'password': 'password123'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    client.post(base + '/unlock', json={'password': 'password123'})
    assert client.get(base, params={'path': 'link.txt'}).status_code == 400
    for _ in range(9):
        client.post(base + '/unlock', json={'password': 'wrong'})
    assert client.post(base + '/unlock', json={'password': 'wrong'}).status_code == 429
