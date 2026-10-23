# RootDrive

**Your files. Your hardware. Your space.**

RootDrive is a lightweight personal file server with a Python backend and a responsive React interface. Run it on an old laptop, desktop, mini PC, Linux server or Raspberry Pi. The built application runs through one HTTP port and needs no persistent Node process, Docker, cloud account, API key or external service.

Created as a university Python semester project. The implementation demonstrates a REST backend, safe filesystem operations and relational metadata persistence.

## Implemented features

- Browse folders in grid or list view; breadcrumbs and file selection.
- Multiple file uploads, drag and drop, progress and configurable per-file limits.
- Download, create folder, rename, move and delete to trash.
- Restore deleted items or permanently remove individual trash items.
- Case-insensitive filename search, optional recursive search and pagination.
- Sort by name, modification date, size or type.
- JPEG, PNG, WebP, GIF, HEIC, HEIF, AVIF and PDF previews.
- Cached photo thumbnails and file properties with expandable camera/lens EXIF metadata.
- Device capacity, free space, disk usage and RootDrive file totals.
- Optional login, multiple accounts, administrator-created users and logout.
- Optional expiring public download links and link revocation.
- Original illustrated icons, a RootDrive application mark and mobile navigation.

Finder `.DS_Store` metadata is hidden from file listings and file totals.

Nothing is uploaded to a third-party service. Runtime does not load fonts, scripts or images from a CDN. The initial workspace is empty; no example files are silently installed.

## Requirements

- Python 3.11 or newer.
- Node.js 20.19+ or 22.12+ and npm for developing/building the frontend.
- Linux or macOS; ARM64 and x86-64 are supported targets.
- A writable local disk with enough space for files, temporary uploads and trash.

The backend deliberately uses `O_NOFOLLOW`, available on Linux and macOS. Native Windows deployment is not currently supported; use WSL2. Any computer running a supported operating system can host RootDrive. Raspberry Pi is one option, not a requirement.

## Install

Run all commands from the project directory:

```bash
cd ~/Documents/rootdrive
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
npm --prefix frontend install
npm --prefix frontend run build
python run.py
```

Open <http://127.0.0.1:8000>. API documentation is at <http://127.0.0.1:8000/docs>.

`requirements.txt` declares the supported dependency ranges. `backend/requirements.lock.txt` captures the exact Python environment used for verification; use it with Python 3.12 for the closest reproduction. `frontend/package-lock.json` is the npm lockfile; use `npm --prefix frontend ci` for repeatable frontend installs.

## Stop the server

For a foreground `python run.py` process, press **Ctrl+C** in its terminal. For a background process, find the listening process with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, then send `kill PID` to that RootDrive process. Replace `8000` if you changed the port. For a systemd deployment, use `sudo systemctl stop rootdrive`.

## Development

Backend terminal:

```bash
source .venv/bin/activate
PYTHONPATH=backend uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Frontend terminal:

```bash
npm --prefix frontend run dev
```

Open the Vite URL printed in the terminal, normally <http://127.0.0.1:5173>. Vite proxies `/api` to the Python server. Restart the backend after changing `.env`.

## Production

```bash
npm --prefix frontend ci
npm --prefix frontend run build
source .venv/bin/activate
python run.py
```

FastAPI serves `frontend/dist` and `/api` on the same port. Node.js can be stopped after the build. Run **one application worker**: filesystem mutation locking is intentionally process-local. Use a regular service account, not root. A process manager such as systemd can keep the server running.

Example Linux systemd unit, with paths adjusted to your installation:

```ini
[Unit]
Description=RootDrive personal file storage
After=network.target

[Service]
User=rootdrive
WorkingDirectory=/opt/rootdrive
ExecStart=/opt/rootdrive/.venv/bin/python /opt/rootdrive/run.py
Restart=on-failure
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Save it as `/etc/systemd/system/rootdrive.service` and run `sudo systemctl enable --now rootdrive`. Create the service user and give it access to the project and storage first. This is an example, not an automatically installed service.

## Configuration

