import hmac
import os
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from ..database import UploadJob
from ..schemas import UploadInput
from ..services.security import require_access
from ..services.workspace import install_file, owner_key

router = APIRouter(prefix='/api/uploads')
CHUNK_SIZE = 4 * 1024 * 1024


def upload_info(job):
    return {'id': job.id, 'path': job.path, 'name': job.path.rsplit('/', 1)[-1], 'size': job.size, 'received': job.received, 'last_modified': job.last_modified, 'status': job.status, 'overwrite': bool(job.overwrite), 'source_name': job.source_name}


def find_job(db, identifier, owner, active=True):
    job = db.get(UploadJob, identifier)
    if job is None or job.owner != owner:
        raise HTTPException(404, 'Upload not found')
    if active and job.status != 'open':
        raise HTTPException(409, 'This upload is no longer active')
    return job


def stage_path(fs, identifier):
    return fs.settings.internal_path / 'uploads' / identifier


def validate_target(fs, path):
    target = fs.path(path, exists=False, allow_root=False)
    for parent in target.parents:
        if parent == fs.root:
            break
        if parent.exists() and not parent.is_dir():
            raise HTTPException(409, 'A file blocks the destination folder')
    return target


@router.get('')
def list_uploads(request: Request, user=Depends(require_access)):
    with request.state.workspace.db() as db:
        jobs = db.scalars(select(UploadJob).where(UploadJob.owner == owner_key(user), UploadJob.status == 'open').order_by(UploadJob.created_at))
        return {'items': [upload_info(job) for job in jobs]}


@router.post('', status_code=201)
def start_upload(body: UploadInput, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    if body.size > fs.settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(413, 'File exceeds the configured upload limit')
    with fs.lock, request.state.workspace.db() as db:
        base = fs.path(body.path)
        if not base.is_dir():
            raise HTTPException(400, 'Destination must be a folder')
        fs.path(body.relative_path, exists=False, allow_root=False)
        path = '/'.join(filter(None, [body.path, body.relative_path]))
        source_name = fs.name(body.source_name) if body.source_name else body.relative_path.rsplit('/', 1)[-1]
        target = validate_target(fs, path)
        if target.exists() and (not body.overwrite or not target.is_file()):
            raise HTTPException(409, 'A file or folder with this name already exists')
        owner = owner_key(user)
        count = db.scalar(select(func.count()).select_from(UploadJob).where(UploadJob.owner == owner, UploadJob.status == 'open'))
        if count >= 1000:
            raise HTTPException(429, 'Cancel unfinished uploads before starting more')
        info = target.stat() if target.exists() else None
        job = UploadJob(id=uuid.uuid4().hex, owner=owner, path=path, size=body.size, last_modified=body.last_modified, source_name=source_name, overwrite=int(info is not None and body.overwrite), original_mtime=str(info.st_mtime_ns) if info else None, original_size=info.st_size if info else None)
        stage = stage_path(fs, job.id)
        stage.touch(exist_ok=False)
        try:
            db.add(job)
            db.commit()
        except BaseException:
            stage.unlink(missing_ok=True)
            raise
        return upload_info(job)


@router.get('/{identifier}')
def get_upload(identifier: str, request: Request, user=Depends(require_access)):
    with request.state.workspace.fs.lock, request.state.workspace.db() as db:
        return upload_info(find_job(db, identifier, owner_key(user), active=False))


async def read_bounded(request, limit):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(413, 'Upload chunk is too large')
    return content


@router.put('/{identifier}')
async def append_upload(identifier: str, request: Request, offset: int = Query(ge=0), user=Depends(require_access)):
    content = await read_bounded(request, CHUNK_SIZE)
    if not content:
        raise HTTPException(400, 'Empty upload chunk')

    def write_chunk():
        fs = request.state.workspace.fs
        with fs.lock, request.state.workspace.db() as db:
            job = find_job(db, identifier, owner_key(user))
            if job.size > fs.settings.max_upload_size_mb * 1024 * 1024:
                raise HTTPException(413, 'File exceeds the current upload limit')
            if offset != job.received:
                raise HTTPException(409, 'Upload offset changed. Refresh upload status and resume')
            if job.received + len(content) > job.size:
                raise HTTPException(413, 'Chunk exceeds the declared file size')
            stage = stage_path(fs, identifier)
            if not stage.is_file() or stage.stat().st_size < job.received:
                raise HTTPException(409, 'Upload data is unavailable. Start this upload again')
            previous = job.received
            try:
                with stage.open('r+b') as output:
                    output.truncate(previous)
                    output.seek(previous)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                job.received += len(content)
                job.updated_at = time.time()
                db.commit()
            except BaseException:
                db.rollback()
                with stage.open('r+b') as output:
                    output.truncate(previous)
                raise
            return upload_info(job)

    return await run_in_threadpool(write_chunk)


@router.post('/{identifier}/verify')
async def verify_upload(identifier: str, request: Request, user=Depends(require_access)):
    content = await read_bounded(request, 65536)

    def verify():
        fs = request.state.workspace.fs
        with fs.lock, request.state.workspace.db() as db:
            job = find_job(db, identifier, owner_key(user))
            expected_length = min(job.received, 65536)
            if len(content) != expected_length:
                raise HTTPException(409, 'Select the original file to resume')
            with stage_path(fs, identifier).open('rb') as handle:
                prefix = handle.read(expected_length)
            if not hmac.compare_digest(prefix, bytes(content)):
                raise HTTPException(409, 'Selected file differs from this upload')
            return upload_info(job)

    return await run_in_threadpool(verify)


@router.post('/{identifier}/complete')
def complete_upload(identifier: str, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        job = find_job(db, identifier, owner_key(user), active=False)
        if job.status == 'completed':
            return fs.entry(fs.path(job.path))
        if job.size > fs.settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(413, 'File exceeds the current upload limit')
        if job.status != 'open' or job.received != job.size:
            raise HTTPException(409, 'Upload is incomplete')
        target = validate_target(fs, job.path)
        stage = stage_path(fs, identifier)
        if not stage.is_file() or stage.stat().st_size != job.size:
            raise HTTPException(409, 'Upload data is incomplete')
        job.status = 'completed'
        job.updated_at = time.time()
        return install_file(fs, db, stage, target, bool(job.overwrite), job.original_mtime, job.original_size)


@router.delete('/{identifier}')
def cancel_upload(identifier: str, request: Request, user=Depends(require_access)):
    fs = request.state.workspace.fs
    with fs.lock, request.state.workspace.db() as db:
        job = find_job(db, identifier, owner_key(user), active=False)
        if job.status == 'completed':
            raise HTTPException(409, 'Upload already completed')
        stage_path(fs, identifier).unlink(missing_ok=True)
        job.status = 'cancelled'
        db.commit()
        return {'ok': True}
