"""Golit command-line entry point.

Fleshed out in M6 (``golit run <app.py>``). Stubbed here so the ``golit``
console-script declared in ``pyproject.toml`` resolves after install.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("golit: CLI not implemented yet (coming in M6). Try `make run`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
