from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
from fastapi import HTTPException
from .editors import editor_kind


def create_document(staged: Path, extension: str) -> None:
    with ZipFile(staged, 'w', compression=ZIP_DEFLATED) as document:
        if extension == '.docx':
            document.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            document.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            document.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t/></w:r></w:p><w:sectPr/></w:body></w:document>')
        else:
            media = 'application/vnd.oasis.opendocument.text'
            document.writestr('mimetype', media, compress_type=ZIP_STORED)
            document.writestr('META-INF/manifest.xml', '<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
            document.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.3"><office:body><office:text><text:p/></office:text></office:body></office:document-content>')


def create_file_contents(staged: Path, destination: Path) -> None:
    kind = editor_kind(destination)
    if kind not in {'text', 'document'}:
        raise HTTPException(415, 'Create a text file or a DOCX/ODT document')
    if kind == 'document':
        create_document(staged, destination.suffix.lower())
    else:
        staged.write_bytes(b'{}\n' if destination.suffix.lower() == '.json' else b'')
