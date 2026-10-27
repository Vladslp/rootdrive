import errno
import os
import shutil
import stat
import uuid
import zipfile
from fastapi import HTTPException


def write_zip(fs, sources, target, base=None):
    base = fs.root if base is None else base
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for source in sources:
            def members():
                yield source
                if source.is_dir():
                    yield from fs.walk(source, True)
            for member in members():
                fs.path(fs.relative(member), allow_root=False)
                name = member.relative_to(base).as_posix()
                if member.is_dir():
                    archive.writestr(name + '/', b'')
                else:
                    descriptor = os.open(member, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        os.close(descriptor)
                        raise HTTPException(409, 'A source file changed. Try again')
                    with os.fdopen(descriptor, 'rb') as original, archive.open(name, 'w', force_zip64=True) as output:
                        shutil.copyfileobj(original, output, 1024 * 1024)


def compress_folder(fs, value, name=None):
    with fs.lock:
        source = fs.path(value, allow_root=False)
        if not source.is_dir():
            raise HTTPException(400, 'Choose a folder to compress')
        name = name if name is not None else source.name.encode()[:236].decode('utf-8', errors='ignore') + '.zip'
        if not name.lower().endswith('.zip'):
            name += '.zip'
        destination = source.parent / fs.name(name)
        fs.path(fs.relative(destination), exists=False, allow_root=False)
        fs.free_destination(destination)
        staged = fs.settings.internal_path / 'uploads' / (uuid.uuid4().hex + '.zip')
        try:
            write_zip(fs, [source], staged, base=source.parent)
            fs.path(fs.relative(destination), exists=False, allow_root=False)
            try:
                os.link(staged, destination, follow_symlinks=False)
            except FileExistsError:
                raise HTTPException(409, 'A file or folder with this name already exists')
            except OSError as error:
                if error.errno == errno.EXDEV:
                    raise HTTPException(503, 'Storage and internal data must be on the same filesystem to create a ZIP')
                raise
            fs.invalidate()
            return fs.entry(destination)
        finally:
            staged.unlink(missing_ok=True)
