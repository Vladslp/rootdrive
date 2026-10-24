import os
import select
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.control import control_paths, request_control, server_control
from app.database import User
from app.main import create_app
from app.services.security import hasher
from test_rootdrive import app, client, put


def test_upload_limit_changes_live_and_survives_restart(client, app):
    assert client.patch('/api/settings', json={'max_upload_size_mb': 1}).status_code == 200
    assert client.get('/api/settings').json()['max_upload_size_mb'] == 1
    assert client.get('/api/auth/me').json()['max_upload_size_mb'] == 1
    assert put(client, 'large.bin', b'x' * (1024 * 1024 + 1)).status_code == 413
    settings = app.state.settings.model_copy()
    settings.max_upload_size_mb = 2048
    restarted = create_app(settings)
    with TestClient(restarted) as connection:
        assert connection.get('/api/settings').json()['max_upload_size_mb'] == 1
        assert put(connection, 'small.txt', b'hello').status_code == 201


@pytest.mark.parametrize('value', [0, -1, 1048577, 1.5, True, '4096'])
def test_upload_limit_validation(client, value):
    assert client.patch('/api/settings', json={'max_upload_size_mb': value}).status_code == 422
    assert client.get('/api/auth/me').json()['max_upload_size_mb'] == 2048


def test_limit_reduction_applies_to_pending_transfers(client):
    job = client.post('/api/uploads', json={'relative_path': 'large.bin', 'size': 1024 * 1024 + 1}).json()
    assert client.patch('/api/settings', json={'max_upload_size_mb': 1}).status_code == 200
    assert client.put('/api/uploads/' + job['id'], params={'offset': 0}, content=b'x').status_code == 413
    assert client.post('/api/uploads/' + job['id'] + '/complete').status_code == 413
    assert client.get('/api/uploads/' + job['id']).json()['received'] == 0


def test_request_guard_honors_increased_limit(client, app):
    app.state.settings.max_upload_size_mb = 1
    client.get('/api/health')
    assert client.patch('/api/settings', json={'max_upload_size_mb': 4}).status_code == 200
    files = [('files', (f'{index}.bin', b'x' * (4 * 1024 * 1024))) for index in range(6)]
    assert client.post('/api/files/upload', files=files).status_code == 201


def test_setting_write_failure_keeps_current_limit(client, monkeypatch):
    def fail(self):
        raise OSError('simulated database failure')
    with monkeypatch.context() as context:
        context.setattr(Session, 'commit', fail)
        assert client.patch('/api/settings', json={'max_upload_size_mb': 4096}).status_code == 503
    assert client.get('/api/settings').json()['max_upload_size_mb'] == 2048


def test_upload_limit_admin_and_csrf(app):
    app.state.settings.auth_enabled = True
    with app.state.db() as db:
        db.add_all([User(username='admin', role='admin', password_hash=hasher.hash('long-password')), User(username='member', role='user', password_hash=hasher.hash('long-password'))])
        db.commit()
    with TestClient(app) as connection:
        assert connection.get('/api/settings').status_code == 401
        response = connection.post('/api/auth/login', json={'username': 'member', 'password': 'long-password'}).json()
        connection.headers['X-CSRF-Token'] = response['csrf_token']
        assert connection.get('/api/settings').status_code == 200
        assert connection.patch('/api/settings', json={'max_upload_size_mb': 4096}).status_code == 403
        connection.post('/api/auth/logout')
        response = connection.post('/api/auth/login', json={'username': 'admin', 'password': 'long-password'}).json()
        connection.headers.pop('X-CSRF-Token')
        assert connection.patch('/api/settings', json={'max_upload_size_mb': 4096}).status_code == 403
        connection.headers['X-CSRF-Token'] = response['csrf_token']
        assert connection.patch('/api/settings', json={'max_upload_size_mb': 4096}).status_code == 200


@pytest.fixture
def controlled_process(tmp_path):
    project = tmp_path / 'Project with spaces'
    project.mkdir()
    code = '''import signal,sys,threading
from app.control import server_control
finished=threading.Event()
signal.signal(signal.SIGTERM,lambda *args:finished.set())
with server_control(sys.argv[1]):
    print('ready',flush=True)
    finished.wait(15)
'''
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    process = subprocess.Popen([sys.executable, '-c', code, str(project)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline().strip() == 'ready'
        yield process, project
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def test_control_stops_only_matching_project(controlled_process, tmp_path):
    process, project = controlled_process
    other = tmp_path / 'Other project'
    other.mkdir()
    assert request_control('STOP', other) is None
    assert process.poll() is None
    assert request_control('PING', project) == 'running'
    assert request_control('STOP', project) == 'stopping'
    assert process.wait(timeout=4) == 0
    assert request_control('STOP', project) is None
    assert not control_paths(project)[0].exists()


def test_duplicate_control_does_not_replace_running_server(controlled_process):
    process, project = controlled_process
    with pytest.raises(RuntimeError, match='already running'):
        with server_control(project):
            pass
    assert request_control('PING', project) == 'running'
    assert process.poll() is None


def test_control_rejects_untrusted_directory(tmp_path, monkeypatch):
    import app.control as control
    monkeypatch.setattr(control, 'CONTROL_BASE', tmp_path)
    directory = tmp_path / f'rootdrive-{os.getuid()}'
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    with pytest.raises(RuntimeError, match='private'):
        control_paths(tmp_path)
