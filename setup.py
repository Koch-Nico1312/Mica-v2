"""Manual dependency helper; the Windows installer is install_and_start.ps1."""

import subprocess
import sys
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    print("Installing requirements...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
        cwd=ROOT, check=True,
    )

    print("Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], cwd=ROOT, check=True)

    if platform.system() == "Windows":
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            postinstall = Path(sys.prefix) / "Scripts" / "pywin32_postinstall.py"
            print(
                "\n⚠️  pywin32 did not install correctly — desktop shortcut creation "
                "will fall back to a slower method that may not work on this machine.\n"
                "    Try fixing it manually with:\n"
                f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
                f'    "{sys.executable}" "{postinstall}" -install\n'
            )

    print("\n✅ Setup complete! Run 'python desktop/local_main.py' to start MICA.")


if __name__ == "__main__":
    main()

