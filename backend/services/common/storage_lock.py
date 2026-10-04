"""Process-shared reader/writer lock for backup maintenance, Linux and Windows."""
from __future__ import annotations

import os
import time
from pathlib import Path


class StorageBusy(RuntimeError):
    pass


class StorageLease:
    def __init__(self, root: Path, *, exclusive: bool = False, timeout: float = 3):
        root.mkdir(parents=True, exist_ok=True)
        self.handle = (root / '.maintenance.lock').open('a+b')
        self._overlap = None
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._lock(exclusive)
                break
            except (BlockingIOError, OSError) as error:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    raise StorageBusy('Daten werden verwendet oder wiederhergestellt; erneut versuchen.') from error
                time.sleep(0.05)

    def _lock(self, exclusive):
        if os.name != 'nt':
            import fcntl
            fcntl.flock(self.handle.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return
        import ctypes
        import msvcrt
        from ctypes import wintypes
        class OVERLAPPED(ctypes.Structure):
            _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                        ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]
        self._overlap = OVERLAPPED()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
        kernel.LockFileEx.restype = wintypes.BOOL
        flags = 1 | (2 if exclusive else 0)  # FAIL_IMMEDIATELY, optional EXCLUSIVE_LOCK
        if not kernel.LockFileEx(msvcrt.get_osfhandle(self.handle.fileno()), flags, 0, 1, 0,
                                 ctypes.byref(self._overlap)):
            raise OSError(ctypes.get_last_error(), 'Storage lock unavailable')

    def close(self):
        if self.handle.closed:
            return
        try:
            if os.name != 'nt':
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            else:
                import ctypes
                import msvcrt
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                               wintypes.DWORD, ctypes.c_void_p]
                kernel.UnlockFileEx(msvcrt.get_osfhandle(self.handle.fileno()), 0, 1, 0,
                                    ctypes.byref(self._overlap))
        finally:
            self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
