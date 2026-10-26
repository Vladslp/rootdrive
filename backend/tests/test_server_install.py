import io
import json
import os
import pty
import select
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from app import server_install as installer

PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('value', ['relative/path', '/', '/tmp/bad\npath', '/tmp/bad%path', '/tmp/$path', '/tmp/"path'])
def test_installer_rejects_unsafe_paths(value):
    if value == '/':
        with pytest.raises(ValueError):
            installer.install(value, '/tmp/data', False)
    else:
        with pytest.raises(ValueError):
            installer.checked_path(value)


def test_node_manifest_accepts_only_the_expected_major_architecture():
    checksum = 'a' * 64
    manifest = f'{checksum}  node-v24.2.1-linux-arm64.tar.gz\n{checksum}  node-v24.2.1-linux-x64.tar.gz\n'
    assert installer.select_node_archive(manifest, 'arm64') == (checksum, 'node-v24.2.1-linux-arm64.tar.gz')
    with pytest.raises(ValueError):
        installer.select_node_archive(manifest + manifest, 'arm64')
    with pytest.raises(ValueError):
        installer.select_node_archive(manifest.replace('v24.', 'v22.'), 'arm64')


def test_node_download_rejects_invalid_checksum_and_redirect(tmp_path, monkeypatch):
    class Response(io.BytesIO):
        url = 'https://nodejs.org/dist/file'
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *args, **kwargs: Response(b'archive'))
    with pytest.raises(ValueError, match='checksum'):
        installer.download('https://nodejs.org/dist/file', tmp_path / 'archive', 'a' * 64)
    Response.url = 'https://unexpected.example/file'
    with pytest.raises(ValueError, match='destination'):
        installer.download('https://nodejs.org/dist/file', tmp_path / 'archive')


def source_tree(path):
    path.mkdir()
    for name in ['backend', 'frontend']:
        (path / name).mkdir()
        (path / name / 'source.txt').write_text('application')
    for name in ['start.sh', 'stop.sh', 'run.py', 'requirements.txt', '.env.example', 'README.md']:
        (path / name).write_text('source')
    (path / '.env').write_text('PRIVATE_SOURCE_VALUE=secret')
    (path / 'storage').mkdir()
    (path / 'storage/private.txt').write_text('user file')
    (path / 'frontend/node_modules').mkdir()
    (path / 'frontend/node_modules/private.txt').write_text('local dependency')
    return path


@pytest.fixture
def isolated_installer(tmp_path, monkeypatch):
    source = source_tree(tmp_path / 'source')
    application, state = tmp_path / 'installed app', tmp_path / 'state'
    calls = []
    monkeypatch.setattr(installer, 'SOURCE', source)
    monkeypatch.setattr(installer, 'SYSTEMD_UNIT', tmp_path / 'rootdrive.service')
    monkeypatch.setattr(installer.pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=1001, pw_gid=1001))
    monkeypatch.setattr(installer, 'own_tree', lambda *args: None)
    monkeypatch.setattr(installer, 'secure_application', lambda *args: None)
    monkeypatch.setattr(installer, 'ensure_node', lambda *args: Path('/usr/bin'))
    monkeypatch.setattr(installer, 'service_address', lambda *args: ('127.0.0.1', 8000))
    monkeypatch.setattr(installer, 'check_port_free', lambda *args: None)
    monkeypatch.setattr(installer, 'wait_for_service', lambda *args: None)
    monkeypatch.setattr(installer, 'run_as_user', lambda arguments, *args: calls.append([str(value) for value in arguments]))
    monkeypatch.setattr(installer.subprocess, 'run', lambda args, **kwargs: calls.append(list(args)) or SimpleNamespace(returncode=3 if 'is-active' in args else 0))
    return source, application, state, calls


def test_install_and_repeat_preserve_data_and_configuration(isolated_installer):
    source, application, state, calls = isolated_installer
    installer.install(application, state, False)
    configuration = application / '.env'
    assert 'HOST=127.0.0.1' in configuration.read_text()
    assert 'AUTH_ENABLED=false' in configuration.read_text()
    assert 'PRIVATE_SOURCE_VALUE' not in configuration.read_text()
    assert not (application / 'storage/private.txt').exists()
    assert not (application / 'frontend/node_modules/private.txt').exists()
    assert json.loads((application / '.rootdrive-server.json').read_text())['state'] == str(state)
    configuration.write_text('HOST=127.0.0.1\nAUTH_ENABLED=true\n')
    (state / 'storage/photo.jpg').write_bytes(b'preserved')
    (application / 'server-install.sh').write_text('obsolete launcher')
    installer.install(application, state, False)
    assert 'AUTH_ENABLED=true' in configuration.read_text()
    assert not (application / 'server-install.sh').exists()
    assert (state / 'storage/photo.jpg').read_bytes() == b'preserved'
    assert any('--install-only' in call for call in calls)
    assert not any('systemctl' in call for call in calls)


