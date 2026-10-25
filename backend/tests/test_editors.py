import io
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image
from pypdf import PdfReader, PdfWriter
from app.config import Settings
from app.database import User
from app.main import create_app
from app.services.security import hasher


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(storage_path=tmp_path / 'storage', database_path=tmp_path / 'data/rootdrive.db', internal_path=tmp_path / 'internal', _env_file=None))


@pytest.fixture
def client(app):
    with TestClient(app) as connection:
        yield connection


def upload(client, name, content):
    assert client.post('/api/files/upload', files={'files': (name, content)}).status_code == 201


def read(client, path):
    response = client.get('/api/editor', params={'path': path})
    assert response.status_code == 200, response.text
    return response.json()


def save(client, path, data, **changes):
    return client.post('/api/editor', json={'path': path, 'revision': data['revision'], 'kind': data['kind'], **changes})


def test_text_save_copy_conflict_and_line_endings(client, app):
    raw = b'\xef\xbb\xbfhello\r\nworld\r\n'
    upload(client, 'note.md', raw)
    original = app.state.settings.storage_path / 'note.md'
    modified = original.stat().st_mtime_ns
    data = read(client, 'note.md')
    assert data['text'] == 'hello\r\nworld\r\n'
    response = save(client, 'note.md', data, text='new\nworld\n')
    assert response.status_code == 200
    assert response.json()['entry']['path'] == 'note (edited).md'
    assert client.get('/api/files/download', params={'path': 'note (edited).md'}).content == b'\xef\xbb\xbfnew\r\nworld\r\n'
    assert original.read_bytes() == raw
    assert original.stat().st_mtime_ns == modified
    assert read(client, 'note (edited).md')['revision'] == response.json()['revision']
    assert client.get('/api/files/versions', params={'path': 'note.md'}).json()['items'] == []
    original.write_bytes(b'changed externally')
    assert save(client, 'note.md', data, text='stale').status_code == 409
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_text_limits_binary_and_unsupported(client, app):
    upload(client, 'binary.txt', b'a\x00b')
    assert client.get('/api/editor', params={'path': 'binary.txt'}).status_code == 415
    upload(client, 'latin.txt', b'\xff')
    assert client.get('/api/editor', params={'path': 'latin.txt'}).status_code == 415
    upload(client, 'unknown.exe', b'abc')
    assert client.get('/api/editor', params={'path': 'unknown.exe'}).status_code == 415
    upload(client, 'large.txt', b'x' * (2 * 1024 * 1024 + 1))
    assert client.get('/api/editor', params={'path': 'large.txt'}).status_code == 413
    upload(client, 'text.txt', b'ok')
    data = read(client, 'text.txt')
    assert save(client, 'text.txt', data, text='\x00').status_code == 422
    assert save(client, 'text.txt', data, text='a' * (2 * 1024 * 1024 + 1)).status_code == 422
    assert save(client, 'text.txt', data, text='\u0410' * (2 * 1024 * 1024)).status_code == 413
    assert client.get('/api/files/download', params={'path': 'text.txt'}).content == b'ok'


def test_editor_isolation_and_kind(client, app, tmp_path):
    outside = tmp_path / 'secret.txt'
    outside.write_text('private')
    (app.state.settings.storage_path / 'link.txt').symlink_to(outside)
    for path in ['../secret.txt', '/etc/passwd', 'link.txt']:
        assert client.get('/api/editor', params={'path': path}).status_code == 400
        assert client.get('/api/editor/image', params={'path': path}).status_code == 400
        assert client.post('/api/editor', json={'path': path, 'revision': '0' * 64, 'kind': 'text', 'text': 'bad'}).status_code == 400
    upload(client, 'hello.txt', b'hello')
    data = read(client, 'hello.txt')
    assert save(client, 'hello.txt', {**data, 'kind': 'photo'}, photo={}).status_code == 422
    assert client.get('/api/editor', params={'path': ''}).status_code == 400


def photo_bytes(format='PNG', animated=False):
    buffer = io.BytesIO()
    image = Image.new('RGBA' if format == 'PNG' else 'RGB', (80, 40), (150, 80, 40, 120) if format == 'PNG' else (150, 80, 40))
    exif = Image.Exif()
    exif[271] = 'RootDrive Test Camera'
    image.save(buffer, format=format, exif=exif, **({'save_all': True, 'append_images': [Image.new('RGB', (80, 40), 'blue')], 'duration': 100, 'loop': 0} if animated else {}))
    return buffer.getvalue()


