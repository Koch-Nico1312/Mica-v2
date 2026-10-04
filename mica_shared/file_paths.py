"""File action addressing without importing either execution runtime."""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any, Callable


def user_directory(name: str) -> Path:
    if platform.system() == 'Linux':
        variable = 'XDG_DOWNLOAD_DIR' if name == 'Downloads' else f'XDG_{name.upper()}_DIR'
        configured = os.environ.get(variable, '')
        if configured and Path(configured).exists():
            return Path(configured)
    return Path.home() / name


def resolve_path(raw: str, *, directory: Callable[[str], Path] | None = None) -> Path:
    shortcuts = {name.lower(): (directory or user_directory)(name) for name in
                 ('Desktop', 'Downloads', 'Documents', 'Pictures', 'Music', 'Videos')}
    shortcuts['home'] = Path.home()
    raw = raw.strip().strip('"').strip("'")
    if raw.lower() in shortcuts:
        return shortcuts[raw.lower()]
    head, separator, rest = raw.replace('\\', '/').partition('/')
    if separator and head.lower() in shortcuts:
        return shortcuts[head.lower()] / rest.strip('/')
    return Path(raw).expanduser()


def file_action_paths(
    params: dict[str, Any], *, resolver: Callable[[str], Path] = resolve_path,
    desktop: Callable[[], Path] | None = None,
) -> list[Path]:
    """Use the handler's aliases, defaults and destination-directory semantics."""
    operation = str(params.get('action', params.get('mode', ''))).strip().lower()
    if operation == 'undo_change':
        return []
    path = (desktop or (lambda: user_directory('Desktop')))() if operation == 'organize_desktop' else resolver(str(params.get('path', 'desktop')))
    name = str(params.get('name', ''))
    target = path / name if name else path
    result = [target]
    if operation in {'move', 'copy'} and params.get('destination'):
        destination = resolver(str(params['destination']))
        result.append(destination / target.name if destination.is_dir() else destination)
    elif operation == 'rename' and params.get('new_name'):
        result.append(target.parent / str(params['new_name']))
    return [item.expanduser() for item in result]
