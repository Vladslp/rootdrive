import errno
import fcntl
import hashlib
import os
import signal
import socket
import stat
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

CONTROL_BASE = Path('/tmp')


def control_paths(project=None):
    root = Path(project) if project else Path(__file__).resolve().parents[2]
    info = root.stat()
    identifier = hashlib.sha256(f'{info.st_dev}:{info.st_ino}'.encode()).hexdigest()[:32]
    directory = CONTROL_BASE / f'rootdrive-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise RuntimeError('RootDrive control directory must be private and owned by your user')
    return directory / (identifier + '.sock'), directory / (identifier + '.lock')


def request_control(command, project=None):
    address, _ = control_paths(project)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        try:
            connection.connect(str(address))
            connection.sendall(('ROOTDRIVE/1 ' + command + '\n').encode())
            response = connection.recv(128).decode('ascii').strip()
        except OSError as error:
            if error.errno in {errno.ENOENT, errno.ECONNREFUSED, errno.ECONNRESET, errno.EPIPE}:
                return None
            raise
        if not response:
            return None
        if response not in {'ROOTDRIVE/1 running', 'ROOTDRIVE/1 stopping'}:
            raise RuntimeError('Unrecognized RootDrive control response')
        return response.rsplit(' ', 1)[-1]


@contextmanager
def server_control(project=None):
    address, lock_path = control_paths(project)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        os.close(descriptor)
        raise RuntimeError('Unsafe RootDrive control lock')
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise RuntimeError('RootDrive is already running for this project')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    finished = threading.Event()
    worker = None
    bound = False
    try:
        if address.exists() or address.is_symlink():
            metadata = address.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise RuntimeError('Unsafe RootDrive control socket')
            address.unlink()
        listener.bind(str(address))
        bound = True
        os.chmod(address, 0o600)
        listener.listen(4)
        listener.settimeout(0.25)

        def serve_requests():
            stopping = False
            while not finished.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with connection:
                    connection.settimeout(1)
                    try:
                        request = connection.recv(64)
                        if request not in {b'ROOTDRIVE/1 PING\n', b'ROOTDRIVE/1 STOP\n'}:
                            continue
                        should_stop = request == b'ROOTDRIVE/1 STOP\n' and not stopping
                        stopping = stopping or should_stop
                        connection.sendall(b'ROOTDRIVE/1 stopping\n' if stopping else b'ROOTDRIVE/1 running\n')
                        if should_stop:
                            os.kill(os.getpid(), signal.SIGTERM)
                    except OSError:
                        continue

        worker = threading.Thread(target=serve_requests, name='rootdrive-control', daemon=True)
        worker.start()
        yield
    finally:
        finished.set()
        listener.close()
        if worker:
            worker.join(timeout=2)
        if bound:
            address.unlink(missing_ok=True)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def stop_server():
    status = request_control('STOP')
    if status is None:
        return 'already-stopped'
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if request_control('PING') is None:
            return 'stopped'
    return 'stopping'


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'stop':
        raise SystemExit('Usage: python backend/app/control.py stop')
    try:
        print(stop_server())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
