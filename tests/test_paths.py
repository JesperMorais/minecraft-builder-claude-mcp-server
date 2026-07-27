"""Tests for cross-platform path resolution and file-manager dispatch."""

import subprocess

import pytest

from minecraft_builder import paths


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    return tmp_path


def _set_system(monkeypatch, name):
    monkeypatch.setattr(paths.platform, "system", lambda: name)


# --------------------------------------------------------------------------- #
# resolve_output_directory
# --------------------------------------------------------------------------- #

def test_shortcut_falls_back_to_home_folder(fake_home, monkeypatch):
    _set_system(monkeypatch, "Linux")  # no user-dirs.dirs in tmp home
    assert paths.resolve_output_directory("Desktop") == fake_home / "Desktop"
    assert paths.resolve_output_directory("my documents") == fake_home / "Documents"
    assert paths.resolve_output_directory("downloads") == fake_home / "Downloads"


def test_shortcut_uses_xdg_user_dirs_on_linux(fake_home, monkeypatch):
    _set_system(monkeypatch, "Linux")
    config = fake_home / ".config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text(
        'XDG_DESKTOP_DIR="$HOME/Skrivbord"\n'
        'XDG_DOWNLOAD_DIR="$HOME/Hamtningar"\n'
    )
    assert paths.resolve_output_directory("desktop") == fake_home / "Skrivbord"
    assert paths.resolve_output_directory("downloads") == fake_home / "Hamtningar"


def test_shortcut_ignores_xdg_off_linux(fake_home, monkeypatch):
    _set_system(monkeypatch, "Windows")
    config = fake_home / ".config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Skrivbord"\n')
    # On Windows the XDG file must be ignored.
    assert paths.resolve_output_directory("desktop") == fake_home / "Desktop"


def test_literal_path_passthrough(monkeypatch):
    _set_system(monkeypatch, "Linux")
    got = paths.resolve_output_directory("/srv/builds/out")
    assert str(got) == "/srv/builds/out"


# --------------------------------------------------------------------------- #
# resolve_input_path
# --------------------------------------------------------------------------- #

def test_mnt_path_preserved_on_linux(monkeypatch):
    _set_system(monkeypatch, "Linux")
    got = paths.resolve_input_path("/mnt/c/Users/josh/build.json")
    assert str(got) == "/mnt/c/Users/josh/build.json"


def test_mnt_path_converted_on_windows(monkeypatch):
    _set_system(monkeypatch, "Windows")
    got = paths.resolve_input_path("/mnt/c/Users/josh/build.json")
    assert str(got) == r"C:\Users\josh\build.json"


# --------------------------------------------------------------------------- #
# open_in_file_manager
# --------------------------------------------------------------------------- #

@pytest.fixture
def recorded_run(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(paths.subprocess, "run", fake_run)
    return calls


def test_open_linux_uses_xdg_open(monkeypatch, recorded_run):
    _set_system(monkeypatch, "Linux")
    msg = paths.open_in_file_manager("/home/u/builds")
    assert recorded_run[0][0] == ["xdg-open", "/home/u/builds"]
    assert "file manager" in msg.lower()


def test_open_linux_select_file_notes_limitation(monkeypatch, recorded_run):
    _set_system(monkeypatch, "Linux")
    msg = paths.open_in_file_manager("/home/u/builds", "/home/u/builds/a.schem")
    assert recorded_run[0][0] == ["xdg-open", "/home/u/builds"]
    assert "xdg-open" in msg


def test_open_macos_reveals_file(monkeypatch, recorded_run):
    _set_system(monkeypatch, "Darwin")
    paths.open_in_file_manager("/Users/u/builds", "/Users/u/builds/a.schem")
    assert recorded_run[0][0] == ["open", "-R", "/Users/u/builds/a.schem"]


def test_open_windows_selects_file(monkeypatch, recorded_run):
    _set_system(monkeypatch, "Windows")
    paths.open_in_file_manager(r"C:\builds", r"C:\builds\a.schem")
    assert recorded_run[0][0] == ["explorer", "/select,", r"C:\builds\a.schem"]


def test_open_raises_runtimeerror_on_failure(monkeypatch):
    _set_system(monkeypatch, "Linux")

    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="no display")

    monkeypatch.setattr(paths.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="no display"):
        paths.open_in_file_manager("/home/u/builds")
