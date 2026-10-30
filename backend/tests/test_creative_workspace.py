import io
import zipfile
import pytest
from lxml import etree
from test_rootdrive import app, client, put
from test_editors import document_bytes


def test_pins_and_playlists_follow_moves_and_ignore_trashed_items(client):
    client.post('/api/folders', json={'name': 'Music'})
    assert client.post('/api/library/pins', json={'path': 'Music'}).status_code == 200
    put(client, 'track.mp3', b'audio', 'Music')
    playlist = client.post('/api/library/playlists', json={'name': 'Evening'}).json()['id']
    assert client.post(f'/api/library/playlists/{playlist}/items', json={'paths': ['Music/track.mp3']}).status_code == 200
    client.patch('/api/files/rename', json={'path': 'Music', 'name': 'Songs'})
    assert client.get('/api/library/pins').json()['items'][0]['path'] == 'Songs'
    assert client.get('/api/library/audio', params={'playlist': playlist}).json()['items'][0]['path'] == 'Songs/track.mp3'
    trash = client.request('DELETE', '/api/files', json={'path': 'Songs'}).json()
    assert client.get('/api/library/pins').json()['items'] == []
    assert client.get('/api/library/audio', params={'playlist': playlist}).json()['total'] == 0
    client.post('/api/trash/restore', json=trash)
    assert client.get('/api/library/audio', params={'playlist': playlist}).json()['total'] == 1
    assert client.delete(f'/api/library/playlists/{playlist}').status_code == 200
    assert client.get('/api/files/download', params={'path': 'Songs/track.mp3'}).content == b'audio'
    assert client.request('DELETE', '/api/library/pins', json={'path': 'Songs'}).status_code == 200
    assert client.get('/api/library/pins').json()['items'] == []


@pytest.mark.parametrize('extension', ['docx', 'odt'])
def test_office_formatting_lists_and_new_paragraph_roundtrip(client, extension):
    name = 'document.' + extension
    put(client, name, document_bytes(extension))
    data = client.get('/api/editor', params={'path': name}).json()
    first = next(item for item in data['paragraphs'] if item['editable'])
    count = len(data['paragraphs'])
    edits = [{'id': first['id'], 'text': first['text'], 'bold': True, 'italic': True, 'style': 'heading1'}, {'id': count, 'text': 'First list item', 'append': True, 'style': 'bullet'}, {'id': count + 1, 'text': 'Second list item', 'append': True, 'style': 'number'}]
    result = client.post('/api/editor', json={'path': name, 'revision': data['revision'], 'kind': 'document', 'paragraphs': edits})
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['paragraphs'][first['id']]['bold'] is True
    assert result['paragraphs'][first['id']]['italic'] is True
    assert result['paragraphs'][first['id']]['style'] == 'heading1'
    assert result['paragraphs'][count]['text'] == 'First list item'
    assert result['paragraphs'][count]['style'] == 'bullet'
    assert result['paragraphs'][count + 1]['style'] == 'number'
    original = client.get('/api/editor', params={'path': name}).json()
    assert len(original['paragraphs']) == count
    copied = client.get('/api/files/download', params={'path': result['entry']['path']}).content
    with zipfile.ZipFile(io.BytesIO(copied)) as archive:
        if extension == 'docx':
            assert 'word/numbering.xml' in archive.namelist()
            numbering = etree.fromstring(archive.read('word/numbering.xml'))
            assert len(numbering) >= 4
            assert b'numbering.xml' in archive.read('[Content_Types].xml')
        else:
            assert b'list-item' in archive.read('content.xml')
