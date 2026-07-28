"""The structure the viewer is currently showing.

Deliberately in-memory and process-local: the viewer's whole job in this phase is
to show what the current session just built, and a file or database would add
persistence semantics nobody has asked for yet. Version history is kept so the
viewer can offer "the previous one was better", which is the most predictable
request once someone can actually see a build.

Reads come from the HTTP thread and writes from the MCP thread, so every access
goes through a lock.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from ..schema import MinecraftStructure
from .payload import build_payload

# Keep memory bounded on a long session; older versions are the least useful.
MAX_VERSIONS = 20


class ViewerState:
    """Thread-safe store of the current structure and its recent history."""

    def __init__(self, max_versions: int = MAX_VERSIONS) -> None:
        self._lock = threading.Lock()
        self._versions: List[MinecraftStructure] = []
        self._max_versions = max_versions
        self._next_version = 1

    def put(self, structure: MinecraftStructure) -> int:
        """Store a structure as the current one; returns its version number."""
        with self._lock:
            self._versions.append(structure)
            version = self._next_version
            self._next_version += 1
            if len(self._versions) > self._max_versions:
                del self._versions[0]
            return version

    def current(self) -> Optional[MinecraftStructure]:
        with self._lock:
            return self._versions[-1] if self._versions else None

    def get(self, version: int) -> Optional[MinecraftStructure]:
        """The structure that *was* ``version``, or None if it has aged out.

        Annotations need this: the user marked what was on screen, and resolving
        a coordinate against the current structure instead would silently point
        at whatever occupies it after a revision.
        """
        with self._lock:
            # Version numbers never restart, so the oldest kept version is
            # derived from the counter rather than tracked separately.
            oldest = self._next_version - len(self._versions)
            offset = version - oldest
            if 0 <= offset < len(self._versions):
                return self._versions[offset]
            return None

    @property
    def version(self) -> int:
        """Version number of the current structure; 0 when nothing is loaded."""
        with self._lock:
            return self._next_version - 1

    def payload(self) -> Dict:
        """Viewer payload for the current structure, or an empty-state marker."""
        with self._lock:
            structure = self._versions[-1] if self._versions else None
            version = self._next_version - 1
        if structure is None:
            return {"empty": True, "message": "No structure yet. Ask Claude to build something."}
        return build_payload(structure, version=version)

    def clear(self) -> None:
        """Drop the history and restart version numbering. Tests only.

        In a real session versions only ever go up, and nothing calls this. It
        resets the counter as well as the list because a half-reset leaves tests
        depending on how many versions earlier tests happened to create.
        """
        with self._lock:
            self._versions.clear()
            self._next_version = 1


# The process-wide instance the MCP tools write to and the HTTP server reads.
STATE = ViewerState()
