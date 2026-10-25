import hashlib
import os
import re
import shutil
import warnings
import zipfile
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from lxml import etree
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from fastapi import HTTPException

TEXT_LIMIT = 2 * 1024 * 1024
DOCUMENT_LIMIT = 32 * 1024 * 1024
PHOTO_LIMIT = 64 * 1024 * 1024
TEXT_EXTENSIONS = set('txt md markdown csv tsv json jsonl yaml yml toml ini cfg conf log xml html htm css scss js jsx ts tsx py sh bash zsh sql c h cpp hpp rs go java kt swift rb php vue svelte tex bib svg srt vtt'.split())
PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'}
WORD = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ODT = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def editor_kind(path):
    name = re.sub(r' \(edited(?: \d+)?\)(?=\.|$)', '', path.name)
    extension = Path(name).suffix.lower().lstrip('.')
    if extension in TEXT_EXTENSIONS or name in {'Dockerfile', 'Makefile', '.gitignore', '.env.example'}:
        return 'text'
    if extension in PHOTO_EXTENSIONS:
        return 'photo'
    if extension in {'docx', 'odt'}:
        return 'document'
    if extension == 'pdf':
        return 'pdf'
    raise HTTPException(415, 'This format is available for preview or download')


def copy_destination(fs, original: Path) -> Path:
    suffix = original.suffix
    stem = original.name[:-len(suffix)] if suffix else original.name
    stem = re.sub(r' \(edited(?: \d+)?\)$', '', stem)
    for number in range(1, 10001):
        marker = ' (edited)' if number == 1 else f' (edited {number})'
        budget = 240 - len((marker + suffix).encode('utf-8'))
        shortened = stem.encode('utf-8')[:budget].decode('utf-8', errors='ignore').rstrip() or 'file'
        candidate = original.parent / fs.name(shortened + marker + suffix)
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise HTTPException(409, 'Too many edited copies already exist for this filename')


def revision(info, path):
    value = f'{path}:{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_size}'
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def open_original(fs, value, expected=None):
    path = fs.path(value, allow_root=False)
    if not path.is_file():
        raise HTTPException(400, 'Choose a regular file')
    kind = editor_kind(path)
    limit = TEXT_LIMIT if kind == 'text' else PHOTO_LIMIT if kind == 'photo' else DOCUMENT_LIMIT
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if info.st_size > limit:
            raise HTTPException(413, f'The {kind} editor supports files up to {limit // (1024 * 1024)} MB')
        token = revision(info, value)
        if expected is not None and expected != token:
            raise HTTPException(409, 'This file changed. Close and reopen the editor before saving')
        yield path, source, kind, token
        if revision(path.stat(follow_symlinks=False), value) != token:
            raise HTTPException(409, 'This file changed while it was being read. Reopen the editor')


def read_text(source):
    raw = source.read(TEXT_LIMIT + 1)
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise HTTPException(415, 'The text editor requires UTF-8 text')
    if '\x00' in text:
        raise HTTPException(415, 'Binary files cannot be edited as text')
    return text, raw.startswith(b'\xef\xbb\xbf')