def test_photo_crop_rotate_adjust_and_alpha(client):
    upload(client, 'photo.png', photo_bytes())
    data = read(client, 'photo.png')
    assert (data['width'], data['height']) == (80, 40)
    preview = client.get('/api/editor/image', params={'path': 'photo.png'})
    assert preview.status_code == 200
    response = save(client, 'photo.png', data, photo={'rotation': 90, 'flip': True, 'crop': [0, 0, 1, .5], 'brightness': 1.2, 'contrast': .9, 'saturation': .8})
    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(client.get('/api/files/download', params={'path': response.json()['entry']['path']}).content)) as image:
        assert image.size == (40, 40)
        assert image.getpixel((10, 10))[3] == 120
        assert image.getexif()[271] == 'RootDrive Test Camera'
        assert image.getexif()[274] == 1
    assert save(client, response.json()['entry']['path'], response.json(), photo={'crop': [.9, 0, .1, 1]}).status_code == 422


def test_photo_animation_and_pixel_limit(client, app):
    upload(client, 'animated.webp', photo_bytes('WEBP', True))
    assert client.get('/api/editor', params={'path': 'animated.webp'}).status_code == 415
    upload(client, 'photo.jpg', photo_bytes('JPEG'))
    app.state.settings.max_preview_pixels = 100
    assert client.get('/api/editor', params={'path': 'photo.jpg'}).status_code == 413


