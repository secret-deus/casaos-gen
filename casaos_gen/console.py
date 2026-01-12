"""Console output helpers.

Windows consoles can use legacy code pages that cannot encode every Unicode
character. These helpers ensure --dry-run and stdout previews never crash due to
UnicodeEncodeError.
"""

from __future__ import annotations

import sys


def write_stdout_text(text: str) -> None:
    """Write text to stdout without crashing on UnicodeEncodeError."""
    if text is None:
        return

    if not text.endswith("\n"):
        text = f"{text}\n"

    try:
        sys.stdout.write(text)
        return
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        data = text.encode(encoding, errors="backslashreplace")
        sys.stdout.buffer.write(data)