def photo_info(source, max_pixels):
    source.seek(0)
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            image = Image.open(source)
            if image.width * image.height > max_pixels:
                image.close()
                raise HTTPException(413, 'This image exceeds the pixel limit')
            if getattr(image, 'n_frames', 1) > 1:
                image.close()
                raise HTTPException(415, 'Animated images are available for preview; editing would remove frames')
            return image
        except (Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise HTTPException(413, 'This image exceeds the pixel limit')
        except (UnidentifiedImageError, ValueError, SyntaxError):
            raise HTTPException(415, 'This image cannot be edited')


class OfficeDocument:
    def __init__(self, source, extension):
        self.archive = zipfile.ZipFile(source)
        infos = self.archive.infolist()
        if len(infos) > 3000 or sum(item.file_size for item in infos) > 64 * 1024 * 1024:
            raise HTTPException(413, 'This document is too complex for the built-in editor')
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or any(item.flag_bits & 1 for item in infos):
            raise HTTPException(415, 'Encrypted or ambiguous documents cannot be edited')
        if any(name.lower().startswith('_xmlsignatures/') or name.lower().endswith('documentsignatures.xml') for name in names):
            raise HTTPException(415, 'Signed documents are available for download without editing')
        self.word = extension == '.docx'
        self.filename = 'word/document.xml' if self.word else 'content.xml'
        try:
            info = self.archive.getinfo(self.filename)
        except KeyError:
            raise HTTPException(415, 'Document content is missing')
        if info.file_size > 8 * 1024 * 1024:
            raise HTTPException(413, 'The document text is too large')
        raw = self.archive.read(info)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
        self.tree = etree.fromstring(raw, parser)
        if self.tree.getroottree().docinfo.doctype or any(isinstance(node, etree._Entity) for node in self.tree.iter()):
            raise HTTPException(415, 'Documents containing XML entities cannot be edited')
        self.paragraphs = self.tree.findall(f'.//{{{WORD}}}p') if self.word else list(self.tree.iter(f'{{{ODT}}}p', f'{{{ODT}}}h'))
        if len(self.paragraphs) > 3000:
            raise HTTPException(413, 'The document contains too many paragraphs')
        self.slots = [self.text_slots(node) for node in self.paragraphs]
        if sum(len(text) for slots, _ in self.slots for _, _, text in slots) > TEXT_LIMIT:
            raise HTTPException(413, 'The document text exceeds 2 MB')

    def text_slots(self, paragraph):
        if self.word:
            safe = {f'{{{WORD}}}{name}' for name in ('p', 'r', 't', 'tab', 'br', 'pPr', 'rPr')}
            editable = True
            for node in paragraph.iter():
                if node is paragraph:
                    continue
                if any(parent.tag in {f'{{{WORD}}}pPr', f'{{{WORD}}}rPr'} for parent in node.iterancestors() if parent is not paragraph):
                    continue
                if node.tag not in safe or (node.tag == f'{{{WORD}}}br' and node.get(f'{{{WORD}}}type', 'textWrapping') != 'textWrapping'):
                    editable = False
            slots = [(node, 'word', node.text or '' if node.tag == f'{{{WORD}}}t' else '\t' if node.tag == f'{{{WORD}}}tab' else '\n') for node in paragraph.iter(f'{{{WORD}}}t', f'{{{WORD}}}tab', f'{{{WORD}}}br')]
        else:
            safe = {f'{{{ODT}}}{name}' for name in ('p', 'h', 'span', 's', 'tab', 'line-break')}
            editable = all(node.tag in safe for node in paragraph.iter())
            slots = []

            def collect(node):
                if node.tag in {f'{{{ODT}}}s', f'{{{ODT}}}tab', f'{{{ODT}}}line-break'}:
                    amount = int(node.get(f'{{{ODT}}}c', '1'))
                    if not 1 <= amount <= 100000:
                        raise HTTPException(413, 'Document whitespace exceeds the editor limit')
                    slots.append((node, 'special', ' ' * amount if node.tag == f'{{{ODT}}}s' else '\t' if node.tag == f'{{{ODT}}}tab' else '\n'))
                    return
                if node.text:
                    slots.append((node, 'text', node.text))
                for child in node:
                    collect(child)
                    if child.tail:
                        slots.append((child, 'tail', child.tail))

            collect(paragraph)
        if not slots and editable:
            if self.word:
                run = etree.SubElement(paragraph, f'{{{WORD}}}r')
                node = etree.SubElement(run, f'{{{WORD}}}t')
            else:
                node = paragraph
            slots = [(node, 'word' if self.word else 'text', '')]
        return slots, editable

    def data(self):
        return [{'id': index, 'text': ''.join(text for _, _, text in slots), 'editable': editable, 'heading': self.paragraphs[index].tag == f'{{{ODT}}}h' or bool(self.paragraphs[index].xpath('./w:pPr/w:pStyle[starts-with(@w:val,"Heading")]', namespaces={'w': WORD}))} for index, (slots, editable) in enumerate(self.slots)]

    def update(self, changes):
        if len({item.id for item in changes}) != len(changes):
            raise HTTPException(422, 'Duplicate paragraph edits')
        for change in changes:
            if change.id < 0 or change.id >= len(self.slots):
                raise HTTPException(422, 'Paragraph no longer exists')
            slots, editable = self.slots[change.id]
            if not editable:
                raise HTTPException(422, 'This paragraph contains complex content and cannot be changed')
            old = ''.join(text for _, _, text in slots)
            if old == change.text:
                continue
            owners = [index for index, (_, _, text) in enumerate(slots) for _ in text]
            chunks = [''] * len(slots)
            if len(old) + len(change.text) > 200000:
                raise HTTPException(413, 'One paragraph exceeds the editor limit')
            for operation, a, b, c, d in SequenceMatcher(None, old, change.text, autojunk=True).get_opcodes():
                if operation == 'equal':
                    for position in range(a, b):
                        chunks[owners[position]] += old[position]
                elif operation in {'insert', 'replace'}:
                    owner = owners[min(a, len(owners) - 1)] if owners else 0
                    chunks[owner] += change.text[c:d]
            for (node, attribute, _), text in zip(slots, chunks):
                if self.word:
                    self.set_word_text(node, text)
                else:
                    self.set_odt_text(node, attribute, text)

    def set_word_text(self, node, text):
        chunks = re.split(r'(\n|\t)', text)
        node.tag = f'{{{WORD}}}t'
        node.attrib.clear()
        node.set(XML_SPACE, 'preserve')
        node.text = chunks[0]
        parent = node.getparent()
        position = parent.index(node) + 1
        for chunk in chunks[1:]:
            if not chunk:
                continue
            element = etree.Element(f'{{{WORD}}}' + ('br' if chunk == '\n' else 'tab' if chunk == '\t' else 't'))
            if chunk not in {'\n', '\t'}:
                element.text = chunk
                element.set(XML_SPACE, 'preserve')
            parent.insert(position, element)
            position += 1

    def set_odt_text(self, node, attribute, text):
        if attribute == 'special':
            node.tag = f'{{{ODT}}}span'
            node.attrib.clear()
            attribute = 'text'
        chunks = re.split(r'( +|\n|\t)', text)
        setattr(node, attribute, chunks[0])
        parent = node if attribute == 'text' else node.getparent()
        position = 0 if attribute == 'text' else parent.index(node) + 1
        previous = None
        for chunk in chunks[1:]:
            if not chunk:
                continue
            if chunk[0] == ' ' or chunk in {'\n', '\t'}:
                element = etree.Element(f'{{{ODT}}}' + ('s' if chunk[0] == ' ' else 'line-break' if chunk == '\n' else 'tab'))
                if chunk[0] == ' ' and len(chunk) > 1:
                    element.set(f'{{{ODT}}}c', str(len(chunk)))
                parent.insert(position, element)
                position += 1
                previous = element
            elif previous is not None:
                previous.tail = chunk

    def write(self, destination):
        content = etree.tostring(self.tree, xml_declaration=True, encoding='UTF-8', standalone=True if self.word else None)
        with zipfile.ZipFile(destination, 'w') as output:
            for item in self.archive.infolist():
                if item.filename == self.filename:
                    output.writestr(item, content)
                else:
                    with self.archive.open(item) as source, output.open(item, 'w') as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)

    def close(self):
        self.archive.close()


