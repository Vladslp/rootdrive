import hashlib
import os
from ..database import ApplicationSetting

DEFAULT_FOLDERS = ('Documents', 'Photos', 'Videos', 'Audio')


def initialize_workspace(fs, sessions):
    if not fs.settings.create_default_folders:
        return
    key = 'default_folders_v1:' + hashlib.sha256(str(fs.root).encode()).hexdigest()
    with fs.lock, sessions() as db:
        if db.get(ApplicationSetting, key) is not None:
            return
        descriptor = os.open(fs.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for name in DEFAULT_FOLDERS:
                try:
                    os.mkdir(name, dir_fd=descriptor)
                except FileExistsError:
                    pass
        finally:
            os.close(descriptor)
        db.add(ApplicationSetting(key=key, value='ready'))
        db.commit()
        fs.invalidate()
