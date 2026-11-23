"""Sentinel AI — Smart Security Camera System (backend package).

This package contains the FastAPI application, database layer, AI pipeline
and all supporting services for the Sentinel AI perimeter control center.
"""

# NOTE: this package intentionally does not import ``backend.config`` (or any
# other submodule) at import time.  ``Settings`` is instantiated when
# ``backend.config`` is imported, so tests and scripts must be free to set
# environment variables before that happens.  Import the submodules directly:
#
#     from backend.config import settings

__all__ = ["__version__"]
__version__ = "1.0.0"
