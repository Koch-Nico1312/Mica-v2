"""Bounded, read-only folder inventory; links and reparse points are skipped."""
import heapq
import os
from pathlib import Path
import stat
import threading
import time


def analyze_folder(path, *, cancelled=None, max_entries=50000, max_seconds=30):
    if type(max_entries) is not int or not 1 <= max_entries <= 100000:
        raise ValueError('Ungültige Dateigrenze.')
    if not isinstance(max_seconds, (int, float)) or not 1 <= max_seconds <= 120:
        raise ValueError('Ungültiges Zeitbudget.')
    if str(path).startswith('\\\\'):
        raise ValueError('Bitte einen lokalen Ordner auswählen, keine Netzwerkfreigabe.')
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Bitte einen vorhandenen Ordner auswählen.')
    cancelled = cancelled or threading.Event()
    started = time.monotonic()
    pending, largest = [(root, 0)], []
    entries = files = directories = total = skipped = errors = 0
    reason = 'finished'
    while pending:
        directory, depth = pending.pop()
        if cancelled.is_set():
            reason = 'cancelled'
            break
        if time.monotonic() - started >= max_seconds:
            reason = 'time_limit'
            break
        try:
            with os.scandir(directory) as children:
                for entry in children:
                    if cancelled.is_set():
                        reason = 'cancelled'
                        break
                    if entries >= max_entries or time.monotonic() - started >= max_seconds:
                        reason = 'entry_limit' if entries >= max_entries else 'time_limit'
                        break
                    entries += 1
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
                            skipped += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth >= 64:
                                errors += 1
                            else:
                                directories += 1
                                pending.append((Path(entry.path), depth + 1))
                        elif stat.S_ISREG(info.st_mode):
                            files += 1
                            total += info.st_size
                            item = (info.st_size, str(Path(entry.path).relative_to(root)))
                            if len(largest) < 20:
                                heapq.heappush(largest, item)
                            elif item > largest[0]:
                                heapq.heapreplace(largest, item)
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
        if reason != 'finished':
            break
    return {'root': str(root), 'files': files, 'directories': directories, 'bytes': total,
            'skipped_links': skipped, 'errors': errors, 'reason': reason,
            'complete': reason == 'finished' and errors == 0,
            'largest': [{'path': path, 'bytes': size} for size, path in sorted(largest, reverse=True)]}


def size_text(size):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if size < 1024 or unit == 'TiB':
            return f'{size:.1f} {unit}'
        size /= 1024
