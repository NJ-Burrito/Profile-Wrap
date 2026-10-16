---
description: Open the review board (Posts, Comments to post, Connect, Profile fixes, Metrics, Settings).
argument-hint: "[--port N] [--open]"
---
Run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" board $ARGUMENTS` in the background and give the user the
local address it prints (it binds 127.0.0.1 only). Allow, Reject and Improve are the user's clicks;
do not press them. Allow needs a gate PASS. If the token banner shows a warning, point to
`profile-wrap auth check` and `docs/linkedin-app-setup.md`.
