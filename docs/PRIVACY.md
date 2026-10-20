# Profile-Wrap privacy policy

Last updated: 2026-10-20. Applies to Profile-Wrap (the `profile-wrap` command line, desktop app and Claude Code and Codex
plugins) and `profile-wrap-mcp`. Profile-Wrap is an independent open source project (MIT). It is not affiliated with LinkedIn, Anthropic or OpenAI.

## Short version

- Your drafts, facts, ledger, board data and settings stay in your own workspace folder on your own machine.
- API keys live in the operating system keychain only, and are sent only to the provider you chose.
- LinkedIn is reached only through the official LinkedIn API, with your own developer app and your own token.
- There is no telemetry, no analytics, no account with us and no server of ours. The maintainers receive nothing.
- The only other call is an optional, anonymous check of GitHub for a newer release (see "Update check"); you can turn it off.

## What stays on your machine

Everything Profile-Wrap creates is a plain file in the workspace folder you pick: `config/`, `drafts/`, `research/`
(your facts), the posting ledger, review-board state and logs. The review board and the desktop app run a local server on
`127.0.0.1` with a random port and a one-time token; they do not listen on your network. Nothing is uploaded to a
Profile-Wrap service because there is none.

## API keys

- A key you paste is saved in the OS keychain (macOS Keychain, Windows Credential Locker, Linux Secret Service or KWallet).
- On a headless machine without a keychain you can set an environment variable instead; Profile-Wrap reads it and never copies it into a file.
- A key is never written to a config file, the ledger, a log, board data, demo data or an error message. Screens show only
  the last 4 characters. A built-in leak scan checks the repository and release builds for key patterns.
- A key is sent only to the provider you selected (Anthropic, OpenAI, OpenRouter, Google Gemini, or your local Ollama).
  Profile-Wrap does not proxy, pool, resell or store keys on any server.
- With the `claude-code` provider, Profile-Wrap starts your own installed `claude` program. It never reads, copies or stores
  your Claude sign-in or tokens.

## What goes to the AI provider you chose

When you ask for a draft or a score, the text of that request is sent to your chosen provider: the topic, the style
rules, and the verified facts needed for that draft. The provider's own terms and privacy policy apply to that data. Choose
`ollama` to keep requests on your machine. Profile-Wrap sends nothing else to a provider.

## LinkedIn data

- Publishing and your own account use only LinkedIn's official API, with a developer app you create and own (see
  `docs/linkedin-app-setup.md`). The access token is stored on your machine and used only to publish posts you approved.
- It does not log in to LinkedIn with a password, drive a browser against LinkedIn, read direct messages, send
  connection invitations or hide automation.
- Optional readers, all off by default and each switched on only by your own typed acknowledgement, can look up other
  people's recent posts. What each one sends, and where:
  - Tavily (`api.tavily.com`): the person's name, a topic if you set one, and the word "linkedin", as a search query;
    for full text, the address of one post. Your Tavily key goes only to that host.
  - Apify (`api.apify.com`): the profile name (the last part of the profile address). Your Apify token goes only to that host.
  - LinkedIn public pages (`www.linkedin.com`): a plain GET of a public page, with no sign-in, no cookies and no token.
  Those services have their own terms and privacy policies. Reading public pages is restricted by the LinkedIn User
  Agreement; see `docs/TERMS-AND-RISK.md`.
- A post is published only after you press Allow on the review board. The MCP tool `post_allowed` can post only a draft
  that already has that board Allow.

## Update check (optional, on by default)

When a surface starts (command line in a terminal, desktop app, review board, the Claude Code plugin session hook, the
MCP server), Profile-Wrap makes one anonymous `GET https://api.github.com/repos/NJ-Burrito/profile-wrap/releases` to learn
whether a newer release exists. If the newest release has no notes it makes a second `GET` of `CHANGELOG.md` from the same
host. It sends no token, no cookie and no workspace data: GitHub sees your IP address and the neutral
`User-Agent: profile-wrap/<version>`, as for any web request. The answer is cached in your user cache folder for one hour
(so at most one request an hour, well inside GitHub's anonymous limit) and nothing is installed unless you run
`profile-wrap update apply` or follow the instructions yourself. It is the only network call that is not LinkedIn, your AI
provider or a reader you switched on.

Turn it off with `updates.check = false` in `config/profile-wrap.json` (`profile-wrap config set updates.check false`) or
the environment variable `PROFILE_WRAP_NO_UPDATE_CHECK=1`. It is also off under CI and in tests. The local choices (skipped
version, remind later) live in the same cache folder.

## Telemetry and cookies

None. No usage statistics, crash reports, tracking identifiers or advertising. The documentation lives on GitHub, which has
its own policy; opening a page there is between you and GitHub.

## Directories and package indexes

Listings on PyPI, the Official MCP Registry, mcp.so, Glama, Smithery and Anthropic's plugin directory carry public
descriptions only. They may count downloads or installs on their side; Profile-Wrap receives those figures only where they
publish them.

## Your control

Delete the workspace folder to remove your data. Remove the key from your keychain app to remove a key. Revoke the token in
your LinkedIn developer app to cut off posting. `profile-wrap pause` stops all posting at once.

## Contact

Questions and requests: https://github.com/NJ-Burrito/profile-wrap/issues . Changes to this policy are made in this file and
are visible in its git history.
