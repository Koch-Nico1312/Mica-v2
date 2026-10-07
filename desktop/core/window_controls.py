"""Bounded, read-only labels from a single explicitly selected window."""
import json
import os
from pathlib import Path
import subprocess


def read_window_controls(target, *, run=subprocess.run):
    if os.name != 'nt':
        return {'text': '', 'status': 'unsupported'}
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        output = run([str(powershell), '-NoProfile', '-NonInteractive', '-File',
            str(Path(__file__).with_name('window_controls.ps1')), '-WindowHandle', str(target['hwnd']),
            '-ProcessId', str(target['pid'])], capture_output=True, timeout=6, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if output.returncode or len(output.stdout) > 100000:
            raise ValueError('Kein lesbarer Fensterbaum.')
        data = json.loads(output.stdout)
        if data.get('status') != 'read' or not isinstance(data.get('controls'), list):
            raise ValueError('Diese Anwendung stellt keine Bedienelemente bereit.')
        lines = []
        for item in data['controls'][:200]:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('type'), str):
                raise ValueError('Ungültige Fensterauskunft.')
            state = {'on': ' (eingeschaltet)', 'off': ' (ausgeschaltet)', 'indeterminate': ' (unbestimmt)'}.get(item.get('checked'), '')
            if item.get('selected') is True:
                state += ' (ausgewählt)'
            lines.append(item['type'][:40] + ': ' + item['name'][:500] + state + (' (deaktiviert)' if not item.get('enabled') else ''))
        return {'text': '\n'.join(lines)[:12000], 'status': 'read', 'truncated': bool(data.get('truncated'))}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'text': '', 'status': 'unsupported'}
