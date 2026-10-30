from test_rootdrive import app, client, put


def test_virtual_albums_follow_renames_and_preserve_originals(client):
    put(client, 'one.jpg', b'photo')
    put(client, 'two.png', b'photo')
    put(client, 'note.txt', b'text')
    assert client.get('/api/gallery').json()['total'] == 2
    album = client.post('/api/albums', json={'name': 'Trips'}).json()['id']
    assert client.post(f'/api/albums/{album}/items', json={'paths': ['one.jpg']}).status_code == 200
    assert client.get('/api/gallery', params={'album': album}).json()['total'] == 1
    assert client.patch('/api/files/rename', json={'path': 'one.jpg', 'name': 'renamed.jpg'}).status_code == 200
    assert client.get('/api/gallery', params={'album': album}).json()['items'][0]['path'] == 'renamed.jpg'
    assert client.post(f'/api/albums/{album}/items', json={'paths': ['note.txt']}).status_code == 415
    deleted = client.request('DELETE', '/api/files', json={'path': 'renamed.jpg'}).json()
    assert client.get('/api/gallery', params={'album': album}).json()['total'] == 0
    client.post('/api/trash/restore', json=deleted)
    assert client.get('/api/gallery', params={'album': album}).json()['total'] == 1
    assert client.delete(f'/api/albums/{album}').status_code == 200
    assert client.get('/api/files/download', params={'path': 'renamed.jpg'}).content == b'photo'


def test_gallery_pagination_and_album_validation(client, app, tmp_path):
    client.post('/api/folders', json={'name': 'nested'})
    put(client, 'a.jpg', b'a', 'nested')
    put(client, 'b.jpg', b'b')
    assert len(client.get('/api/gallery?limit=1').json()['items']) == 1
    assert client.get('/api/gallery?limit=1&offset=1').json()['total'] == 2
    assert client.get('/api/gallery?album=missing').status_code == 404
    assert client.post('/api/albums', json={'name': '  '}).status_code == 422
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(b'secret')
    (app.state.fs.root / 'link.jpg').symlink_to(outside)
    assert client.get('/api/gallery').json()['total'] == 2
    album = client.post('/api/albums', json={'name': 'Safe'}).json()['id']
    assert client.post(f'/api/albums/{album}/items', json={'paths': ['../outside.jpg']}).status_code == 400