def document_bytes(extension='docx', dangerous=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        if extension == 'docx':
            xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Hello</w:t></w:r><w:r><w:t> world</w:t></w:r></w:p><w:p><w:hyperlink><w:r><w:t>Link</w:t></w:r></w:hyperlink></w:p></w:body></w:document>'
            if dangerous:
                xml = b'<!DOCTYPE document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>'
            archive.writestr('word/document.xml', xml)
            archive.writestr('word/media/preserved.bin', b'embedded-object')
        else:
            archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            archive.writestr('content.xml', b'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><text:p>Hello<text:span> world</text:span>!</text:p></office:text></office:body></office:document-content>')
            archive.writestr('Pictures/preserved.bin', b'embedded-object')
        archive.writestr('unchanged.xml', b'<preserved/>')
    return buffer.getvalue()


@pytest.mark.parametrize('extension', ['docx', 'odt'])
def test_office_text_preserves_package_and_runs(client, extension):
    upload(client, 'paper.' + extension, document_bytes(extension))
    data = read(client, 'paper.' + extension)
    assert data['paragraphs'][0]['text'] == ('Hello world' if extension == 'docx' else 'Hello world!')
    response = save(client, 'paper.' + extension, data, paragraphs=[{'id': 0, 'text': 'Hello bright world!'}])
    assert response.status_code == 200, response.text
    assert response.json()['paragraphs'][0]['text'] == 'Hello bright world!'
    raw = client.get('/api/files/download', params={'path': response.json()['entry']['path']}).content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read('unchanged.xml') == b'<preserved/>'
        assert archive.read('word/media/preserved.bin' if extension == 'docx' else 'Pictures/preserved.bin') == b'embedded-object'
        if extension == 'docx':
            tree = etree.fromstring(archive.read('word/document.xml'))
            assert len(tree.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}b')) == 1
            assert response.json()['paragraphs'][1]['editable'] is False
            assert save(client, response.json()['entry']['path'], response.json(), paragraphs=[{'id': 1, 'text': 'destroy'}]).status_code == 422
        else:
            assert archive.infolist()[0].filename == 'mimetype'
            assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_document_entities_damaged_and_locked(client):
    upload(client, 'evil.docx', document_bytes(dangerous=True))
    assert client.get('/api/editor', params={'path': 'evil.docx'}).status_code == 415
    upload(client, 'broken.odt', b'not a document')
    assert client.get('/api/editor', params={'path': 'broken.odt'}).status_code == 415
    upload(client, 'paper.docx', document_bytes())
    data = read(client, 'paper.docx')
    assert save(client, 'paper.docx', data, paragraphs=[{'id': 0, 'text': 'x'}, {'id': 0, 'text': 'y'}]).status_code == 422
    assert save(client, 'paper.docx', data, paragraphs=[{'id': 20, 'text': 'x'}]).status_code == 422


def pdf_bytes(encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_blank_page(width=400, height=500)
    writer.add_blank_page(width=600, height=700)
    writer.add_metadata({'/Title': 'RootDrive PDF'})
    if encrypted:
        writer.encrypt('test-password')
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_reorder_rotate_delete_and_metadata(client):
    upload(client, 'pages.pdf', pdf_bytes())
    data = read(client, 'pages.pdf')
    assert data['pages'] == 3
    response = save(client, 'pages.pdf', data, pages=[{'index': 2, 'rotation': 90}, {'index': 0, 'rotation': 0}])
    assert response.status_code == 200, response.text
    reader = PdfReader(io.BytesIO(client.get('/api/files/download', params={'path': response.json()['entry']['path']}).content))
    assert len(reader.pages) == 2
    assert reader.pages[0].mediabox.width == 600
    assert reader.pages[0].rotation == 90
    assert reader.pages[1].mediabox.width == 200
    assert reader.metadata.title == 'RootDrive PDF'
    assert save(client, response.json()['entry']['path'], response.json(), pages=[]).status_code == 422
    assert save(client, response.json()['entry']['path'], response.json(), pages=[{'index': 0}, {'index': 0}]).status_code == 422
    assert save(client, response.json()['entry']['path'], response.json(), pages=[{'index': 2}]).status_code == 422


def test_pdf_encrypted_and_damaged(client):
    upload(client, 'locked.pdf', pdf_bytes(True))
    assert client.get('/api/editor', params={'path': 'locked.pdf'}).status_code == 415
    upload(client, 'broken.pdf', b'broken')
    assert client.get('/api/editor', params={'path': 'broken.pdf'}).status_code == 415


def test_editor_requires_auth_and_csrf(tmp_path):
    app = create_app(Settings(auth_enabled=True, storage_path=tmp_path / 'storage', database_path=tmp_path / 'data/app.db', internal_path=tmp_path / 'internal', _env_file=None))
    (app.state.settings.storage_path / 'private.txt').write_text('private')
    with app.state.db() as db:
        db.add(User(username='editor', password_hash=hasher.hash('valid-test-password'), role='user'))
        db.commit()
    with TestClient(app) as client:
        assert client.get('/api/editor', params={'path': 'private.txt'}).status_code == 401
        assert client.get('/api/editor/image', params={'path': 'private.txt'}).status_code == 401
        assert client.post('/api/editor', json={'path': 'private.txt', 'revision': '0' * 64, 'kind': 'text', 'text': 'x'}).status_code == 401
        login = client.post('/api/auth/login', json={'username': 'editor', 'password': 'valid-test-password'})
        assert login.status_code == 200
        data = read(client, 'private.txt')
        assert save(client, 'private.txt', data, text='saved').status_code == 403
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        assert save(client, 'private.txt', data, text='saved').status_code == 200


@pytest.mark.parametrize('extension', ['docx', 'odt'])
def test_office_line_breaks_tabs_and_spaces(client, extension):
    upload(client, 'spaces.' + extension, document_bytes(extension))
    data = read(client, 'spaces.' + extension)
    text = '  Hello\nnew\tworld  ! '
    result = save(client, 'spaces.' + extension, data, paragraphs=[{'id': 0, 'text': text}])
    assert result.status_code == 200, result.text
    assert result.json()['paragraphs'][0]['text'] == text
    assert result.json()['paragraphs'][0]['editable'] is True
    result = save(client, result.json()['entry']['path'], result.json(), paragraphs=[{'id': 0, 'text': 'Changed again\nwith  spaces'}])
    assert result.status_code == 200
    assert result.json()['paragraphs'][0]['text'] == 'Changed again\nwith  spaces'


def test_pdf_range_for_editor(client):
    raw = pdf_bytes()
    upload(client, 'range.pdf', raw)
    response = client.get('/api/files/media', params={'path': 'range.pdf'}, headers={'Range': 'bytes=10-29'})
    assert response.status_code == 206
    assert response.content == raw[10:30]
    assert response.headers['content-type'].startswith('application/pdf')
    assert client.head('/api/files/media', params={'path': 'range.pdf'}).headers['content-length'] == str(len(raw))


@pytest.mark.parametrize('mode', ['copy', 'original'])
def test_editor_save_rolls_back_on_database_failure(client, app, monkeypatch, mode):
    from sqlalchemy.orm import Session
    upload(client, 'rollback.txt', b'original')
    data = read(client, 'rollback.txt')
    def fail_commit(self):
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(Session, 'commit', fail_commit)
    with pytest.raises(RuntimeError):
        save(client, 'rollback.txt', data, text='changed', mode=mode)
    assert (app.state.settings.storage_path / 'rollback.txt').read_bytes() == b'original'
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())
    assert not list((app.state.settings.internal_path / 'versions').glob('*'))
    assert not (app.state.settings.storage_path / 'rollback (edited).txt').exists()


@pytest.mark.parametrize('name,content,changes', [
    ('source.txt', b'original', {'text': 'changed'}),
    ('source.png', photo_bytes(), {'photo': {'rotation': 90, 'brightness': .5}}),
    ('source.docx', document_bytes(), {'paragraphs': [{'id': 0, 'text': 'Changed paragraph'}]}),
    ('source.odt', document_bytes('odt'), {'paragraphs': [{'id': 0, 'text': 'Changed paragraph'}]}),
    ('source.pdf', pdf_bytes(), {'pages': [{'index': 1, 'rotation': 90}]}),
])
def test_save_original_preserves_recoverable_version(client, app, name, content, changes):
    upload(client, name, content)
    data = read(client, name)
    result = save(client, name, data, mode='original', **changes)
    assert result.status_code == 200, result.text
    assert result.json()['entry']['path'] == name
    assert result.json()['mode'] == 'original'
    assert (app.state.settings.storage_path / name).read_bytes() != content
    assert read(client, name)['revision'] == result.json()['revision']
    assert len(list(app.state.settings.storage_path.iterdir())) == 1
    versions = client.get('/api/files/versions', params={'path': name}).json()['items']
    assert len(versions) == 1
    assert (app.state.settings.internal_path / 'versions' / versions[0]['id']).read_bytes() == content
    assert save(client, name, data, mode='original', **changes).status_code == 409
    assert client.post('/api/versions/' + versions[0]['id'] + '/restore').status_code == 200
    assert (app.state.settings.storage_path / name).read_bytes() == content


def test_original_save_rejects_invalid_mode_and_limit_without_versions(client, app):
    upload(client, 'note.txt', b'original')
    data = read(client, 'note.txt')
    assert save(client, 'note.txt', data, mode='overwrite', text='changed').status_code == 422
    app.state.settings.max_upload_size_mb = 1
    assert save(client, 'note.txt', data, mode='original', text='x' * (1024 * 1024 + 1)).status_code == 413
    assert (app.state.settings.storage_path / 'note.txt').read_bytes() == b'original'
    assert client.get('/api/files/versions', params={'path': 'note.txt'}).json()['items'] == []


def test_heic_editor_save_copy_preserves_original(client):
    buffer = io.BytesIO()
    Image.new('RGB', (120, 80), '#739a86').save(buffer, format='HEIF', quality=90)
    raw = buffer.getvalue()
    upload(client, 'camera.heic', raw)
    data = read(client, 'camera.heic')
    result = save(client, 'camera.heic', data, photo={'rotation': 90, 'crop': [0, 0, 1, 1]})
    assert result.status_code == 200, result.text
    with Image.open(io.BytesIO(client.get('/api/files/download', params={'path': result.json()['entry']['path']}).content)) as image:
        assert image.size == (80, 120)
    assert client.get('/api/files/download', params={'path': 'camera.heic'}).content == raw
    assert client.get('/api/files/versions', params={'path': 'camera.heic'}).json()['items'] == []


def test_photo_palette_transparency(client):
    buffer = io.BytesIO()
    image = Image.new('P', (80, 40), 0)
    image.putpalette([100, 140, 180] + [0, 0, 0] * 255)
    image.save(buffer, format='PNG', transparency=0)
    upload(client, 'palette.png', buffer.getvalue())
    data = read(client, 'palette.png')
    result = save(client, 'palette.png', data, photo={'brightness': 1.2})
    assert result.status_code == 200
    with Image.open(io.BytesIO(client.get('/api/files/download', params={'path': result.json()['entry']['path']}).content)) as saved:
        assert saved.convert('RGBA').getpixel((0, 0))[3] == 0


def test_office_signed_document_rejected(client):
    buffer = io.BytesIO(document_bytes())
    with zipfile.ZipFile(buffer, 'a') as archive:
        archive.writestr('_xmlsignatures/sig1.xml', '<signature/>')
    upload(client, 'signed.docx', buffer.getvalue())
    assert client.get('/api/editor', params={'path': 'signed.docx'}).status_code == 415


def test_edit_limit_preserves_original(client, app):
    upload(client, 'limit.txt', b'small')
    data = read(client, 'limit.txt')
    app.state.settings.max_upload_size_mb = 1
    assert save(client, 'limit.txt', data, text='a' * (1024 * 1024 + 1)).status_code == 413
    assert (app.state.settings.storage_path / 'limit.txt').read_bytes() == b'small'
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_copy_names_skip_files_folders_and_symlinks(client, app, tmp_path):
    upload(client, 'note.txt', b'original')
    upload(client, 'note (edited).txt', b'keep this copy')
    root = app.state.settings.storage_path
    (root / 'note (edited 2).txt').mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('private')
    (root / 'note (edited 3).txt').symlink_to(outside)
    (root / 'note (edited 4).txt').symlink_to(tmp_path / 'missing')
    data = read(client, 'note.txt')
    result = save(client, 'note.txt', data, text='new copy')
    assert result.status_code == 200
    assert result.json()['entry']['name'] == 'note (edited 5).txt'
    result = save(client, 'note.txt', data, text='another copy')
    assert result.json()['entry']['name'] == 'note (edited 6).txt'
    assert (root / 'note.txt').read_bytes() == b'original'
    assert (root / 'note (edited).txt').read_bytes() == b'keep this copy'
    assert outside.read_text() == 'private'


@pytest.mark.parametrize('name', ['Dockerfile', 'Makefile', '.gitignore', '.env.example', '\u0444' * 116 + '.txt'])
def test_copy_names_remain_safe_and_editable(client, app, name):
    upload(client, name, b'original')
    data = read(client, name)
    result = save(client, name, data, text='copy')
    assert result.status_code == 200, result.text
    copy = result.json()['entry']
    assert len(copy['name'].encode()) <= 240
    assert read(client, copy['path'])['text'] == 'copy'
    assert (app.state.settings.storage_path / name).read_bytes() == b'original'


def test_edited_copy_stays_in_source_folder(client, app):
    assert client.post('/api/folders', json={'name': 'Documents'}).status_code == 201
    assert client.post('/api/files/upload', params={'path': 'Documents'}, files={'files': ('note.md', b'original')}).status_code == 201
    result = save(client, 'Documents/note.md', read(client, 'Documents/note.md'), text='copy')
    assert result.status_code == 200
    assert result.json()['entry']['path'] == 'Documents/note (edited).md'
    assert (app.state.settings.storage_path / 'Documents/note.md').read_bytes() == b'original'


@pytest.mark.parametrize('name,content,changes', [
    ('source.png', photo_bytes(), {'photo': {'rotation': 90}}),
    ('source.docx', document_bytes(), {'paragraphs': [{'id': 0, 'text': 'Changed paragraph'}]}),
    ('source.odt', document_bytes('odt'), {'paragraphs': [{'id': 0, 'text': 'Changed paragraph'}]}),
    ('source.pdf', pdf_bytes(), {'pages': [{'index': 1, 'rotation': 90}]}),
])
def test_all_editors_preserve_source_bytes_and_timestamp(client, app, name, content, changes):
    upload(client, name, content)
    original = app.state.settings.storage_path / name
    modified = original.stat().st_mtime_ns
    result = save(client, name, read(client, name), **changes)
    assert result.status_code == 200, result.text
    assert original.read_bytes() == content
    assert original.stat().st_mtime_ns == modified
    assert result.json()['entry']['path'] != name
    assert (app.state.settings.storage_path / result.json()['entry']['path']).read_bytes() != content
    assert client.get('/api/files/versions', params={'path': name}).json()['items'] == []


def test_editing_a_copy_uses_next_number(client):
    upload(client, 'note.txt', b'original')
    first = save(client, 'note.txt', read(client, 'note.txt'), text='copy').json()
    second = save(client, first['entry']['path'], first, text='next copy')
    assert second.status_code == 200
    assert second.json()['entry']['path'] == 'note (edited 2).txt'
    assert client.get('/api/files/download', params={'path': first['entry']['path']}).content == b'copy'
