"""Enable ``python -m espalier`` to invoke the CLI (parity with the
``espalier`` console script).

Delegates to the same entry point the console script uses
(``espalier.cli:main``), so ``python3 -m espalier audit .`` works."""
import sys

from espalier.cli import main

if __name__ == "__main__":
    sys.exit(main())