def pdf_reader(source):
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise HTTPException(415, 'Encrypted PDFs cannot be edited')
    if len(reader.pages) > 500:
        raise HTTPException(413, 'The PDF editor supports up to 500 pages')
    if '/AcroForm' in reader.root_object or '/Perms' in reader.root_object:
        raise HTTPException(415, 'PDF forms and signed documents are available for preview and download')
    if not reader.pages:
        raise HTTPException(415, 'The PDF has no pages')
    return reader


def edit_photo(source, staged, edits, max_pixels):
    with photo_info(source, max_pixels) as original:
        image = ImageOps.exif_transpose(original)
        exif = image.getexif()
        icc = image.info.get('icc_profile')
        if edits.rotation:
            image = image.rotate(-edits.rotation, expand=True)
        if edits.flip:
            image = ImageOps.mirror(image)
        left, top, right, bottom = edits.crop
        bounds = (round(left * image.width), round(top * image.height), round(right * image.width), round(bottom * image.height))
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise HTTPException(422, 'Crop area is too small')
        image = image.crop(bounds)
        if image.mode in {'P', 'LA'} or 'transparency' in image.info:
            image = image.convert('RGBA')
        alpha = image.getchannel('A') if 'A' in image.getbands() else None
        image = image.convert('RGB')
        if edits.brightness != 1:
            image = ImageEnhance.Brightness(image).enhance(edits.brightness)
        if edits.contrast != 1:
            image = ImageEnhance.Contrast(image).enhance(edits.contrast)
        if edits.saturation != 1:
            image = ImageEnhance.Color(image).enhance(edits.saturation)
        if alpha is not None:
            image.putalpha(alpha)
        exif[274] = 1
        exif[256], exif[257] = image.size
        if 34665 in exif:
            camera = exif.get_ifd(34665)
            camera[40962], camera[40963] = image.size
        output_format = original.format
        options = {'exif': exif.tobytes()}
        if icc:
            options['icc_profile'] = icc
        if output_format in {'JPEG', 'WEBP', 'AVIF', 'HEIF'}:
            options['quality'] = 95
        if output_format == 'JPEG':
            image = image.convert('RGB')
        image.save(staged, format=output_format, **options)
        image.close()


def edit_pdf(reader, staged, pages):
    if not pages or len({page.index for page in pages}) != len(pages):
        raise HTTPException(422, 'Keep at least one page; duplicate pages are not supported')
    if any(page.index >= len(reader.pages) for page in pages):
        raise HTTPException(422, 'Page no longer exists')
    writer = PdfWriter()
    writer.append(reader, pages=[page.index for page in pages], import_outline=True)
    for target, change in zip(writer.pages, pages):
        if change.rotation:
            target.rotate(change.rotation)
    if reader.metadata:
        writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
    writer.write(staged)
