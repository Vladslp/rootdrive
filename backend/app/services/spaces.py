import re
import uuid
from threading import RLock
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from ..database import Space, SpaceMember, User, create_database
from .bootstrap import initialize_workspace
from .filesystem import Filesystem
from .previews import Previews
from .security import current_session

GLOBAL_PATHS = ('/api/auth/', '/api/spaces', '/api/settings', '/api/health')
READ_POSTS = {'/api/studio/preview', '/api/discovery/duplicates', '/api/files/archive'}


class SpaceRegistry:
    def __init__(self, app):
        self.app = app
        self.lock = RLock()
        self.contexts = {}
        self.engines = []
        self.legacy = SimpleNamespace(id='shared', fs=app.state.fs, db=app.state.db, previews=app.state.previews, settings=app.state.settings)

    def identity(self, request):
        if not self.app.state.settings.auth_enabled:
            return None
        with self.app.state.db() as db:
            session = current_session(request, db)
            user = db.get(User, session.user_id) if session else None
            return user.id if user else None

    def describe(self, db, identifier, user_id):
        if identifier == 'shared':
            return {'id': 'shared', 'name': 'Shared workspace', 'kind': 'legacy', 'role': 'editor', 'owner': False}
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise HTTPException(404, 'Workspace not found')
        space = db.get(Space, identifier)
        member = db.get(SpaceMember, (identifier, user_id)) if space and user_id else None
        if not space or (space.owner_id != user_id and (space.kind == 'personal' or not member)):
            raise HTTPException(403, 'You no longer have access to this workspace')
        return {'id': space.id, 'name': space.name, 'kind': space.kind, 'role': 'editor' if space.owner_id == user_id else member.role, 'owner': space.owner_id == user_id}

    def selected(self, request, user_id):
        if not self.app.state.settings.auth_enabled or not user_id:
            return self.describe(None, 'shared', None)
        with self.app.state.db() as db:
            return self.describe(db, request.cookies.get('rootdrive_space', 'shared'), user_id)

    def personal(self, user_id):
        with self.lock, self.app.state.db() as db:
            space = db.scalar(select(Space).where(Space.personal_key == str(user_id)))
            if space is None:
                space = Space(id=uuid.uuid4().hex, name='Personal', kind='personal', owner_id=user_id, personal_key=str(user_id))
                db.add(space)
                db.commit()
            return space.id

    def context(self, identifier):
        if identifier == 'shared':
            return self.legacy
        with self.lock:
            if identifier in self.contexts:
                context = self.contexts[identifier]
                context.settings.max_upload_size_mb = self.app.state.settings.max_upload_size_mb
                return context
            base = self.app.state.settings.internal_path / 'spaces' / identifier
            for path in (base.parent, base, base / 'files', base / 'internal', base / 'metadata.db'):
                if path.is_symlink():
                    raise HTTPException(503, 'Workspace storage is unavailable')
            settings = self.app.state.settings.model_copy(update={'storage_path': base / 'files', 'internal_path': base / 'internal', 'database_path': base / 'metadata.db'})
            settings.prepare()
            engine, database = create_database(settings.database_path)
            filesystem = Filesystem(settings)
            initialize_workspace(filesystem, database)
            context = SimpleNamespace(id=identifier, settings=settings, fs=filesystem, db=database, previews=Previews(settings, filesystem))
            self.engines.append(engine)
            self.contexts[identifier] = context
            return context

    def resolve(self, request):
        path = request.url.path
        request.state.workspace = self.legacy
        if path.startswith('/api/public/'):
            identifier = request.query_params.get('space', 'shared')
            if identifier != 'shared':
                if not self.app.state.settings.auth_enabled or not re.fullmatch('[0-9a-f]{32}', identifier):
                    raise HTTPException(404, 'This link is unavailable')
                with self.app.state.db() as db:
                    if db.get(Space, identifier) is None:
                        raise HTTPException(404, 'This link is unavailable')
                request.state.workspace = self.context(identifier)
            return
        if not path.startswith('/api/') or path.startswith(GLOBAL_PATHS):
            return
        user_id = self.identity(request)
        space = self.selected(request, user_id)
        expected = request.headers.get('X-RootDrive-Space') or request.query_params.get('workspace')
        if expected and expected != space['id']:
            raise HTTPException(409, 'Workspace changed in another tab. Reload before continuing')
        if space['role'] == 'reader' and request.method not in {'GET', 'HEAD', 'OPTIONS'} and path not in READ_POSTS:
            raise HTTPException(403, 'This workspace is read-only')
        request.state.workspace = self.context(space['id'])

    def close(self):
        for engine in self.engines:
            engine.dispose()
