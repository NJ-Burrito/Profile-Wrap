"""``profile-wrap gui``: a native window (pywebview) on a local server, with a browser fallback.

The server listens on 127.0.0.1 only, on a random port, and every page and API call needs the
per-launch token. It makes no network call of its own; the only outside call is the one the user
asks for (a provider test or a draft) to the provider they chose.
"""
from __future__ import annotations