def test_installer_does_not_adopt_unmanaged_data(isolated_installer):
    _, application, state, calls = isolated_installer
    state.mkdir()
    (state / 'important.txt').write_text('preserve')
    with pytest.raises(ValueError, match='not managed'):
        installer.install(application, state, False)
    assert calls == []
    assert (state / 'important.txt').read_text() == 'preserve'


def test_installer_does_not_replace_unmanaged_service(isolated_installer):
    _, application, state, calls = isolated_installer
    installer.SYSTEMD_UNIT.write_text('custom service')
    with pytest.raises(ValueError, match='not managed'):
        installer.install(application, state)
    assert installer.SYSTEMD_UNIT.read_text() == 'custom service'
    assert calls == []


def test_unit_uses_unprivileged_account_and_quoted_paths():
    unit = installer.unit_text(Path('/opt/Root Drive'))
    assert 'User=rootdrive' in unit
    assert 'ExecStart="/opt/Root Drive/.venv/bin/python" "/opt/Root Drive/run.py" serve' in unit
    assert 'Restart=on-failure' in unit and 'NoNewPrivileges=true' in unit
    assert 'HOST=0.0.0.0' not in unit
    assert 'start.sh' not in unit


@pytest.fixture
def launcher(tmp_path):
    path = tmp_path / 'Project with spaces'
    path.mkdir()
    source = (PROJECT / 'start.sh').read_text()
    begin = source.index('install_server() {')
    end = source.index('\n}\n\nMODE=start', begin) + 2
    source = source[:begin] + 'install_server() {\n    printf "SERVER-INSTALL"\n    printf " <%s>" "$@"\n    printf "\\n"\n    exit 0\n}' + source[end:]
    (path / 'start.sh').write_text(source)
    (path / '.env').write_text('HOST=127.0.0.1\n')
    (path / '.venv/bin').mkdir(parents=True)
    fake = path / '.venv/bin/python'
    fake.write_text('#!/bin/sh\ncase "$1" in\n-c) printf "Python fixture\\n" ;;\n-m) exit 0 ;;\n-) printf "fixture-hash\\n" ;;\n*) printf "LOCAL-LAUNCH\\n" ;;\nesac\n')
    fake.chmod(0o755)
    (path / 'frontend/dist').mkdir(parents=True)
    (path / 'frontend/dist/index.html').write_text('built')
    (path / 'frontend/dist/.rootdrive-build').write_text('fixture-hash\n')
    return path


