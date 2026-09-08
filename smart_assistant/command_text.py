"""Command argument parsing without treating Windows path separators as escapes."""
from __future__ import annotations

import shlex
import re


def split(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    return list(lexer)


def file_request(raw: str) -> tuple[str, str]:
    """Separate command/path from a multiline body, preserving its whitespace."""
    header, separator, body = raw.partition("\n")
    match = re.match(r'''^\s*\S+\s+("[^"]*"|'[^']*'|\S+)(?:[ \t]+(.*))?$''', header)
    if not match:
        raise ValueError("a file path is required")
    filename = split(match.group(1))[0]
    if separator:
        return filename, body
    # Legacy one-line create_file requests remain supported.
    return filename, match.group(2) or ""
