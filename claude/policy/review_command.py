#!/usr/bin/env python3
"""Recognize review attempts; completed evidence requires the installed invocation."""
from __future__ import annotations
import sys
import os
from pathlib import Path, PurePosixPath
from repo_target import UnresolvableTarget, _tokenize, _is_command_start, _is_env_prefix_position


def matches(command: str) -> bool:
    try:
        tokens = _tokenize(command)
    except (ValueError, UnresolvableTarget):
        return False
    literal_companion = None
    for index, token in enumerate(tokens):
        if token.startswith('COMPANION=') and (_is_command_start(tokens, index) or _is_env_prefix_position(tokens, index)):
            value = token.partition('=')[2]
            literal_companion = value if value and not any(c in value for c in '$`') else None
        if not (_is_command_start(tokens, index) or _is_env_prefix_position(tokens, index)):
            continue
        offset = index + (1 if token == 'node' else 0)
        if offset + 1 >= len(tokens):
            continue
        executable = tokens[offset]
        if executable in ('$COMPANION', '${COMPANION}'):
            executable = literal_companion or ''
        if '$' in executable or '`' in executable:
            continue
        if PurePosixPath(executable).name == 'codex-companion.mjs' and tokens[offset + 1] == 'review':
            return True
    return False


def completed_matches(command: str) -> bool:
    """Only a final installed companion invocation can inherit the shell exit status.

    Accept simple literal assignments and successful cd prefixes. Conditional
    branches, pipelines, background work and following commands cannot prove
    that this review ran and succeeded. The installed cache and PATH are trusted
    local inputs, as are the existing flag files; this is not provider attestation.
    """
    try:
        tokens = _tokenize(command)
    except (ValueError, UnresolvableTarget):
        return False
    if any(token in (';', '||', '|', '&', '(', ')') for token in tokens):
        return False
    units = [[]]
    for token in tokens:
        if token == '&&':
            units.append([])
        else:
            units[-1].append(token)
    companion = None
    for prefix in units[:-1]:
        if len(prefix) == 1 and prefix[0].startswith('COMPANION='):
            companion = prefix[0].partition('=')[2]
        elif len(prefix) == 2 and prefix[0] == 'cd' and not any(c in prefix[1] for c in '$`'):
            continue
        else:
            return False
    argv = units[-1]
    if argv and argv[0] == 'node':
        argv = argv[1:]
    if len(argv) < 2 or argv[1] != 'review':
        return False
    executable = companion if argv[0] in ('$COMPANION', '${COMPANION}') else argv[0]
    if not executable or any(c in executable for c in '$`'):
        return False
    if any(c in arg for arg in argv[1:] for c in '$`'):
        return False
    root = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))) / 'plugins/cache/openai-codex/codex'
    path = Path(executable)
    if not path.is_absolute():
        return False
    try:
        relative = path.relative_to(root)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return len(relative.parts) == 3 and relative.parts[1:] == ('scripts', 'codex-companion.mjs') and resolved.is_file()


if __name__ == '__main__':
    matcher = completed_matches if '--completed' in sys.argv else matches
    raise SystemExit(0 if matcher(sys.stdin.read()) else 1)