Copy `.env.example` to `.env`. Relative paths are resolved from the project directory. Real `.env` files, uploaded files and databases are ignored by Git.

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Address used by `python run.py` |
| `PORT` | `8000` | HTTP port |
| `STORAGE_PATH` | `./storage` | Browsable user files |
| `DATABASE_PATH` | `./data/rootdrive.db` | SQLite metadata |
| `INTERNAL_PATH` | `./data/internal` | Trash and temporary upload staging |
| `AUTH_ENABLED` | `false` | Require login |
| `ENABLE_PUBLIC_SHARES` | `false` | Enable anonymous file download links |
| `COOKIE_SECURE` | `false` | Restrict session cookies to HTTPS when true |
| `MAX_UPLOAD_SIZE_MB` | `2048` | Maximum size of each file |
| `SESSION_HOURS` | `24` | Session duration |
| `MAX_PREVIEW_PIXELS` | `50000000` | Maximum decoded photo size for thumbnails/previews |
| `PREVIEW_CACHE_SIZE_MB` | `512` | Derived JPEG preview cache limit |

Storage must not contain application code, the database, `.env` or the internal directories. Keep `STORAGE_PATH` and `INTERNAL_PATH` on the **same filesystem** for rename-based trash operations. For an external disk, use sibling paths such as `/mnt/drive/files` and `/mnt/drive/rootdrive-internal`. The database can remain on the host disk.

## Local network access

Set the following in `.env`, then restart:

```dotenv
HOST=0.0.0.0
```

Find the server's LAN address and open `http://SERVER_LAN_IP:8000` from another device on the same network. Allow the configured port in the server firewall. RootDrive does not configure routers, expose ports to the Internet or open firewall rules automatically.

On a trusted LAN, HTTP works with `COOKIE_SECURE=false`. For passwords and remote access, terminate HTTPS with a correctly configured reverse proxy and set `COOKIE_SECURE=true`. Use a VPN or properly secured proxy for access beyond your LAN. Do not forward the unauthenticated default service to the public Internet.

## Authentication

Authentication is disabled by default. The UI hides login and account controls in this mode. Account-creation endpoints remain protected and cannot be used to create an administrator.

Create the initial administrator with a hidden password prompt:

```bash
source .venv/bin/activate
python run.py create-admin --username admin
```

Then set `AUTH_ENABLED=true` and restart. Passwords must contain at least ten characters. Passwords are hashed with Argon2id. The CLI does not accept passwords as command-line arguments.

Administrators can list users and create member or administrator accounts in Settings → Users, or through `GET /api/auth/users` and `POST /api/auth/users`. There is no open registration. When authentication is off, Settings shows instructions for creating the first administrator through the CLI and enabling authentication. All signed-in users access **one shared workspace**. They do not have private directories. They can modify the same files and revoke workspace shares.

Sessions use random tokens in HttpOnly, SameSite=Strict cookies; only token hashes are stored in SQLite. The frontend keeps the CSRF token in memory and includes it on mutations. Session tokens are never stored in localStorage. Expired sessions are cleaned up on login. Login attempts are limited per client address in memory; a server restart resets that limit.

## Sharing

Set `ENABLE_PUBLIC_SHARES=true` to reveal sharing actions. Create a link from an individual file's menu. Choose an hour, a day, a week or no expiration. Anyone with the link can download that file without signing in.

Tokens contain 256 bits of randomness and only hashes are persisted. The full link appears once when created; copy it then. The Shared links screen lists and revokes links. Existing links follow API renames and moves. Moving a file or parent folder to trash revokes its links permanently; restoration does not reactivate them. Files modified outside RootDrive cannot be tracked automatically, so revoke old links before replacing shared paths externally.

## Uploads and storage

Uploads use FastAPI `UploadFile` multipart parsing. Data is copied in 1 MiB chunks to a staging directory, then written with exclusive creation to the destination. Conflicts return HTTP 409 rather than overwriting. A failed batch rolls back files created by that request and removes its staging files. Browser uploads send files individually, show transfer progress and report per-file errors.

The default limit is 2 GiB per file, with at most 20 files in an API request. The browser queues larger selections as individual requests. An aggregate request-body guard also caps incoming requests. Multipart parsing may spool an oversized file to disk before the per-file validation runs; allow sufficient temporary space and configure a reverse-proxy request limit where appropriate. Starlette may use the operating system temporary directory in addition to RootDrive staging.

