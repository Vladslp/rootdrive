#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$PROJECT_DIR"
umask 077

MODE=start
case "${1:-}" in
    "") ;;
    --install-only) MODE=install ;;
    --help|-h)
        printf '%s\n' 'Usage: ./start.sh [--install-only]' 'Installs missing project dependencies, builds the frontend when needed, and starts RootDrive.' 'Requires Python 3.11+. Node.js and npm are needed only to build the frontend.' 'Stop the server with Ctrl+C or ./stop.sh.'
        exit 0
        ;;
    *) printf '%s\n' "Unknown option: $1" 'Usage: ./start.sh [--install-only]' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Too many arguments.' >&2
    exit 2
fi

ROOTDRIVE_COLOR=0
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ "${NO_COLOR+x}" != x ]; then
    ROOTDRIVE_COLOR=1
fi
export ROOTDRIVE_COLOR
if [ "$ROOTDRIVE_COLOR" -eq 1 ]; then
    RD_RESET=$(printf '\033[0m')
    RD_BOLD=$(printf '\033[1m')
    RD_BLUE=$(printf '\033[38;5;111m')
    RD_MUTED=$(printf '\033[38;5;245m')
    RD_GREEN=$(printf '\033[38;5;114m')
    RD_RED=$(printf '\033[38;5;210m')
else
    RD_RESET= RD_BOLD= RD_BLUE= RD_MUTED= RD_GREEN= RD_RED=
fi

stage() {
    printf '\n  %s%s%s  %s%s%s\n' "$RD_BLUE" "$1" "$RD_RESET" "$RD_BOLD" "$2" "$RD_RESET"
}
note() {
    printf '         %s%s%s\n' "$RD_MUTED" "$1" "$RD_RESET"
}
ready() {
    printf '\n  %s%s%s  %s\n\n' "$RD_GREEN" '✓' "$RD_RESET" "$1"
}

launcher_exit() {
    if [ "$1" -ne 0 ]; then
        printf '\n  %s%s%s  Setup stopped. Check the message above.\n\n' "$RD_RED" '✕' "$RD_RESET" >&2
    fi
}
trap 'launcher_exit $?' 0

printf '\n  %s%s  ┌───┐ ┌───┐%s\n'  "$RD_BLUE" "$RD_BOLD" "$RD_RESET"
printf '  %s%s  │ · │ │ · │%s   %s%sRootDrive%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET" "$RD_BOLD" "$RD_BLUE" "$RD_RESET"
printf '  %s%s  └─┬─┘ └─┬─┘%s   %sSetup & launch%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET" "$RD_MUTED" "$RD_RESET"
printf '  %s%s    ╰──┬──╯%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET"
printf '  %s%s       ╵%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET"
stage '[1/4]' 'Python environment'

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if ! "$VENV_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    if [ -e "$PROJECT_DIR/.venv" ] || [ -L "$PROJECT_DIR/.venv" ]; then
        printf '%s\n' 'The existing .venv is unavailable or uses Python older than 3.11.' 'Rename it and run ./start.sh again to create a fresh environment.' >&2
        exit 1
    fi
    PYTHON_BIN=
    for candidate in python3 python3.13 python3.12 python3.11 python3.14 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON_BIN=$(command -v "$candidate")
            break
        fi
    done
    if [ -z "$PYTHON_BIN" ]; then
        printf '%s\n' 'Python 3.11 or newer is required. Install it, then run ./start.sh again.' >&2
        exit 1
    fi
    note 'Creating a local virtual environment…'
    if ! "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"; then
        printf '%s\n' 'Could not create the virtual environment. On Debian/Ubuntu, install the python3-venv package for your Python version.' >&2
        exit 1
    fi
fi

dependencies_ready() {
    "$VENV_PYTHON" - <<'PY' >/dev/null 2>&1
import importlib
from importlib.metadata import version
from pathlib import Path
from packaging.requirements import Requirement

def verify(path):
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        if value.startswith('-r '):
            verify(path.parent / value[3:].strip())
            continue
        requirement = Requirement(value)
        if requirement.marker is None or requirement.marker.evaluate():
            if version(requirement.name) not in requirement.specifier:
                raise RuntimeError(requirement.name)

verify(Path('requirements.txt'))
for name in ['fastapi', 'uvicorn', 'sqlalchemy', 'pydantic_settings', 'argon2', 'multipart', 'PIL', 'pillow_heif', 'lxml', 'pypdf']:
    importlib.import_module(name)
PY
}

note "$("$VENV_PYTHON" -c 'import platform; print("Python " + platform.python_version())')"
stage '[2/4]' 'Backend dependencies'
if ! dependencies_ready || ! "$VENV_PYTHON" -m pip check >/dev/null 2>&1; then
    note 'Installing Python packages…'
    "$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements.txt
    if ! dependencies_ready; then
        printf '%s\n' 'Python dependencies could not be loaded. Check the installation output above.' >&2
        exit 1
    fi
    "$VENV_PYTHON" -m pip check
else
    note 'Already installed'
fi

