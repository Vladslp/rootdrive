#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$PROJECT_DIR"
umask 077

NEED_SERVICE=yes
validate_arguments() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --help|-h)
                printf '%s\n' 'Usage: ./server-install.sh [--install-dir PATH] [--data-dir PATH] [--no-service]' 'Installs Linux dependencies, builds RootDrive and enables a systemd service.' 'Defaults: /opt/rootdrive, /var/lib/rootdrive, service user rootdrive.' 'Existing installed configuration and data are preserved. Source workspace data is not migrated.' 'Use --no-service on Linux systems without systemd.'
                exit 0
                ;;
            --no-service) NEED_SERVICE=no; shift ;;
            --install-dir|--data-dir)
                if [ "$#" -lt 2 ] || [ -z "$2" ]; then printf 'Missing value for %s\n' "$1" >&2; exit 2; fi
                shift 2
                ;;
            *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
        esac
    done
}
validate_arguments "$@"

if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'Server installation requires Linux. Use ./start.sh --start for a local launch on this system.' >&2
    exit 1
fi
case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ;;
    *) printf '%s\n' 'Automatic installation supports 64-bit x86 and ARM Linux. Use a 64-bit OS on Raspberry Pi.' >&2; exit 1 ;;
esac
if [ "$NEED_SERVICE" = yes ] && { ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; }; then
    printf '%s\n' 'systemd is not running. Use --no-service to install without a system service.' >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        printf '%s\n' 'Administrator access is required. Run this script as root or install sudo.' >&2
        exit 1
    fi
    printf '%s\n' 'Administrator access is needed to install system packages and the service.'
    exec sudo -- sh "$PROJECT_DIR/server-install.sh" "$@"
fi

printf '\n  RootDrive  /  Server setup\n\n  [1/5] System dependencies\n\n'
if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip python3-dev build-essential pkg-config libheif-dev libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev ca-certificates tar util-linux passwd
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make pkgconf-pkg-config libheif-devel libjpeg-turbo-devel zlib-devel libxml2-devel libxslt-devel ca-certificates tar util-linux shadow-utils
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm python python-pip base-devel pkgconf libheif libjpeg-turbo zlib libxml2 libxslt ca-certificates tar util-linux shadow
else
    printf '%s\n' 'Automatic dependency installation supports apt, dnf and pacman. Install Python 3.11+, venv, pip, tar and runuser manually on this distribution.' >&2
    exit 1
fi

INSTALL_PYTHON=
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys,venv,ensurepip; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
        INSTALL_PYTHON=$(command -v "$candidate")
        break
    fi
done
if [ -z "$INSTALL_PYTHON" ]; then
    printf '%s\n' 'Python 3.11+ with venv is required. Use Debian 12+, Ubuntu 24.04+ or Raspberry Pi OS 64-bit Bookworm or newer.' >&2
    exit 1
fi
exec "$INSTALL_PYTHON" "$PROJECT_DIR/backend/app/server_install.py" "$@"
