"""The local review board: a stdlib HTTP server on 127.0.0.1 and a small browser app.

Modules: ``store`` (reads), ``actions`` (decisions and bookkeeping writes), ``worker`` (the Improve
job), ``security`` (host, origin, token, path rules), ``server`` (HTTP), ``cli_ext`` (``profile-wrap board``
and ``profile-wrap review``).
"""
from __future__ import annotations

BOARD_API_VERSION = 1
