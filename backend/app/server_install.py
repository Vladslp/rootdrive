import argparse
import hashlib
import http.client
import json
import os
import platform
import pwd
import stat
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
SERVICE_USER = 'rootdrive'
NODE_BASE = 'https://nodejs.org/dist/latest-v24.x/'
SYSTEMD_UNIT = Path('/etc/systemd/system/rootdrive.service')


def checked_path(value):
    path = Path(value)
    if not path.is_absolute() or any(character in str(path) for character in '\n\r"\\%$'):
        raise ValueError('Installation paths must be absolute and cannot contain quotes, backslashes, newlines, % or $')
    return path.resolve()


def unit_text(application):
    return f'''[Unit]
Description=RootDrive personal cloud
After=network.target

[Service]
Type=simple
User={SERVICE_USER}
WorkingDirectory="{application}"
ExecStart="{application}/.venv/bin/python" "{application}/run.py" serve
Restart=on-failure
RestartSec=3
TimeoutStopSec=90
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

[Install]
WantedBy=multi-user.target
'''


def select_node_archive(manifest, architecture):
    matches = []
    pattern = re.compile(rf'([a-fA-F0-9]{{64}})\s+(node-v24\.\d+\.\d+-linux-{re.escape(architecture)}\.tar\.gz)$')
    for line in manifest.splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            matches.append(match.groups())
    if len(matches) != 1:
        raise ValueError('The official Node.js checksum list did not contain exactly one supported archive')
    return matches[0]


def download(url, destination, expected=None):
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={'User-Agent': 'RootDrive installer'})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as output:
        if not response.url.startswith('https://nodejs.org/'):
            raise ValueError('Unexpected Node.js download destination')
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > 256 * 1024 * 1024:
                raise ValueError('Node.js download exceeded its expected size limit')
            digest.update(block)
            output.write(block)
    if expected and digest.hexdigest() != expected.lower():
        raise ValueError('Node.js archive checksum verification failed')


def new_environment(state):
    return '\n'.join([
        'HOST=127.0.0.1', 'PORT=8000',
        'STORAGE_PATH=' + json.dumps(str(state / 'storage'), ensure_ascii=False),
        'DATABASE_PATH=' + json.dumps(str(state / 'data/rootdrive.db'), ensure_ascii=False),
        'INTERNAL_PATH=' + json.dumps(str(state / 'data/internal'), ensure_ascii=False),
        'AUTH_ENABLED=false', 'ENABLE_PUBLIC_SHARES=false',
        'COOKIE_SECURE=false', 'MAX_UPLOAD_SIZE_MB=2048',
    ]) + '\n'


def copy_application(source, destination):
    if source == destination:
        return
    excluded = shutil.ignore_patterns('.git', '.venv', '.runtime', '__pycache__', 'node_modules', 'dist', '.DS_Store', '.env*', '.npmrc', '.pypirc', '*.pyc', '.pytest_cache', '*.tsbuildinfo')
    for name in ['backend', 'frontend']:
        shutil.copytree(source / name, destination / name, dirs_exist_ok=True, ignore=excluded)
    for name in ['start.sh', 'stop.sh', 'run.py', 'requirements.txt', '.env.example', 'README.md']:
        shutil.copy2(source / name, destination / name)


def run_as_user(arguments, application, environment=None, quiet=False):
    runner = shutil.which('runuser') or '/usr/sbin/runuser'
    output = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL} if quiet else {}
    subprocess.run([runner, '-u', SERVICE_USER, '--', *map(str, arguments)], cwd=application, env=environment, check=True, **output)


def own_tree(path, user):
    os.chown(path, user.pw_uid, user.pw_gid)
    for directory, folders, files in os.walk(path, followlinks=False):
        for name in folders + files:
            os.chown(Path(directory) / name, user.pw_uid, user.pw_gid, follow_symlinks=False)


def secure_application(application, user):
    for directory, folders, files in os.walk(application, followlinks=False):
        os.chown(directory, 0, user.pw_gid)
        os.chmod(directory, 0o750)
        for name in files + folders:
            path = Path(directory) / name
            if path.is_symlink():
                os.chown(path, 0, user.pw_gid, follow_symlinks=False)
                continue
            mode = path.stat().st_mode
            os.chown(path, 0, user.pw_gid)
            os.chmod(path, 0o750 if stat.S_ISDIR(mode) or mode & 0o111 else 0o640)


