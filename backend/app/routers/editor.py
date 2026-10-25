import uuid
import zipfile
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf.errors import PdfReadError
from ..services.security import require_access
from ..services.workspace import install_file
from ..services.editors import DOCUMENT_LIMIT, PHOTO_LIMIT, TEXT_LIMIT, OfficeDocument, copy_destination, edit_pdf, edit_photo, open_original, pdf_reader, photo_info, read_text, revision

router = APIRouter(prefix='/api/editor', dependencies=[Depends(require_access)])


class ParagraphEdit(BaseModel):
    id: int = Field(ge=0, le=2999)
    text: str = Field(max_length=100000)


class PDFPage(BaseModel):
    index: int = Field(ge=0, le=499)
    rotation: Literal[0, 90, 180, 270] = 0


class PhotoEdits(BaseModel):
    rotation: Literal[0, 90, 180, 270] = 0
    flip: bool = False
    crop: tuple[float, float, float, float] = (0, 0, 1, 1)
    brightness: float = Field(default=1, ge=0.2, le=2)
    contrast: float = Field(default=1, ge=0.2, le=2)
    saturation: float = Field(default=1, ge=0, le=2)

    @model_validator(mode='after')
    def valid_crop(self):
        left, top, right, bottom = self.crop
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError('Choose a crop area inside the image')
        return self


class SaveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(max_length=4096)
    revision: str = Field(min_length=64, max_length=64)
    kind: Literal['text', 'photo', 'document', 'pdf']
    text: str | None = Field(default=None, max_length=TEXT_LIMIT)
    photo: PhotoEdits | None = None
    paragraphs: list[ParagraphEdit] | None = Field(default=None, max_length=3000)
    pages: list[PDFPage] | None = Field(default=None, min_length=1, max_length=500)


def source_data(fs, original, source, kind, token):
    result = {'kind': kind, 'revision': token, 'format': original.suffix.lower().lstrip('.')}
    if kind == 'text':
        result['text'], _ = read_text(source)
        result['encoding'] = 'UTF-8'
    elif kind == 'photo':
        with photo_info(source, fs.settings.max_preview_pixels) as image:
            result['width'], result['height'] = image.size
    elif kind == 'document':
        document = OfficeDocument(source, original.suffix.lower())
        try:
            result['paragraphs'] = document.data()
        finally:
            document.close()
    else:
        result['pages'] = len(pdf_reader(source).pages)
    return result


def editor_data(fs, path):
    with open_original(fs, path) as (original, source, kind, token):
        return source_data(fs, original, source, kind, token)


@router.get('')
def get_editor(request: Request, path: str):
    fs = request.app.state.fs
    try:
        with fs.lock, request.app.state.previews.lock:
            return editor_data(fs, path)
    except (zipfile.BadZipFile, etree.XMLSyntaxError, PdfReadError, ValueError, KeyError):
        raise HTTPException(415, 'This file is damaged or uses an unsupported document format')


@router.get('/image')
def image_reference(request: Request, path: str):
    return request.app.state.previews.response(path)


@router.post('')
def save_editor(body: SaveInput, request: Request):
    fs = request.app.state.fs
    staged = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
    try:
        with fs.lock, request.app.state.previews.lock, request.app.state.db() as db:
            with open_original(fs, body.path, body.revision) as (original, source, kind, token):
                if kind != body.kind:
                    raise HTTPException(422, 'The editor does not match this file type')
                if kind == 'text':
                    if body.text is None:
                        raise HTTPException(422, 'Text is required')
                    old, bom = read_text(source)
                    text = body.text.replace('\r\n', '\n')
                    if '\x00' in text:
                        raise HTTPException(422, 'Text cannot contain binary null bytes')
                    if '\r\n' in old and old.count('\n') == old.count('\r\n'):
                        text = text.replace('\n', '\r\n')
                    encoded = (b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8')
                    if len(encoded) > TEXT_LIMIT:
                        raise HTTPException(413, 'Text exceeds the 2 MB editor limit')
                    staged.write_bytes(encoded)
                elif kind == 'photo':
                    if body.photo is None:
                        raise HTTPException(422, 'Photo adjustments are required')
                    edit_photo(source, staged, body.photo, fs.settings.max_preview_pixels)
                elif kind == 'document':
                    if body.paragraphs is None:
                        raise HTTPException(422, 'Paragraph edits are required')
                    if sum(len(item.text.encode('utf-8')) for item in body.paragraphs) > TEXT_LIMIT:
                        raise HTTPException(413, 'Document text exceeds the 2 MB editor limit')
                    document = OfficeDocument(source, original.suffix.lower())
                    try:
                        document.update(body.paragraphs)
                        document.write(staged)
                    finally:
                        document.close()
                else:
                    if body.pages is None:
                        raise HTTPException(422, 'Page edits are required')
                    edit_pdf(pdf_reader(source), staged, body.pages)
                editor_limit = TEXT_LIMIT if kind == 'text' else PHOTO_LIMIT if kind == 'photo' else DOCUMENT_LIMIT
                if staged.stat().st_size > editor_limit:
                    raise HTTPException(413, 'The resulting file exceeds the editor size limit')
                if staged.stat().st_size > fs.settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, 'The saved file exceeds the upload limit')
            with staged.open('rb') as candidate:
                result = source_data(fs, original, candidate, kind, token)
            if revision(original.stat(follow_symlinks=False), body.path) != token:
                raise HTTPException(409, 'This file changed. Reopen the editor before saving')
            destination = copy_destination(fs, original)
            result['entry'] = install_file(fs, db, staged, destination)
            result['revision'] = revision(destination.stat(follow_symlinks=False), fs.relative(destination))
            return result
    except (zipfile.BadZipFile, etree.XMLSyntaxError, PdfReadError, ValueError, KeyError):
        raise HTTPException(415, 'This file is damaged or uses an unsupported document format')
    finally:
        staged.unlink(missing_ok=True)
