import io
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from test_rootdrive import app, client, put


@pytest.mark.parametrize('format,extension', [('JPEG', 'jpg'), ('HEIF', 'heic')])
def test_camera_and_lens_exif(client, format, extension):
    metadata = Image.Exif()
    metadata[271] = 'Test Camera Maker'
    metadata[272] = 'Camera X'
    metadata[34665] = {42036: '24mm F1.8', 33434: IFDRational(1, 125), 33437: IFDRational(18, 10), 34855: 200, 36867: '2026:10:23 12:34:56'}
    output = io.BytesIO()
    Image.new('RGB', (800, 600), 'blue').save(output, format=format, exif=metadata)
    filename = f'camera.{extension}'
    original = output.getvalue()
    assert put(client, filename, original).status_code == 201
    response = client.get('/api/files/metadata', params={'path': filename})
    assert response.status_code == 200
    result = response.json()
    assert result['width'] == 800
    assert result['height'] == 600
    fields = {field['label']: field['value'] for field in result['exif']}
    assert fields['Camera model'] == 'Camera X'
    assert fields['Lens model'] == '24mm F1.8'
    assert fields['Shutter speed'] == '1/125 s'
    assert fields['Aperture'] == 'f/1.8'
    assert fields['ISO'] == '200'
    assert client.get('/api/files/download', params={'path': filename}).content == original


def test_metadata_without_exif_and_permissions(client, app):
    output = io.BytesIO()
    Image.new('RGB', (100, 60), 'white').save(output, format='PNG')
    put(client, 'plain.png', output.getvalue())
    result = client.get('/api/files/metadata', params={'path': 'plain.png'}).json()
    assert result['exif'] == []
    assert result['width'] == 100
    assert client.get('/api/files/metadata', params={'path': '../secret.png'}).status_code == 400
    app.state.settings.auth_enabled = True
    assert client.get('/api/files/metadata', params={'path': 'plain.png'}).status_code == 401


def test_finder_metadata_is_hidden(client, app):
    (app.state.settings.storage_path / '.DS_Store').write_bytes(b'finder')
    assert client.get('/api/files').json()['total'] == 0
    assert client.get('/api/storage/stats').json()['file_count'] == 0


def test_lens_specification_format():
    from app.services.metadata import format_exif
    assert format_exif(42034, (50, 50, 0, 0)) == '50 mm'
    assert format_exif(42034, (24, 70, 2.8, 4)) == '24–70 mm · f/2.8–4'
