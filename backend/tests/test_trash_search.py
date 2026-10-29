from test_rootdrive import app, client, put


def test_trash_search_matches_original_paths_and_preserves_global_revision(client):
    client.post('/api/folders', json={'name': 'Travel'})
    for name, content, path in [('a.txt', b'a', 'Travel'), ('z.txt', b'zz', ''), ('100%.txt', b'xxx', '')]:
        put(client, name, content, path)
        client.request('DELETE', '/api/files', json={'path': path + '/' + name if path else name})
    full = client.get('/api/trash').json()
    search = client.get('/api/trash', params={'q': 'TRAVEL'}).json()
    assert search['total'] == 1
    assert search['items'][0]['path'] == 'Travel/a.txt'
    assert search['revision'] == full['revision']
    assert client.get('/api/trash', params={'q': '%'}).json()['total'] == 1
    assert client.get('/api/trash', params={'q': 'missing'}).json()['total'] == 0
    sorted_items = client.get('/api/trash', params={'sort': 'size', 'direction': 'asc'}).json()['items']
    assert [entry['size'] for entry in sorted_items] == [1, 2, 3]
    page = client.get('/api/trash', params={'sort': 'size', 'direction': 'asc', 'offset': 1, 'limit': 1}).json()
    assert page['items'] == sorted_items[1:2]
    assert page['total'] == 3
    assert client.get('/api/trash', params={'sort': 'invalid'}).status_code == 422
