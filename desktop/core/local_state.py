"""Small, atomic local state files for explicitly saved desktop features."""
import json
import os
from pathlib import Path
import tempfile

DATA_DIR = Path(__file__).resolve().parents[2] / '.mica-data'


class FileLease:
    """Process lifetime ownership, released by the OS even after a crash."""
    def __init__(self, path, *, label='Die gespeicherten Timer'):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open('a+b')
        try:
            if path.stat().st_size == 0:
                self.handle.write(b'0')
                self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError(label + ' werden bereits von einer anderen Mica-Instanz verwaltet.')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.handle.close()


def read_json(path, *, limit=262144):
    with Path(path).open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Gespeicherter Zustand ist zu groß.')
    return json.loads(data.decode('utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
