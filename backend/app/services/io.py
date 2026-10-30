import os
import stat
from contextlib import contextmanager
from fastapi import HTTPException


@contextmanager
def open_regular(fs, value):
    with fs.lock:
        path = fs.path(value, allow_root=False)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise HTTPException(400, 'Choose a regular file')
    with os.fdopen(descriptor, 'rb') as source:
        yield path, source
