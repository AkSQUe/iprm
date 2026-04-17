#!/usr/bin/env python3
"""Verify that every top-level package in requirements.txt has a pin in requirements.lock.

Rationale: our deploy script installs from requirements.lock (reproducible
builds), while developers add new dependencies to requirements.txt. If the
lock isn't regenerated, the deploy installs an incomplete set of packages
and fails at import time on production.

This script is run in CI (see .github/workflows/verify-lock.yml) and fails
the build if requirements.lock is stale. Run locally with:

    python scripts/verify-lock.py

Exit code 0 = OK, 1 = drift detected.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TXT = REPO_ROOT / 'requirements.txt'
LOCK = REPO_ROOT / 'requirements.lock'

# Canonicalize package names per PEP 503 (pip normalization): lowercase,
# replace runs of [-_.] with a single '-'. Example: 'Flask-Cors' == 'flask_cors'.
_CANON = re.compile(r'[-_.]+')


def canonical(name: str) -> str:
    return _CANON.sub('-', name.strip()).lower()


def parse_top_level(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            # Skip comments, blank lines, and -r/-e include directives.
            continue
        # Split on first version specifier character.
        name = re.split(r'[<>=!~\[\s]', line, maxsplit=1)[0]
        if name:
            names.add(canonical(name))
    return names


def parse_lock(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or '==' not in line:
            continue
        name = line.split('==', 1)[0].strip()
        if name:
            names.add(canonical(name))
    return names


def main() -> int:
    if not TXT.exists() or not LOCK.exists():
        print(f'ERROR: missing requirements.txt or requirements.lock at {REPO_ROOT}')
        return 1

    top = parse_top_level(TXT)
    locked = parse_lock(LOCK)
    missing = top - locked

    if not missing:
        print(f'OK: all {len(top)} requirements.txt entries pinned in requirements.lock')
        return 0

    print('ERROR: requirements.lock is out of sync with requirements.txt.')
    print('The following top-level packages are missing from requirements.lock:')
    for name in sorted(missing):
        print(f'  - {name}')
    print()
    print('To fix:')
    print('  python -m venv /tmp/lock-check && source /tmp/lock-check/bin/activate')
    print('  pip install -r requirements.txt')
    print('  pip freeze > requirements.lock  # then curate to keep only real deps')
    return 1


if __name__ == '__main__':
    sys.exit(main())
