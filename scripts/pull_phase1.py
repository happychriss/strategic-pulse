"""Compatibility wrapper: python scripts/pull_phase1.py == python -m srm.pull."""

import sys

from srm.pull import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
