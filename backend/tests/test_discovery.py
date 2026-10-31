from test_rootdrive import app, client, put


def test_duplicates_compare_content_and_reuse_hashes(client):
    put(client, 'one.txt', b'same')
    put(client, 'two.txt', b'same')
    put(client, 'other.txt', b'nope')
    first = client.post('/api/discovery/duplicates').json()
    assert first['hashed'] == 3
    assert len(first['groups']) == 1
    assert {item['path'] for item in first['groups'][0]['items']} == {'one.txt', 'two.txt'}
    assert client.post('/api/discovery/duplicates').json()['hashed'] == 0
    client.request('DELETE', '/api/files', json={'path': 'two.txt'})
    assert client.post('/api/discovery/duplicates').json()['groups'] == []
    assert client.get('/api/files/download', params={'path': 'one.txt'}).content == b'same'


def test_content_search_reports_lines_and_never_follows_links(client, app, tmp_path):
    put(client, 'note.md', b'first\nA lovely sunset\nlast')
    put(client, 'binary.txt', b'\x00sunset')
    client.post('/api/folders', json={'name': 'nested'})
    put(client, 'other.py', b'sunset = True', 'nested')
    result = client.get('/api/discovery/content', params={'q': 'SUNSET'}).json()
    assert len(result['items']) == 2
    match = next(item for item in result['items'] if item['entry']['name'] == 'note.md')
    assert match['line'] == 2
    assert match['excerpt'] == 'A lovely sunset'
    assert result['skipped'] == 1
    assert client.get('/api/discovery/content', params={'q': 'sunset', 'path': 'nested'}).json()['scanned'] == 1
    assert client.get('/api/discovery/content', params={'q': 'sunset', 'path': '..'}).status_code == 400
    secret = tmp_path / 'private.txt'
    secret.write_text('sunset')
    (app.state.fs.root / 'link.txt').symlink_to(secret)
    assert client.get('/api/discovery/content', params={'q': 'sunset'}).json()['scanned'] == 3


def test_duplicate_scan_refuses_parallel_work(client, app):
    with app.state.fs.discovery_lock:
        response = client.post('/api/discovery/duplicates')
    assert response.status_code == 409
    assert client.post('/api/discovery/duplicates').status_code == 200
