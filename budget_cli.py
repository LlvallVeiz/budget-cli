#!/usr/bin/env python3
"""Titik masuk CLI: jalankan dengan `python3 budget_cli.py <perintah> ...`.

Alternatif: `python3 -m budget <perintah> ...`.
"""

import sys

from budget.cli import main

if __name__ == "__main__":
    sys.exit(main())
