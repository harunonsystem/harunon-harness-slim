#!/usr/bin/env python3
"""Inspect commit argv without executing Git; share index and hook-bypass checks."""
from __future__ import annotations

import sys
from repo_target import _tokenize, _is_git_start, _SEPARATORS, _GIT_GLOBAL_VALUE_OPTIONS

VALUE_OPTIONS = {
    '-m', '--message', '-F', '--file', '-C', '--reuse-message', '-c', '--reedit-message',
    '--author', '--date', '--cleanup', '--trailer', '--fixup', '--squash', '--pathspec-from-file',
}
FLAG_OPTIONS = {
    '--amend', '--allow-empty', '--allow-empty-message', '--no-edit', '--edit', '--quiet',
    '--verbose', '--status', '--no-status', '--signoff', '--no-signoff', '--reset-author',
    '--dry-run', '--short', '--branch', '--porcelain', '--long', '--null', '--no-post-rewrite',
    '--no-gpg-sign', '--gpg-sign', '--untracked-files', '--no-verify', '--all', '--include',
    '--only', '--pathspec-file-nul',
}


def commit_arguments(command: str) -> list[list[str]]:
    tokens = _tokenize(command)
    found = []
    for index, token in enumerate(tokens):
        if token != 'git' or not _is_git_start(tokens, index):
            continue
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor].startswith('-'):
            option = tokens[cursor]
            cursor += 1
            if option in _GIT_GLOBAL_VALUE_OPTIONS or option == '-C':
                cursor += 1
        if cursor >= len(tokens) or tokens[cursor] != 'commit':
            continue
        end = cursor + 1
        while end < len(tokens) and tokens[end] not in _SEPARATORS and tokens[end] not in ('(', ')'):
            end += 1
        found.append(tokens[cursor + 1:end])
    return found


def inspect(args: list[str], mode: str) -> str | None:
    cursor = 0
    while cursor < len(args):
        token = args[cursor]
        cursor += 1
        if token == '--':
            return 'commit pathspec' if mode == 'index' and cursor < len(args) else None
        if not token.startswith('-') or token == '-':
            if mode == 'index':
                return 'commit pathspec'
            continue
        name = token.split('=', 1)[0]
        if name in ('--all', '--include', '--only', '--pathspec-from-file', '--pathspec-file-nul') and mode == 'index':
            return 'commit-time staging/pathspec'
        if name == '--no-verify' and mode == 'no-verify':
            return 'hook bypass'
        if name in VALUE_OPTIONS:
            if '=' not in token:
                if cursor >= len(args):
                    return 'missing option value'
                cursor += 1
            continue
        if token.startswith('--'):
            if name not in FLAG_OPTIONS and mode == 'index':
                return 'unsupported commit option'
            continue
        # Short options may be combined. A value option consumes the remainder,
        # e.g. -m-a is the message "-a", while -amtext stages then sets a message.
        for offset, flag in enumerate(token[1:], 1):
            if flag in 'aio' and mode == 'index':
                return 'commit-time staging/pathspec'
            if flag == 'n' and mode == 'no-verify':
                return 'hook bypass'
            if flag in 'mFCc':
                if offset == len(token) - 1:
                    if cursor >= len(args):
                        return 'missing option value'
                    cursor += 1
                break
            if flag in 'Su':  # optional attached values (signing key / untracked mode)
                break
            if flag not in 'qveszb' and mode == 'index':
                return 'unsupported commit option'
    return None


def main() -> int:
    mode = sys.argv[1]
    try:
        invocations = commit_arguments(sys.stdin.read())
        if not invocations:
            raise ValueError('commit argv cannot be resolved')
        for args in invocations:
            reason = inspect(args, mode)
            if reason:
                print(reason)
                return 2
    except Exception:
        print('commit argv cannot be resolved')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
