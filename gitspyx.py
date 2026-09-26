#!/usr/bin/env python3
"""GitSpyX — backwards-compatibility shim.

The project is now a proper package. This file keeps the classic invocation
working so old bookmarks, scripts and muscle memory don't break:

    python3 gitspyx.py -u <username>              # user profile
    python3 gitspyx.py -u OWNER -i REPO           # repo investigation
                                                  # (translated to -i OWNER/REPO)

All real logic lives in the :mod:`gitspyx` package; see README for the full
flag reference.
"""

import sys

from gitspyx.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
