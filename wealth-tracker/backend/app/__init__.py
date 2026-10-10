"""
The FastAPI app. The domain logic it builds on lives next to it in backend/domain
(database, portfolio, imports, money). This puts backend/ on sys.path once, before
any submodule of `app` imports `domain`, so it works however the app is started
(uvicorn from backend/, pytest from the repo root, a script).
"""

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
