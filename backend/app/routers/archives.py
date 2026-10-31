import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ..services.archive_reader import archive_listing, extract_archive, open_archive
from ..services.security import require_access
from ..services.transfers import copy_paths

router = APIRouter(prefix='/api', dependencies=[Depends(require_access)])


class CopyInput(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)
    destination: str = Field(default='', max_length=4096)


class ExtractInput(BaseModel):
    path: str = Field(max_length=4096)
    destination: str = Field(default='', max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    members: list[str] | None = Field(default=None, min_length=1, max_length=10000)


@router.post('/files/copy', status_code=201)
def copy_files(body: CopyInput, request: Request):
    return copy_paths(request.state.workspace.fs, body.paths, body.destination)


@router.get('/archives')
def browse_archive(request: Request, path: str, prefix: str = '', offset: int = Query(0, ge=0, le=10000), limit: int = Query(100, ge=1, le=200)):
    return archive_listing(request.state.workspace.fs, path, prefix, offset, limit)


@router.post('/archives/extract', status_code=201)
def unpack_archive(body: ExtractInput, request: Request):
    return extract_archive(request.state.workspace.fs, body.path, body.destination, body.name, body.members)


@router.get('/archives/member')
def archive_member(request: Request, path: str, member: str):
    manager = open_archive(request.state.workspace.fs, path)
    archive, members = manager.__enter__()
    try:
        info = members.get(member)
        if info is None or info.is_dir():
            raise HTTPException(404, 'Archive file not found')
        stream = archive.open(info)
    except BaseException:
        manager.__exit__(None, None, None)
        raise

    def chunks():
        try:
            while block := stream.read(256 * 1024):
                yield block
        finally:
            stream.close()
            manager.__exit__(None, None, None)

    name = PurePosixPath(member).name
    return StreamingResponse(chunks(), media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream', headers={'Content-Length': str(info.file_size), 'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name), 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "sandbox; default-src 'none'"})
