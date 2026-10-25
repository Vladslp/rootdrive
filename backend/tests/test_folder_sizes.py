import time
from test_rootdrive import app, client, put


def test_folder_size_empty_state_and_nested_contents(client, app, tmp_path):
    root = app.state.fs.root
    (root / 'Empty').mkdir()
    (root / 'Full' / 'Nested').mkdir(parents=True)
    (root / 'Full' / 'Nested' / 'photo.jpg').write_bytes(b'12345')
    (root / 'Full' / 'note.txt').write_bytes(b'abc')
    (root / 'Empty' / '.DS_Store').write_bytes(b'ignored')
    outside = tmp_path / 'private.txt'
    outside.write_bytes(b'not counted')
    (root / 'Empty' / 'link.txt').symlink_to(outside)
    entries = {item['name']: item for item in client.get('/api/files').json()['items']}
    assert entries['Empty']['child_count'] == 0 and entries['Empty']['size'] == 0
    assert entries['Full']['child_count'] == 2 and entries['Full']['size'] == 8
    nested = client.get('/api/files', params={'path': 'Full'}).json()['items']
    assert nested[0]['child_count'] == 1 and nested[0]['size'] == 5


def test_folder_size_cache_reused_and_invalidated_by_operations(client, app, monkeypatch):
    client.post('/api/folders', json={'name': 'Photos'})
    root = app.state.fs.root
    (root / 'Photos' / 'first.txt').write_bytes(b'abc')
    assert client.get('/api/files').json()['items'][0]['size'] == 3
    from app.services import filesystem
    original = filesystem.os.scandir
    scans = []
    def scan(path):
        scans.append(path)
        return original(path)
    monkeypatch.setattr(filesystem.os, 'scandir', scan)
    assert client.get('/api/files').json()['items'][0]['size'] == 3
    assert root / 'Photos' not in scans
    assert client.post('/api/files/upload', params={'path': 'Photos'}, files={'files': ('next.txt', b'12345')}).status_code == 201
    assert client.get('/api/files').json()['items'][0]['size'] == 8
    client.request('DELETE', '/api/files', json={'path': 'Photos/first.txt'})
    assert client.get('/api/files').json()['items'][0]['size'] == 5


def test_folder_size_external_changes_expire_and_sort(client, app):
    root = app.state.fs.root
    (root / 'A').mkdir()
    (root / 'B').mkdir()
    (root / 'A' / 'one.txt').write_bytes(b'1')
    (root / 'B' / 'two.txt').write_bytes(b'22')
    entries = client.get('/api/files', params={'sort': 'size', 'direction': 'desc'}).json()['items']
    assert [item['name'] for item in entries] == ['B', 'A']
    (root / 'A' / 'one.txt').write_bytes(b'12345')
    for key, (_, value) in app.state.fs.folder_cache.items():
        app.state.fs.folder_cache[key] = (time.monotonic() - 31, value)
    entries = client.get('/api/files', params={'sort': 'size', 'direction': 'desc'}).json()['items']
    assert [item['name'] for item in entries] == ['A', 'B']
    assert entries[0]['size'] == 5
