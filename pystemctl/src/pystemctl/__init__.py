"""Python reimplementation of systemctl and journalctl.

The unit-management helpers also create ephemeral (transient) user units, so a
caller can start a background command and reach it later by name.
"""

__version__ = "0.1.0"
