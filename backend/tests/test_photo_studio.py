import io
from PIL import Image
from test_rootdrive import app, client, put


def photo(color='red', exif=True):
    output = io.BytesIO()
    image = Image.new('RGB', (120, 80), color)
    metadata = Image.Exif()
    if exif:
        metadata[271] = 'Example Camera'
        metadata[272] = 'Model X'
        metadata[42036] = '50mm lens'
    image.save(output, format='JPEG', exif=metadata)
    return output.getvalue()


def test_conversion_resize_and_metadata_are_applied_to_copies(client):
    original = photo()
    put(client, 'image.jpg', original)
    for output_format in ['jpeg', 'png', 'webp']:
        result = client.post('/api/studio/export', json={'paths': ['image.jpg'], 'format': output_format, 'width': 60, 'height': 60}).json()
        entry = result['items'][0]
        data = client.get('/api/files/download', params={'path': entry['path']}).content
        with Image.open(io.BytesIO(data)) as image:
            assert image.size == (60, 40)
            assert not image.getexif()
            assert image.format.lower() == output_format
    assert client.get('/api/files/download', params={'path': 'image.jpg'}).content == original
    result = client.post('/api/studio/export', json={'paths': ['image.jpg'], 'format': 'png', 'strip_metadata': False}).json()
    with Image.open(io.BytesIO(client.get('/api/files/download', params={'path': result['items'][0]['path']}).content)) as image:
        assert image.getexif()[272] == 'Model X'


def test_watermark_preview_matches_saved_pixels_and_batch_rollback(client, app):
    put(client, 'first.jpg', photo())
    put(client, 'second.jpg', photo('blue'))
    body = {'paths': ['first.jpg', 'second.jpg'], 'format': 'png', 'watermark': 'RootDrive', 'width': 100, 'height': 100}
    preview = client.post('/api/studio/preview', json=body)
    assert preview.status_code == 200
    assert preview.headers['content-type'] == 'image/png'
    result = client.post('/api/studio/export', json=body).json()
    saved = client.get('/api/files/download', params={'path': result['items'][0]['path']})
    with Image.open(io.BytesIO(saved.content)) as image, Image.open(io.BytesIO(preview.content)) as shown:
        assert image.tobytes() == shown.tobytes()
    before = {path.name for path in app.state.fs.root.iterdir()}
    assert client.post('/api/studio/export', json={'paths': ['first.jpg', '../secret'], 'format': 'png'}).status_code == 400
    assert {path.name for path in app.state.fs.root.iterdir()} == before
    assert list((app.state.settings.internal_path / 'uploads').iterdir()) == []


def test_logo_and_raw_embedded_preview(client, app):
    put(client, 'photo.jpg', photo())
    put(client, 'logo.png', photo('white', False))
    result = client.post('/api/studio/preview', json={'paths': ['photo.jpg'], 'logo': 'logo.png', 'position': 'center'})
    assert result.status_code == 200
    put(client, 'camera.cr2', b'RAW HEADER' + photo() + b'RAW FOOTER')
    thumbnail = client.get('/api/files/thumbnail', params={'path': 'camera.cr2'})
    assert thumbnail.status_code == 200
    with Image.open(io.BytesIO(thumbnail.content)) as image:
        assert image.size == (120, 80)
    assert client.get('/api/files/preview', params={'path': 'camera.cr2'}).status_code == 200
    put(client, 'empty.nef', b'RAW without embedded picture')
    assert client.get('/api/files/thumbnail', params={'path': 'empty.nef'}).status_code == 415
    assert client.post('/api/studio/export', json={'paths': ['camera.cr2'], 'format': 'webp'}).status_code == 201
    app.state.settings.max_preview_pixels = 100
    assert client.post('/api/studio/preview', json={'paths': ['photo.jpg']}).status_code == 413
