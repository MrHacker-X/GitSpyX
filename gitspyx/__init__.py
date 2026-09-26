"""GitSpyX - Advanced GitHub Intelligence Tool.

Public API surface of the package. Prefer the CLI (``python -m gitspyx``)
for interactive use; import from here for scripting.
"""

__title__ = "gitspyx"
__version__ = "3.1.0"
__author__ = "Alex Butler (Vritra Security Organization)"
__license__ = "MIT"

from .cache import ETagCache
from .client import GitSpyXClient
from .collectors import (
    collect_full_report,
    collect_org,
    collect_repo,
    collect_repo_activity,
    collect_search,
    collect_user,
)
from .exceptions import (
    APIError,
    AuthenticationError,
    ExportError,
    GitSpyXError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SecondaryRateLimitError,
    ValidationError,
)
from .exporters import ExportManager
from .ui import render

__all__ = [
    "__title__",
    "__version__",
    "__author__",
    "__license__",
    "APIError",
    "AuthenticationError",
    "ETagCache",
    "ExportError",
    "ExportManager",
    "GitSpyXClient",
    "GitSpyXError",
    "NetworkError",
    "NotFoundError",
    "RateLimitError",
    "SecondaryRateLimitError",
    "ValidationError",
    "collect_full_report",
    "collect_org",
    "collect_repo",
    "collect_repo_activity",
    "collect_search",
    "collect_user",
    "render",
]
