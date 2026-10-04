"""Check source consistency without importing MICA or touching runtime data."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "LICENSE", "SECURITY.md", "readme.md", "Start MICA.cmd",
    "install_and_start.ps1", "setup.py", "pytest.ini", "ruff.toml",
    "desktop/local_main.py", "desktop/start_mica.py",
    "backend/services/api/app.py", "backend/docker-compose.yml",
    "mica_shared/__init__.py", "docs/README.md",
)
LINK = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")


def check_repository(root: Path) -> tuple[list[str], int, int]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    errors = [f"Missing required file: {name}" for name in REQUIRED if not (root / name).is_file()]
    errors.extend(f"Unresolved root copy: {path.name}" for path in root.glob("* - Kopie*"))
    python_count = link_count = 0
    for name in names:
        path = root / name
        if " - Kopie" in path.name:
            errors.append(f"Copied source filename: {name}")
        # Gitlinks and intentionally removed optional files are not file inputs.
        if not path.is_file() or path.suffix not in {".py", ".md"}:
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            errors.append(f"Cannot read {name}: {error}")
            continue
        if path.suffix == ".py":
            python_count += 1
            try:
                ast.parse(source, filename=name)
            except SyntaxError as error:
                errors.append(f"Invalid Python: {name}:{error.lineno}: {error.msg}")
        else:
            source = re.sub(r"(```|~~~).*?\1", "", source, flags=re.DOTALL)
            for match in LINK.finditer(source):
                target = match[1].strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                link_count += 1
                if not (path.parent / unquote(parsed.path)).exists():
                    errors.append(f"Broken local link: {name} -> {target}")
    return errors, python_count, link_count


def main() -> int:
    try:
        errors, python_count, link_count = check_repository(ROOT)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Repository check failed: {error}")
        return 1
    for error in errors:
        print(error)
    print(f"Checked {python_count} Python files and {link_count} local documentation links; {len(errors)} errors.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
