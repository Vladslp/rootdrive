import io
import stat
import zipfile
import pytest
from test_rootdrive import app, client, put


def upload_zip(client, entries, name='bundle.zip'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for member, data in entries:
            archive.writestr(member, data)
    result = put(client, name, stream.getvalue())
    assert result.status_code == 201
    return name


def test_browse_download_and_extract_selected_archive_members(client, app):
    name = upload_zip(client, [('Album/photo.txt', b'photo'), ('Album/Empty/', b''), ('Notes.txt', b'notes')])
    root = client.get('/api/archives', params={'path': name}).json()
    assert [(entry['name'], entry['type']) for entry in root['items']] == [('Album', 'folder'), ('Notes.txt', 'file')]
    assert client.get('/api/archives', params={'path': name, 'prefix': 'Album'}).json()['total'] == 2
    response = client.get('/api/archives/member', params={'path': name, 'member': 'Album/photo.txt'})
    assert response.content == b'photo'
    assert 'attachment' in response.headers['content-disposition']
    result = client.post('/api/archives/extract', json={'path': name, 'name': 'Extracted', 'members': ['Album']})
    assert result.status_code == 201, result.text
    assert (app.state.fs.root / 'Extracted/Album/photo.txt').read_bytes() == b'photo'
    assert (app.state.fs.root / 'Extracted/Album/Empty').is_dir()
    assert not (app.state.fs.root / 'Extracted/Notes.txt').exists()
    assert client.post('/api/archives/extract', json={'path': name, 'name': 'Extracted'}).status_code == 409
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


@pytest.mark.parametrize('member', ['../outside.txt', '/absolute.txt', 'A/../../outside', 'A\\bad', 'C:/bad', 'A/./file'])
def test_archives_reject_unsafe_members_before_writing(client, app, member):
    name = upload_zip(client, [('safe.txt', b'keep'), (member, b'bad')])
    assert client.get('/api/archives', params={'path': name}).status_code == 400
    assert client.post('/api/archives/extract', json={'path': name, 'name': 'Unsafe'}).status_code == 400
    assert not (app.state.fs.root / 'Unsafe').exists()


def test_archive_links_duplicates_and_size_limits_are_rejected(client, app):
    info = zipfile.ZipInfo('link')
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    name = upload_zip(client, [(info, b'/etc/passwd')])
    assert client.get('/api/archives', params={'path': name}).status_code == 400
    upload_zip(client, [('same', b'1'), ('same', b'2')], 'duplicate.zip')
    assert client.get('/api/archives', params={'path': 'duplicate.zip'}).status_code == 415
    upload_zip(client, [('huge', b'0' * (2 * 1024 * 1024))], 'large.zip')
    app.state.settings.max_upload_size_mb = 1
    assert client.post('/api/archives/extract', json={'path': 'large.zip'}).status_code == 413
    assert not (app.state.fs.root / 'large extracted').exists()


def test_copy_is_streamed_conflict_safe_and_preserves_folders(client, app, tmp_path):
    client.post('/api/folders', json={'name': 'Source'})
    client.post('/api/folders', json={'path': 'Source', 'name': 'Empty'})
    put(client, 'note.txt', b'hello', 'Source')
    outside = tmp_path / 'outside.txt'
    outside.write_text('secret')
    (app.state.fs.root / 'Source/link.txt').symlink_to(outside)
    result = client.post('/api/files/copy', json={'paths': ['Source'], 'destination': ''})
    assert result.status_code == 201, result.text
    assert (app.state.fs.root / 'Source (copy)/note.txt').read_bytes() == b'hello'
    assert (app.state.fs.root / 'Source (copy)/Empty').is_dir()
    assert not (app.state.fs.root / 'Source (copy)/link.txt').exists()
    assert (app.state.fs.root / 'Source/note.txt').read_bytes() == b'hello'
    assert client.post('/api/files/copy', json={'paths': ['Source'], 'destination': 'Source'}).status_code == 400
    assert client.post('/api/files/copy', json={'paths': ['../outside.txt']}).status_code == 400
    assert client.post('/api/files/copy', json={'paths': ['Source/link.txt']}).status_code == 400
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())


def test_copy_failure_rolls_back_already_created_targets(client, app, monkeypatch):
    from app.services import transfers
    put(client, 'one.txt', b'one')
    put(client, 'two.txt', b'two')
    link = transfers.os.link
    calls = 0
    def fail(source, destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('disk full')
        return link(source, destination, **kwargs)
    monkeypatch.setattr(transfers.os, 'link', fail)
    assert client.post('/api/files/copy', json={'paths': ['one.txt', 'two.txt']}).status_code == 503
    assert {item.name for item in app.state.fs.root.iterdir()} == {'one.txt', 'two.txt'}
    assert not list((app.state.settings.internal_path / 'uploads').iterdir())