A crash or power failure can leave partial staging files or an unfinished metadata transition. Files in `data/internal/uploads` can be inspected and removed while the server is stopped. Trash is never automatically emptied. Back up both storage and the data directory with the server stopped for a consistent snapshot.

Storage totals are scanned with streaming directory iteration and cached for 30 seconds. API file mutations invalidate the cache. RootDrive file size excludes trash; disk usage includes the OS, other applications, staging and trash.

## Photo previews and EXIF

Photo cards load lazy 640-pixel JPEG thumbnails. HEIC/HEIF and AVIF previews are converted to JPEG with a maximum 1920-pixel edge so browsers can display them. Downloads always return the original file. Pillow and pillow-heif run locally, with one conversion at a time, and respect the pixel limit. The first preview can take longer on slower hardware. Supported-platform wheels bundle the HEIF decoder; source installs may require libheif development packages.

Derived files live in `INTERNAL_PATH/previews`, outside browsable storage. Cache keys include the source path, modification time, change time and size. The oldest derived files are removed when the configured cache limit is exceeded. Original files and their EXIF are never changed.

Properties includes a collapsible EXIF section with available camera make/model, lens, ISO, exposure, aperture, focal length, capture time, software and other selected fields. Dimensions and values are read from the original; absent metadata is not invented. Public links still share the original file, including whatever metadata that original contains.

## Python architecture

```text
backend/app/
  config.py             Environment configuration and path separation
  main.py               Application factory, middleware, errors, static frontend
  database.py           SQLAlchemy models and SQLite setup
  schemas.py            Pydantic request validation
  cli.py                Server startup and administrator creation
  routers/
    files.py            Files, folders, trash, search and storage endpoints
    auth.py             Login, logout, sessions and administrator-created users
    shares.py           Share creation, revocation and public downloads
  services/
    filesystem.py       Path validation, listing, streaming downloads and statistics
    security.py         Argon2 verification, session lookup and CSRF enforcement
    previews.py         Bounded photo conversion and derived thumbnail cache
    metadata.py         Read-only EXIF extraction and display formatting
backend/tests/          Isolated API integration tests
frontend/src/           React, TypeScript, local API client and illustrated UI
frontend/public/assets/ Original locally hosted image assets
run.py                  Project entrypoint
```

Three Python technological areas for the university demonstration:

1. **Web backend and REST API.** FastAPI uses an application factory, dependency-based access checks, Pydantic input schemas and structured errors. Uvicorn runs the ASGI application. OpenAPI is generated at `/docs`.
2. **Filesystem operations and storage management.** `pathlib`, `os`, `stat`, `shutil`, `heapq` and chunked I/O implement isolation, bounded-memory listing, uploads, downloads, rename/move, trash and disk statistics. Symbolic links are excluded, path components are validated and downloads open with `O_NOFOLLOW`.
3. **SQLite database and persistence.** SQLAlchemy stores users, sessions, trash records and share metadata. Each request uses its own session. SQLite runs in WAL mode with foreign keys enabled and a busy timeout. File contents remain on disk instead of becoming database blobs.

File operations use a reentrant lock to coordinate requests in a single server process. Rename and trash metadata updates attempt filesystem rollback if the database commit fails. Filesystem changes and SQLite commits cannot be one atomic transaction across a power failure.

## API

