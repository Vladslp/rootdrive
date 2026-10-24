from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from .config import ROOT, Settings
from .database import create_database
from .routers import auth, files, shares, uploads, workspace
from .services.filesystem import Filesystem
from .services.previews import Previews


class BodyLimit:
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > self.limit:
                raise HTTPException(413, 'Upload request exceeds the configured limit')
            return message

        await self.app(scope, limited_receive, send)


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    settings.prepare()
    engine, sessions = create_database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title='RootDrive', version='1.0.0', lifespan=lifespan)
    app.state.settings, app.state.db = settings, sessions
    app.state.fs = Filesystem(settings)
    app.state.previews = Previews(settings, app.state.fs)
    app.state.login_attempts = defaultdict(deque)
    app.add_middleware(BodyLimit, limit=settings.max_upload_size_mb * 1024 * 1024 * 20 + 1024 * 1024)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return JSONResponse({'error': {'message': str(error.detail)}}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({'error': {'message': 'Please check the supplied values', 'fields': [{'location': list(item['loc']), 'message': item['msg']} for item in error.errors()]}}, status_code=422)

    @app.exception_handler(OSError)
    async def filesystem_error(request, error):
        return JSONResponse({'error': {'message': 'Storage is unavailable, full, or not writable'}}, status_code=503)

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'error': {'message': 'Cross-origin request rejected'}}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'name': 'RootDrive'}

    app.include_router(auth.router)
    app.include_router(files.router)
    app.include_router(shares.router)
    app.include_router(uploads.router)
    app.include_router(workspace.router)
    dist = ROOT / 'frontend/dist'
    if dist.exists():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        def frontend(path: str):
            if path.startswith('api/'):
                raise HTTPException(404, 'Endpoint not found')
            return FileResponse(dist / 'index.html')
    return app
