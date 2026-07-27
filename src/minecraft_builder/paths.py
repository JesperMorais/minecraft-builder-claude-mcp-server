"""Cross-platform path resolution and file-manager helpers.

Kept separate from ``server.py`` so the platform-specific branching can be
unit-tested by monkeypatching ``platform.system`` and ``Path.home`` without
standing up an MCP server.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

# raw shortcut (lower-cased) -> (XDG user-dirs key, default folder name)
_SHORTCUTS = {
    "desktop": ("DESKTOP", "Desktop"),
    "my desktop": ("DESKTOP", "Desktop"),
    "documents": ("DOCUMENTS", "Documents"),
    "my documents": ("DOCUMENTS", "Documents"),
    "downloads": ("DOWNLOAD", "Downloads"),
    "download": ("DOWNLOAD", "Downloads"),
}


def _linux_xdg_dir(xdg_key: str) -> Optional[Path]:
    """Read a configured XDG user directory from ~/.config/user-dirs.dirs.

    Returns None if the file is missing/unreadable or the key is absent, so the
    caller can fall back to the conventional ``~/<Folder>`` location.
    """
    config = Path.home() / ".config" / "user-dirs.dirs"
    try:
        lines = config.read_text().splitlines()
    except OSError:
        return None
    prefix = f"XDG_{xdg_key}_DIR"
    for line in lines:
        line = line.strip()
        if not line.startswith(prefix):
            continue
        # e.g. XDG_DESKTOP_DIR="$HOME/Desktop"
        _, _, value = line.partition("=")
        value = value.strip().strip('"')
        value = value.replace("$HOME", str(Path.home()))
        if value:
            return Path(value)
    return None


def resolve_output_directory(raw: str) -> Path:
    """Resolve an output-directory argument to a concrete Path.

    Friendly shortcuts (``desktop``, ``documents``, ``downloads``) resolve to
    the user's home-relative folder on every OS, honouring XDG user-dirs on
    Linux. Anything else is treated as a literal path.
    """
    key = raw.strip().lower()
    if key in _SHORTCUTS:
        xdg_key, folder = _SHORTCUTS[key]
        if platform.system() == "Linux":
            configured = _linux_xdg_dir(xdg_key)
            if configured is not None:
                return configured
        return Path.home() / folder
    return Path(raw).expanduser()


def resolve_input_path(raw: str) -> Path:
    """Resolve an input JSON path.

    A ``/mnt/<drive>/...`` path is only rewritten to a Windows path when we are
    actually running on native Windows. On Linux/WSL that same path is already
    correct, so rewriting it (as the original code always did) would break it.
    """
    if platform.system() == "Windows" and raw.startswith("/mnt/"):
        parts = raw.split("/")
        if len(parts) >= 3 and parts[2]:
            drive = parts[2].upper()
            return Path(drive + ":\\" + "\\".join(parts[3:]))
    return Path(raw).expanduser()


def open_in_file_manager(folder_path: str, select_file: Optional[str] = None) -> str:
    """Open ``folder_path`` in the OS file manager, selecting a file if able.

    Returns a human-readable status string. Raises ``RuntimeError`` (with the
    underlying stderr where available) if the launch fails, or
    ``FileNotFoundError`` if no launcher command exists.
    """
    system = platform.system()

    try:
        if system == "Windows":
            # explorer returns non-zero even on success, so don't check the code.
            if select_file:
                subprocess.run(["explorer", "/select,", select_file])
                return f"Opened Windows Explorer and selected:\n{select_file}"
            subprocess.run(["explorer", folder_path])
            return f"Opened Windows Explorer at:\n{folder_path}"

        if system == "Darwin":
            if select_file:
                subprocess.run(["open", "-R", select_file], check=True,
                               capture_output=True, text=True)
                return f"Revealed in Finder:\n{select_file}"
            subprocess.run(["open", folder_path], check=True,
                           capture_output=True, text=True)
            return f"Opened in Finder:\n{folder_path}"

        # Linux and other POSIX systems: xdg-open cannot highlight a file.
        subprocess.run(["xdg-open", folder_path], check=True,
                       capture_output=True, text=True)
        note = ""
        if select_file:
            note = ("\n(Note: highlighting a file isn't supported by xdg-open; "
                    "opened the containing folder instead.)")
        return f"Opened file manager at:\n{folder_path}{note}"

    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
        raise RuntimeError(detail) from exc