All private endpoints require a session when authentication is enabled. State-changing requests additionally require `X-CSRF-Token`. `/api/auth/me` returns the current account, configuration flags and CSRF token for an existing authenticated session.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Health |
| GET | `/api/files` | Paginated folder listing |
| GET | `/api/search` | Search using `path`, `q`, `recursive` |
| POST | `/api/files/upload?path=...` | Multipart `files` upload |
| GET | `/api/files/download?path=...` | Attachment download |
| GET | `/api/files/preview?path=...` | Supported inline preview |
| GET | `/api/files/thumbnail?path=...` | Cached JPEG photo thumbnail |
| GET | `/api/files/metadata?path=...` | Image dimensions and camera/lens EXIF |
| POST | `/api/folders` | Create folder with `path`, `name` |
| PATCH | `/api/files/rename` | Rename with `path`, `name` |
| POST | `/api/files/move` | Move with `path`, `destination` |
| DELETE | `/api/files` | JSON `path`, move to trash |
| GET | `/api/trash` | Paginated trash records |
| POST | `/api/trash/restore` | JSON trash `id` |
| DELETE | `/api/trash` | JSON trash `id`, permanent removal |
| GET | `/api/storage/stats` | Cached file totals and disk usage |
| GET | `/api/auth/me` | Account and feature flags |
| POST | `/api/auth/login` | Login with `username`, `password` |
| POST | `/api/auth/logout` | Revoke current session |
| GET, POST | `/api/auth/users` | Administrator lists/creates accounts |
| GET, POST | `/api/shares` | List/create shares |
| DELETE | `/api/shares/{id}` | Revoke share |
| GET | `/api/public/{token}` | Anonymous shared-file download |

Listings accept `sort=name|size|type|modified`, `direction=asc|desc`, `offset` and `limit` (up to 200). They retain only the requested sorted window in memory, bounded by `offset + limit`; large directories still need a scan for sorting and totals. Errors use `{"error":{"message":"..."}}` with 400, 401, 403, 404, 409, 413, 415, 422 or 503 as appropriate.

## Tests

```bash
source .venv/bin/activate
pytest -q
npm --prefix frontend run build
```

Tests use temporary storage directories and temporary SQLite databases, never your workspace files. Coverage includes file lifecycle, conflicts, restoration, permanent deletion, unsafe names, traversal, symlink escapes, streaming upload limits, failed-batch cleanup, search/pagination, previews, stats, optional authentication, CSRF, administrator restrictions, public sharing, revocation/expiry and restart persistence.

## Raspberry Pi and older hardware

Use a 64-bit Linux distribution with Python 3.11+. Raspberry Pi OS 64-bit, Debian and Ubuntu are suitable examples. On Debian-based systems:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Install a supported Node.js version to build locally, or copy the project and a prebuilt `frontend/dist` from another machine and install only Python dependencies. No GPU is required. Store large files on a reliable SSD or external drive when possible. Ensure the temporary upload directory has enough disk space. Performance depends on disk and network speed; Raspberry Pi hardware has not been benchmarked in this project.

## Current limitations

- One shared workspace; no private per-user folders or granular permissions.
- One server worker. Locks do not coordinate separate processes.
- Designed for a trusted LAN with server-owned storage. Do not let untrusted local users mutate storage concurrently. Final download opens reject symlinks, but parent-path validation and mutations are not fully descriptor-relative; hostile external filesystem changes can create races.
- No resumable uploads, folder uploads, bulk selection actions or folder ZIP downloads.
- No video/audio playback, office-document conversion or OCR. Native image formats and PDFs preview directly; HEIC/HEIF and AVIF have derived JPEG previews.
- Downloads stream without implementing HTTP byte-range requests. Large PDF behavior depends on the browser; download is always available.
- Directory scanning, recursive search and initial storage stats can take time on very large collections. There is no background indexer.
- The move picker shows the first 200 entries in a folder, with folders sorted first.
- The first administrator is created through the CLI. Further accounts are managed in Settings by administrators. Settings does not edit server environment variables.
- No full activity history, synchronization client, versioning or automated backup.
- No antivirus scanning or content sanitization. Downloads are attachments; inline previews are limited to supported image formats and PDFs.
- Interrupted operations after a crash need administrator inspection. SQLite and filesystem changes are not power-loss atomic.
- Native Windows, real phone hardware, Raspberry Pi hardware and reverse-proxy deployments have not been verified.

## Planned improvements

Resumable uploads, indexed search for large libraries, file versioning, bulk actions, a paginated move picker, richer account administration, download ranges and stronger descriptor-relative filesystem operations. These are not exposed as unfinished controls in the interface.

## Design assets

The illustrated icons and application mark were created with ImageGen and are served locally. The RootDrive mark joins a storage drive with branching roots. The asset manifest in `frontend/public/assets/README.md` records generation and cleanup. Lucide provides the small action icons. Source files contain no comments or docstrings.
