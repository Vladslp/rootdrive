import pytest
from test_rootdrive import app, client


def test_location_matches_the_sorted_page(client, app):
    root = app.state.fs.root
    (root / 'Nested').mkdir()
    for index in range(125):
        (root / 'Nested' / f'{index:03}.txt').write_text('data')
    result = client.get('/api/files/location', params={'path': 'Nested/124.txt', 'limit': 60})
    assert result.json() == {'path': 'Nested', 'offset': 120}
    page = client.get('/api/files', params={**result.json(), 'limit': 60}).json()
    assert any(item['path'] == 'Nested/124.txt' for item in page['items'])
    assert client.get('/api/files/location', params={'path': 'Nested'}).json() == {'path': '', 'offset': 0}


@pytest.mark.parametrize('path', ['../outside', '/etc/passwd', 'missing', ''])
def test_location_rejects_unsafe_or_missing_targets(client, path):
    assert client.get('/api/files/location', params={'path': path}).status_code in {400, 404}


def test_location_rejects_symlinks(client, app, tmp_path):
    outside = tmp_path / 'outside'
    outside.write_text('secret')
    (app.state.fs.root / 'link').symlink_to(outside)
    assert client.get('/api/files/location', params={'path': 'link'}).status_code == 400
