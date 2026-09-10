"""Package execution entry point: python3 -m session_titles."""

import sys
from session_titles.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
