import threading
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from test_rootdrive import app, client, put
from test_previews_users import image_bytes


def test_thumbnail_revalidation_checks_revision_and_access(client, app):
    put(client, 'photo.png', image_bytes())
    first = client.get('/api/files/thumbnail', params={'path': 'photo.png'})
    etag = first.headers['etag']
    assert first.headers['cache-control'] == 'private, no-cache'
    assert first.headers['vary'] == 'Cookie'
    cached = client.get('/api/files/thumbnail', params={'path': 'photo.png'}, headers={'If-None-Match': etag})
    assert cached.status_code == 304 and cached.content == b''
    assert client.get('/api/files/thumbnail', params={'path': 'photo.png'}, headers={'If-None-Match': 'W/' + etag}).status_code == 304
    (app.state.fs.root / 'photo.png').write_bytes(image_bytes(size=(600, 1000)))
    changed = client.get('/api/files/thumbnail', params={'path': 'photo.png'}, headers={'If-None-Match': etag})
    assert changed.status_code == 200 and changed.headers['etag'] != etag
    app.state.settings.auth_enabled = True
    assert client.get('/api/files/thumbnail', params={'path': 'photo.png'}, headers={'If-None-Match': changed.headers['etag']}).status_code == 401
    assert client.get('/api/auth/me').headers['cache-control'] == 'no-store'


def test_cached_thumbnail_skips_decode(client, monkeypatch):
    put(client, 'photo.png', image_bytes())
    first = client.get('/api/files/thumbnail', params={'path': 'photo.png'})
    def unavailable(*args, **kwargs):
        raise AssertionError('Cached thumbnail decoded again')
    monkeypatch.setattr(Image, 'open', unavailable)
    assert client.get('/api/files/thumbnail', params={'path': 'photo.png'}).content == first.content


def test_decode_does_not_hold_filesystem_lock(client, app, monkeypatch):
    put(client, 'photo.png', image_bytes())
    decoding, release = threading.Event(), threading.Event()
    original = Image.open
    def slow(*args, **kwargs):
        decoding.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(Image, 'open', slow)
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(client.get, '/api/files/thumbnail', params={'path': 'photo.png'})
        try:
            assert decoding.wait(5)
            listing = executor.submit(client.get, '/api/files')
            assert listing.result(timeout=2).status_code == 200
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200


def test_same_thumbnail_converts_once(client, monkeypatch):
    put(client, 'photo.png', image_bytes())
    original = Image.open
    count = 0
    lock = threading.Lock()
    def counted(*args, **kwargs):
        nonlocal count
        with lock:
            count += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(Image, 'open', counted)
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: client.get('/api/files/thumbnail', params={'path': 'photo.png'}), range(6)))
    assert all(response.status_code == 200 for response in results)
    assert count == 1
    assert all(response.content == results[0].content for response in results)


def test_preview_prune_scan_is_amortized(client, app, monkeypatch):
    from pathlib import Path
    original = Path.glob
    scans = []
    def counted(path, pattern):
        if path == app.state.previews.cache:
            scans.append(pattern)
        return original(path, pattern)
    monkeypatch.setattr(Path, 'glob', counted)
    for index in range(10):
        name = f'photo-{index}.png'
        put(client, name, image_bytes(size=(64, 64)))
        assert client.get('/api/files/thumbnail', params={'path': name}).status_code == 200
    assert scans == ['*.jpg']


def test_preview_concurrency_is_bounded(client, monkeypatch):
    original = Image.open
    active, maximum = 0, 0
    lock = threading.Lock()
    release, started = threading.Event(), threading.Event()
    for index in range(6):
        put(client, f'photo-{index}.png', image_bytes(size=(64, 64)))
    def slow(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            started.set()
        try:
            assert release.wait(5)
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(Image, 'open', slow)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(client.get, '/api/files/thumbnail', params={'path': f'photo-{index}.png'}) for index in range(6)]
        try:
            assert started.wait(5)
        finally:
            release.set()
        assert all(future.result(timeout=5).status_code == 200 for future in futures)
    assert maximum <= 2