def interactive(launcher, choice):
    master, slave = pty.openpty()
    process = subprocess.Popen(['sh', str(launcher / 'start.sh')], stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    output = b''
    sent = False
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if b'Choose [1]:' in output and not sent:
                    os.write(master, choice.encode() + b'\n')
                    sent = True
            if process.poll() is not None:
                break
        assert process.wait(timeout=2) == 0
        return output.decode()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


@pytest.mark.parametrize('choice', ['1', ''])
def test_start_menu_local_launch(launcher, choice):
    output = interactive(launcher, choice)
    assert 'LOCAL-LAUNCH' in output and 'SERVER-INSTALL' not in output


def test_start_menu_server_install(launcher):
    output = interactive(launcher, '2')
    assert 'SERVER-INSTALL' in output and 'LOCAL-LAUNCH' not in output


def test_start_menu_exit(launcher):
    output = interactive(launcher, '0')
    assert 'LOCAL-LAUNCH' not in output and 'SERVER-INSTALL' not in output


def test_start_flags_are_noninteractive_and_forward_arguments(launcher):
    launch = subprocess.run(['sh', launcher / 'start.sh', '--start'], capture_output=True, text=True, check=True)
    assert 'Choose [1]:' not in launch.stdout and 'LOCAL-LAUNCH' in launch.stdout
    install = subprocess.run(['sh', launcher / 'start.sh', '--server-install', '--data-dir', '/var/lib/Root Drive'], capture_output=True, text=True, check=True)
    assert '<--data-dir> </var/lib/Root Drive>' in install.stdout
    preparation = subprocess.run(['sh', launcher / 'start.sh', '--install-only'], capture_output=True, text=True, check=True)
    assert 'LOCAL-LAUNCH' not in preparation.stdout and 'Installation complete' in preparation.stdout


def test_server_installer_help_and_argument_errors():
    help_result = subprocess.run(['sh', PROJECT / 'start.sh', '--server-install', '--help'], capture_output=True, text=True)
    assert help_result.returncode == 0 and '--no-service' in help_result.stdout
    invalid = subprocess.run(['sh', PROJECT / 'start.sh', '--server-install', '--unknown'], capture_output=True, text=True)
    assert invalid.returncode == 2 and 'Unknown option' in invalid.stderr


def test_service_install_writes_unit_and_uses_systemctl(isolated_installer, monkeypatch):
    _, application, state, calls = isolated_installer
    def run(arguments, **kwargs):
        calls.append(list(arguments))
        return SimpleNamespace(returncode=3 if 'is-active' in arguments and 'restart' not in [item for call in calls[:-1] for item in call] else 0)
    monkeypatch.setattr(installer.subprocess, 'run', run)
    installer.install(application, state)
    text = installer.SYSTEMD_UNIT.read_text()
    assert 'User=rootdrive' in text
    assert ['systemctl', 'daemon-reload'] in calls
    assert ['systemctl', 'enable', 'rootdrive.service'] in calls
    assert ['systemctl', 'restart', 'rootdrive.service'] in calls
    assert 'start.sh' not in text


def test_bootstrap_uses_stub_packages_and_preserves_forwarded_paths(tmp_path):
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    commands = {
        'uname': '#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac\n',
        'id': '#!/bin/sh\necho 0\n',
        'apt-get': '#!/bin/sh\nprintf "PACKAGE"\nprintf " <%s>" "$@"\nprintf "\\n"\n',
        'python3': '#!/bin/sh\nif [ "$1" = -c ]; then exit 0; fi\nprintf "HELPER"\nprintf " <%s>" "$@"\nprintf "\\n"\n',
    }
    for name, source in commands.items():
        executable = binaries / name
        executable.write_text(source)
        executable.chmod(0o755)
    result = subprocess.run(['sh', PROJECT / 'start.sh', '--server-install', '--no-service', '--data-dir', str(tmp_path / 'data with spaces')], capture_output=True, text=True, check=True, env={**os.environ, 'PATH': str(binaries) + os.pathsep + os.defpath})
    assert 'PACKAGE <update>' in result.stdout
    assert 'PACKAGE <install> <-y>' in result.stdout
    assert f'<--data-dir> <{tmp_path / "data with spaces"}>' in result.stdout
    assert 'server_install.py>' in result.stdout


def test_readiness_requires_expected_application_and_active_service(monkeypatch):
    calls = []
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, method, path): calls.append((method, path))
        def getresponse(self): return SimpleNamespace(status=200, read=lambda limit: b'{"name":"RootDrive","status":"ok"}')
        def close(self): pass
    monkeypatch.setattr(installer.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(installer.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    installer.wait_for_service(('127.0.0.1', 8000))
    assert calls == [('GET', '/api/health')]


def test_busy_port_is_reported_without_stopping_other_processes(monkeypatch):
    closed = []
    monkeypatch.setattr(installer.socket, 'create_connection', lambda *args, **kwargs: SimpleNamespace(close=lambda: closed.append(True)))
    with pytest.raises(ValueError, match='already in use'):
        installer.check_port_free(('127.0.0.1', 8000))
    assert closed == [True]


def test_user_runner_is_resolved_before_using_restricted_build_path(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.shutil, 'which', lambda name: '/usr/sbin/runuser')
    monkeypatch.setattr(installer.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    installer.run_as_user(['sh', 'start.sh', '--install-only'], tmp_path, {'PATH': '/runtime/bin:/usr/bin:/bin'})
    arguments, options = calls[0]
    assert arguments[:4] == ['/usr/sbin/runuser', '-u', 'rootdrive', '--']
    assert options['env']['PATH'] == '/runtime/bin:/usr/bin:/bin'


def test_configuration_supports_unicode_and_spaces(tmp_path):
    from app.config import Settings
    state = tmp_path / 'Мои файлы'
    environment = tmp_path / '.env'
    environment.write_text(installer.new_environment(state))
    settings = Settings(_env_file=environment)
    assert settings.storage_path == state / 'storage'
    assert settings.database_path == state / 'data/rootdrive.db'


def test_existing_node_checks_run_as_the_service_user(tmp_path, monkeypatch):
    binaries = tmp_path / '.runtime/node/bin'
    binaries.mkdir(parents=True)
    (binaries / 'node').write_text('fixture')
    (binaries / 'npm').write_text('fixture')
    calls = []
    monkeypatch.setattr(installer, 'run_as_user', lambda args, *rest, **kwargs: calls.append((args, kwargs)))
    assert installer.ensure_node(tmp_path, tmp_path / 'state', SimpleNamespace(pw_uid=1001, pw_gid=1001)) == binaries
    assert len(calls) == 2 and calls[0][1]['quiet'] is True
    assert calls[1][0][1] == '--version'


def test_privilege_escalation_reenters_the_same_launcher_mode(tmp_path):
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    commands = {
        'uname': '#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac\n',
        'id': '#!/bin/sh\necho 1000\n',
        'sudo': '#!/bin/sh\nprintf "SUDO"\nprintf " <%s>" "$@"\nprintf "\\n"\n',
    }
    for name, source in commands.items():
        executable = binaries / name
        executable.write_text(source)
        executable.chmod(0o755)
    result = subprocess.run(['sh', PROJECT / 'start.sh', '--server-install', '--no-service', '--data-dir', str(tmp_path / 'data with spaces')], capture_output=True, text=True, check=True, env={**os.environ, 'PATH': str(binaries) + os.pathsep + os.defpath})
    assert f'SUDO <--> <sh> <{PROJECT / "start.sh"}> <--server-install> <--no-service>' in result.stdout
    assert f'<--data-dir> <{tmp_path / "data with spaces"}>' in result.stdout
    assert 'System dependencies' not in result.stdout
