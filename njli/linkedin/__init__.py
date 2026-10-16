"""The LinkedIn package: OAuth on the user's own app, the Posts API, the ledger-first post flow.

This is the only package allowed to reach the LinkedIn API host. Endpoints are limited to
``/v2/userinfo``, ``/rest/posts``, ``/rest/images`` and ``/rest/documents``; the social-actions
route exists only in ``social_extra`` (the experimental, opt-in extra).
"""
