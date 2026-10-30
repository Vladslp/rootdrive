import os
import shutil
import uuid
from pathlib import Path
from fastapi import HTTPException
from .io import open_regular
from .workspace import normalize_paths


def available_name(fs, directory, original, suffix='copy'):
    stem, extension = Path(original).stem, Path(original).suffix
    for index in range(1, 10000):
        tail = f' ({suffix}{" " + str(index) if index > 1 else ""}){extension}'
        name = stem.encode()[:240 - len(tail.encode())].decode('utf-8', errors='ignore') + tail
        target = directory / fs.name(name)
        if not target.exists() and not target.is_symlink():
            return target
    raise HTTPException(409, 'Choose another destination name')


def publish_directory(stage, destination):
    try:
        destination.mkdir()
    except FileExistsError:
        raise HTTPException(409, 'A file or folder with this name already exists')
    try:
        for current, directories, files in os.walk(stage):
            relative = Path(current).relative_to(stage)
            for name in directories:
                (destination / relative / name).mkdir()
            for name in files:
                os.link(Path(current) / name, destination / relative / name, follow_symlinks=False)
    except BaseException:
        shutil.rmtree(destination)
        raise


def copy_paths(fs, values, destination):
    with fs.lock:
        parent = fs.path(destination)
        if not parent.is_dir():
            raise HTTPException(400, 'Choose a destination folder')
        sources = normalize_paths(fs, values)
        stage = fs.settings.internal_path / 'uploads' / uuid.uuid4().hex
        stage.mkdir()
        installed = []
        count = 0
        try:
            for index, source in enumerate(sources):
                if source.is_dir() and parent.is_relative_to(source):
                    raise HTTPException(400, 'Cannot copy a folder inside itself')
                target = parent / source.name
                if target.exists() or target.is_symlink():
                    target = available_name(fs, parent, source.name)
                temporary = stage / str(index)
                if source.is_dir():
                    temporary.mkdir()
                    candidates = fs.walk(source, True)
                else:
                    candidates = [source]
                for item in candidates:
                    count += 1
                    if count > 10000:
                        raise HTTPException(413, 'Copy up to 10000 items at once')
                    current = fs.path(fs.relative(item), allow_root=False)
                    output = temporary / current.relative_to(source) if source.is_dir() else temporary
                    if current.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                    else:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with open_regular(fs, fs.relative(current)) as (_, handle), output.open('xb') as saved:
                            shutil.copyfileobj(handle, saved, 1024 * 1024)
                            metadata = os.fstat(handle.fileno())
                        os.utime(output, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                if source.is_dir():
                    publish_directory(temporary, target)
                else:
                    try:
                        os.link(temporary, target, follow_symlinks=False)
                    except FileExistsError:
                        raise HTTPException(409, 'Destination changed. Try again')
                installed.append(target)
            fs.invalidate()
            return {'items': [fs.entry(path) for path in installed]}
        except BaseException:
            for target in reversed(installed):
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
            fs.invalidate()
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