def ensure_node(application, state, user):
    local = application / '.runtime/node/bin/node'
    candidates = [str(local), shutil.which('node')]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            run_as_user([candidate, '-e', 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)'], application, quiet=True)
            if (Path(candidate).parent / 'npm').exists():
                run_as_user([candidate, '--version'], application)
                return Path(candidate).parent
        except (OSError, subprocess.CalledProcessError):
            continue
    architecture = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if not architecture:
        raise ValueError('Automatic Node.js installation supports x86_64 and ARM64')
    runtime = application / '.runtime'
    if runtime.is_symlink():
        raise ValueError('The runtime directory must not be a symbolic link')
    runtime.mkdir(exist_ok=True)
    os.chown(runtime, user.pw_uid, user.pw_gid)
    with tempfile.TemporaryDirectory(prefix='node-install-', dir=runtime) as temporary:
        stage = Path(temporary)
        os.chown(stage, user.pw_uid, user.pw_gid)
        manifest = stage / 'SHASUMS256.txt'
        download(NODE_BASE + 'SHASUMS256.txt', manifest)
        checksum, filename = select_node_archive(manifest.read_text(), architecture)
        archive = stage / filename
        download(NODE_BASE + filename, archive, checksum)
        os.chmod(archive, 0o644)
        unpacked = stage / 'node'
        unpacked.mkdir()
        os.chown(unpacked, user.pw_uid, user.pw_gid)
        run_as_user(['tar', '-xzf', archive, '--strip-components=1', '-C', unpacked], application)
        run_as_user([unpacked / 'bin/node', '--version'], application)
        target = runtime / 'node'
        if target.is_symlink():
            raise ValueError('The Node.js installation path must not be a symbolic link')
        if target.exists():
            shutil.rmtree(target)
        unpacked.rename(target)
    return application / '.runtime/node/bin'


def service_address(application):
    code = "import json,sys;sys.path.insert(0,'backend');from app.config import Settings;s=Settings();print(json.dumps({'host':s.host,'port':s.port}))"
    runner = shutil.which('runuser') or '/usr/sbin/runuser'
    result = subprocess.run([runner, '-u', SERVICE_USER, '--', str(application / '.venv/bin/python'), '-c', code], cwd=application, capture_output=True, text=True, check=True)
    settings = json.loads(result.stdout)
    host = '127.0.0.1' if settings['host'] == '0.0.0.0' else '::1' if settings['host'] == '::' else settings['host']
    return host, int(settings['port'])


def check_port_free(address):
    try:
        connection = socket.create_connection(address, timeout=1)
    except OSError:
        return
    connection.close()
    raise ValueError(f'Port {address[1]} is already in use. Stop the existing server or change PORT in the installed .env, then run the installer again')


def wait_for_service(address):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection(*address, timeout=1)
        try:
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            payload = json.loads(response.read(16384))
            active = subprocess.run(['systemctl', 'is-active', '--quiet', 'rootdrive.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if active and response.status == 200 and isinstance(payload, dict) and payload.get('name') == 'RootDrive' and payload.get('status') == 'ok':
                return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(.3)
    subprocess.run(['systemctl', 'stop', 'rootdrive.service'], check=False)
    raise ValueError('The service did not become ready. Read sudo journalctl -u rootdrive -n 50, fix the reported error and rerun the installer')


def install(application, state, service=True):
    application, state = checked_path(application), checked_path(state)
    if application == Path('/') or state == Path('/') or state == application or state.is_relative_to(application) or application.is_relative_to(state):
        raise ValueError('Application and data directories must be separate, non-root paths')
    if application != SOURCE and (application.is_relative_to(SOURCE) or SOURCE.is_relative_to(application)):
        raise ValueError('The installation directory must be separate from the source checkout')
    marker = application / '.rootdrive-server.json'
    state_marker = state / '.rootdrive-state'
    if application.exists() and not marker.is_file() and any(application.iterdir()):
        raise ValueError('Choose an empty application directory outside the source checkout')
    if state.exists() and any(state.iterdir()) and not state_marker.is_file():
        raise ValueError('The data directory is not managed by RootDrive; choose an empty directory')
    if marker.is_file():
        installed = json.loads(marker.read_text())
        if installed.get('state') != str(state) or installed.get('application') != str(application):
            raise ValueError('Existing application/data paths do not match; data migration must be performed explicitly')
    unit = SYSTEMD_UNIT
    if service and unit.exists() and not marker.is_file():
        raise ValueError('An existing rootdrive.service is not managed by this installer')
    if service and subprocess.run(['systemctl', 'is-active', '--quiet', 'rootdrive.service']).returncode == 0:
        subprocess.run(['systemctl', 'stop', 'rootdrive.service'], check=True)
    print('\n  [2/5] Application and storage\n', flush=True)
    state.mkdir(parents=True, exist_ok=True)
    try:
        user = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        subprocess.run(['useradd', '--system', '--user-group', '--home-dir', str(state), '--no-create-home', '--shell', '/usr/sbin/nologin', SERVICE_USER], check=True)
        user = pwd.getpwnam(SERVICE_USER)
    if user.pw_uid == 0:
        raise ValueError('RootDrive must run as an unprivileged service user')
    application.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'application': str(application), 'state': str(state), 'service_user': SERVICE_USER}) + '\n')
    state_marker.write_text('rootdrive\n')
    copy_application(SOURCE, application)
    legacy_launcher = application / 'server-install.sh'
    if legacy_launcher.is_file() or legacy_launcher.is_symlink():
        legacy_launcher.unlink()
    environment_file = application / '.env'
    if environment_file.is_symlink():
        raise ValueError('The installed .env must not be a symbolic link')
    if not environment_file.exists():
        environment_file.write_text(new_environment(state))
    os.chmod(environment_file, 0o600)
    for name in ['storage', 'data', 'data/internal']:
        (state / name).mkdir(parents=True, exist_ok=True)
    own_tree(application, user)
    own_tree(state, user)
    for name in ['start.sh', 'stop.sh']:
        os.chmod(application / name, 0o755)
    os.chmod(marker, 0o644)
    print('\n  [3/5] Node.js build runtime\n', flush=True)
    node_bin = ensure_node(application, state, user)
    environment = dict(os.environ)
    environment['PATH'] = os.pathsep.join([str(node_bin), str(Path(sys.executable).parent), os.defpath])
    print('\n  [4/5] Dependencies and frontend\n', flush=True)
    run_as_user(['sh', application / 'start.sh', '--install-only'], application, environment)
    secure_application(application, user)
    print('\n  [5/5] Server service\n', flush=True)
    if service:
        address = service_address(application)
        check_port_free(address)
        content = unit_text(application)
        with tempfile.NamedTemporaryFile(mode='w', dir=unit.parent, prefix='.rootdrive-', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        try:
            os.chmod(temporary, 0o644)
            temporary.replace(unit)
        finally:
            temporary.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'rootdrive.service'], check=True)
        subprocess.run(['systemctl', 'restart', 'rootdrive.service'], check=True)
        wait_for_service(address)
    print(f'\n  RootDrive installed\n\n  Application  {application}\n  Data         {state}\n  Settings     {environment_file}\n', flush=True)
    if service:
        print('  Start / stop  sudo systemctl start|stop rootdrive\n  Logs          sudo journalctl -u rootdrive -f\n', flush=True)
    else:
        print(f'  Run as {SERVICE_USER}: {application}/.venv/bin/python {application}/run.py serve\n', flush=True)
    print('  Default address: http://127.0.0.1:8000\n  Existing settings are preserved. Configure HOST in .env for LAN access.\n', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Install RootDrive as a Linux server')
    parser.add_argument('--install-dir', default='/opt/rootdrive')
    parser.add_argument('--data-dir', default='/var/lib/rootdrive')
    parser.add_argument('--no-service', action='store_true')
    arguments = parser.parse_args()
    if platform.system() != 'Linux' or os.geteuid() != 0:
        parser.error('Run start.sh --server-install on Linux with administrator access')
    try:
        install(arguments.install_dir, arguments.data_dir, not arguments.no_service)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'\n  Installation stopped: {error}\n  Configuration and stored files are not automatically deleted.\n', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
