"""Allow ``python -m socialsentiment ...`` (propagates the exit status)."""

import sys

from socialsentiment.cli import main

if __name__ == "__main__":
    sys.exit(main())
