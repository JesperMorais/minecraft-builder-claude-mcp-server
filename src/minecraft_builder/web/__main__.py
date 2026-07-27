"""Run the 3D viewer on its own.

    python -m minecraft_builder.web                      # empty, waits for a structure
    python -m minecraft_builder.web examples/pagoda.json # load a structure and show it
    python -m minecraft_builder.web --open build.json    # ...and open a browser

Normally the viewer is started by the ``show_structure`` MCP tool inside a Claude
session. Running it directly is for looking at a structure file you already have,
and for working on the frontend without needing a session at all — the static
assets are re-read per request, so a browser refresh picks up edits.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path
from typing import List, Optional

from ..schema import MinecraftStructure, StructureTooLargeError
from .app import ensure_running
from .state import STATE


def _load(path: Path) -> MinecraftStructure:
    with path.open(encoding="utf-8") as handle:
        return MinecraftStructure(**json.load(handle))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m minecraft_builder.web",
        description="Serve the local 3D structure viewer.",
    )
    parser.add_argument(
        "structure",
        nargs="?",
        type=Path,
        help="Optional path to a structure JSON file to display immediately.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the viewer in your default browser.",
    )
    args = parser.parse_args(argv)

    if args.structure is not None:
        try:
            structure = _load(args.structure)
            version = STATE.put(structure)
        except FileNotFoundError:
            print(f"No such file: {args.structure}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as error:
            print(f"{args.structure} is not valid JSON: {error}", file=sys.stderr)
            return 1
        except StructureTooLargeError as error:
            print(f"Structure too large: {error}", file=sys.stderr)
            return 1
        except ValueError as error:
            print(f"Could not load {args.structure}: {error}", file=sys.stderr)
            return 1

        size = structure.calculate_size()
        print(f"Loaded {structure.name!r} "
              f"({size.width}x{size.height}x{size.length}) as version {version}")

    url = ensure_running()
    print(f"Viewer running at {url}")
    print("Press Ctrl+C to stop.")

    if args.open_browser:
        webbrowser.open(url)

    try:
        # The server runs on a daemon thread, so the process has to stay alive.
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
