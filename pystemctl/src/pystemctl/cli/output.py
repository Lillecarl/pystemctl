"""One stderr voice and one JSON vocabulary for every command.

Human flags stay the primary interface: ``--json`` only changes the shape
of what is printed, never what is asked, and no flag is replaced by JSON
input. The key vocabulary below covers every command payload:

- ``unit`` names the unit; ``unit_file`` names a file on disk.
- ``active_state``, ``sub_state``, ``load_state`` are the runtime states;
  ``unit_file_state`` is the enablement state (is-enabled, list-unit-files).
- ``job_state`` is the manager start-job outcome; ``result`` is systemd's
  Result and ``exit_status`` its ExecMainStatus number.
- ``exit_code`` is the command's own exit code for the payload.
- ``matched``, ``timed_out`` and ``timeout`` report watch outcomes.
- ``tags``, ``session``, ``main_pid``, ``started_at``, ``transient``,
  ``description``, ``path``, ``profile``, ``job``, ``removed``, ``error``,
  ``event``, ``changes``, ``files`` and ``reloaded`` mean what they say.

``show`` and ``cat`` pass D-Bus property and file keys through untouched;
those vocabularies belong to systemd and the filesystem, not to pystemctl.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def warn(message: object) -> None:
    """Say *message* on stderr with the command prefix."""
    print(f"pystemctl: {message}", file=sys.stderr)


def jsonable(value: Any) -> Any:
    """Make D-Bus values safe for ``json.dumps``."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def emit_json(payload: Any, *, flush: bool = False) -> None:
    """Print *payload* as JSON, the same way from every handler."""
    print(json.dumps(jsonable(payload), default=str, ensure_ascii=False), flush=flush)