if [ ! -e .env ] && [ ! -L .env ]; then
    cp .env.example .env
    note 'Created .env with local defaults'
fi

fingerprint() {
    "$VENV_PYTHON" - "$1" "${2:-}" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path('frontend')
if sys.argv[1] == 'packages':
    files = [root / 'package.json', root / 'package-lock.json']
else:
    files = [root / 'index.html', root / 'package.json', root / 'package-lock.json']
    files.extend(root.glob('*.config.*'))
    files.extend(root.glob('tsconfig*.json'))
    files.extend(root.glob('.env*'))
    for name in ['src', 'public']:
        files.extend(path for path in (root / name).rglob('*') if path.is_file() and not path.is_relative_to(root / 'public/assets/pdfjs'))
hash_value = hashlib.sha256(sys.argv[2].encode())
for path in sorted(set(files)):
    if path.is_file():
        hash_value.update(str(path.relative_to(root)).encode() + b'\0')
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                hash_value.update(chunk)
print(hash_value.hexdigest())
PY
}

stage '[3/4]' 'Web interface'
BUILD_HASH=$(fingerprint source)
BUILD_MARKER=frontend/dist/.rootdrive-build
SAVED_BUILD_HASH=
if [ -f "$BUILD_MARKER" ]; then
    SAVED_BUILD_HASH=$(cat "$BUILD_MARKER")
fi
if [ ! -f frontend/dist/index.html ] || [ "$BUILD_HASH" != "$SAVED_BUILD_HASH" ]; then
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        if [ -f frontend/dist/index.html ] && [ -z "$SAVED_BUILD_HASH" ]; then
            note 'Using the supplied frontend build'
        else
            printf '%s\n' 'Building the frontend requires Node.js 22.13+ and npm. Install them, then run ./start.sh again.' >&2
            exit 1
        fi
    else
        if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)'; then
            printf '%s\n' 'Please update Node.js to 22.13+ before building the frontend.' >&2
            exit 1
        fi
        NODE_PLATFORM=$(node -p 'process.platform + ":" + process.arch + ":" + process.versions.node.split(".")[0]')
        PACKAGE_HASH=$(fingerprint packages "$NODE_PLATFORM")
        PACKAGE_MARKER=frontend/node_modules/.rootdrive-dependencies
        SAVED_PACKAGE_HASH=
        if [ -f "$PACKAGE_MARKER" ]; then
            SAVED_PACKAGE_HASH=$(cat "$PACKAGE_MARKER")
        fi
        if [ ! -x frontend/node_modules/.bin/vite ] || [ ! -x frontend/node_modules/.bin/tsc ] || [ "$PACKAGE_HASH" != "$SAVED_PACKAGE_HASH" ]; then
            note 'Installing frontend packages…'
            npm --prefix frontend ci --no-audit --no-fund
            printf '%s\n' "$PACKAGE_HASH" > "$PACKAGE_MARKER"
        fi
        note 'Building the interface…'
        npm --prefix frontend run build
        printf '%s\n' "$BUILD_HASH" > "$BUILD_MARKER"
    fi
else
    note 'Build is up to date'
fi

if [ "$MODE" = install ]; then
    stage '[4/4]' 'Installation complete'
    ready 'Ready. Run ./start.sh to start your drive.'
    exit 0
fi

stage '[4/4]' 'Starting server'
STATUS=0
"$VENV_PYTHON" - <<'PY' || STATUS=$?
import http.client
import os
import json
import sys
sys.path.insert(0, 'backend')
from app.config import Settings

settings = Settings()
host = '127.0.0.1' if settings.host == '0.0.0.0' else '::1' if settings.host == '::' else settings.host
address = f'[{host}]' if ':' in host else host
url = f'http://{address}:{settings.port}'
colored = os.environ.get('ROOTDRIVE_COLOR') == '1'
blue = '\033[38;5;111m' if colored else ''
green = '\033[38;5;114m' if colored else ''
muted = '\033[38;5;245m' if colored else ''
reset = '\033[0m' if colored else ''
connection = http.client.HTTPConnection(host, settings.port, timeout=2)
try:
    connection.request('GET', '/api/health')
    response = connection.getresponse()
    payload = response.read(16384)
    try:
        existing = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        existing = {}
    if isinstance(existing, dict) and response.status == 200 and existing.get('name') == 'RootDrive' and existing.get('status') == 'ok':
        print(f'\n  {green}✓{reset}  RootDrive is already running\n\n     {blue}{url}{reset}\n', flush=True)
        sys.exit(10)
    print(f'Port {settings.port} is already used by another server. Change PORT in .env or stop that server.', file=sys.stderr)
    sys.exit(11)
except (OSError, http.client.HTTPException):
    print(f'\n     {blue}{url}{reset}\n\n     {muted}Ctrl+C or ./stop.sh  stop server{reset}\n', flush=True)
finally:
    connection.close()
PY
if [ "$STATUS" -eq 10 ]; then
    exit 0
fi
if [ "$STATUS" -ne 0 ]; then
    exit "$STATUS"
fi
exec "$VENV_PYTHON" "$PROJECT_DIR/run.py"
