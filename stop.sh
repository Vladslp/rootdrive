#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$PROJECT_DIR"

case "${1:-}" in
    "") ;;
    --help|-h)
        printf '%s\n' 'Usage: ./stop.sh' 'Gracefully stops RootDrive started with ./start.sh or python run.py.' 'Run as the same operating-system user as the server.'
        exit 0
        ;;
    *) printf '%s\n' "Unknown option: $1" 'Usage: ./stop.sh' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Too many arguments.' >&2
    exit 2
fi

RD_RESET= RD_BOLD= RD_BLUE= RD_MUTED= RD_GREEN= RD_RED=
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ "${NO_COLOR+x}" != x ]; then
    RD_RESET=$(printf '\033[0m')
    RD_BOLD=$(printf '\033[1m')
    RD_BLUE=$(printf '\033[38;5;111m')
    RD_MUTED=$(printf '\033[38;5;245m')
    RD_GREEN=$(printf '\033[38;5;114m')
    RD_RED=$(printf '\033[38;5;210m')
fi

printf '\n  %s%s  ┌───┐ ┌───┐%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET"
printf '  %s%s  │ · │ │ · │%s   %s%sRootDrive%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET" "$RD_BOLD" "$RD_BLUE" "$RD_RESET"
printf '  %s%s  └─┬─┘ └─┬─┘%s   %sStop server%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET" "$RD_MUTED" "$RD_RESET"
printf '  %s%s    ╰──┬──╯%s\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET"
printf '  %s%s       ╵%s\n\n' "$RD_BLUE" "$RD_BOLD" "$RD_RESET"

STOP_PYTHON=
for candidate in "$PROJECT_DIR/.venv/bin/python" python3 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        STOP_PYTHON=$candidate
        break
    fi
done
if [ -z "$STOP_PYTHON" ]; then
    printf '  %s✕%s  Python 3.11+ is required. You can also stop the server with Ctrl+C.\n\n' "$RD_RED" "$RD_RESET" >&2
    exit 1
fi

if ! STOP_RESULT=$("$STOP_PYTHON" "$PROJECT_DIR/backend/app/control.py" stop); then
    printf '  %s✕%s  Could not stop RootDrive. Check the message above.\n\n' "$RD_RED" "$RD_RESET" >&2
    exit 1
fi
case "$STOP_RESULT" in
    stopped) printf '  %s✓%s  RootDrive stopped.\n\n' "$RD_GREEN" "$RD_RESET" ;;
    already-stopped) printf '  %s✓%s  RootDrive is already stopped.\n\n' "$RD_GREEN" "$RD_RESET" ;;
    stopping) printf '  %s…%s  RootDrive is finishing active requests. Shutdown is in progress.\n\n' "$RD_BLUE" "$RD_RESET" ;;
    *) printf '  %s✕%s  Unexpected shutdown response.\n\n' "$RD_RED" "$RD_RESET" >&2; exit 1 ;;
esac
