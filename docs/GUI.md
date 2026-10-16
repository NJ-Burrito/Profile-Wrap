# The desktop app (`profile-wrap gui`)

```text
profile-wrap gui                      # native window if pywebview is installed, else your browser
profile-wrap gui --browser            # always the browser
profile-wrap gui --workspace DIR      # a workspace other than the current one
profile-wrap gui --selftest [--json]  # headless check: server, /health, every screen; exit 0 or 1
```

For a native window install the optional package: `uv pip install pywebview`. Without it, or when the
machine has no web view (WebView2 on Windows, WebKit on macOS, WebKitGTK on Linux), the app opens your
default browser on the same local address. Profile-Wrap is independent and not affiliated with LinkedIn.

## Screens

| Screen | What it does |
|---|---|
| Home | Workspace, posting mode, pause flags, chosen provider, the next post, and the doctor result (run it again with one button). |
| Board | Starts the existing review board on a random local port and links to it. The board keeps its own security rules (it refuses to be framed), so it opens in its own tab or window. |
| Providers | Lists the six providers with the key state (last 4 characters only). Paste or replace a key in a password field, test the connection, choose provider and model, remove a stored key. |
| Build | Pick a calendar day, generate a text draft with the chosen provider, and run the gate. Shows the caption and each gate line. |
| Settings | Workspace folder (for this session), posting mode, and which scheduled jobs are on in the config. |

Keys: the key goes from the password field to the OS keychain through `profile_wrap.providers.keystore`
and nowhere else. The page never receives a key back (only `****` and the last 4 characters), nothing is
written to a file, the ledger or a log, and an error message that would contain the key has it replaced
by `[REDACTED]`. With no keychain (headless Linux) the screen says to set
`PROFILE_WRAP_<PROVIDER>_API_KEY` instead.

Build writes drafts only (`drafts/<slug>/caption.txt`, `alt.txt`, `meta.json` with status `draft`). It
refuses to touch a draft that is queued or posted, asks for the Replace box before overwriting a caption,
and handles `text` posts; a `slides` or `gif` day needs media, so it points to `profile-wrap build-week`.
The gate decides whether the draft passes; Allow and posting stay on the board and the CLI.

The schedule switches edit `schedule.jobs.<name>.enabled` in the config. Install the jobs in the OS
scheduler with `profile-wrap schedule install`. `api_scheduled` posting also needs its written
acknowledgement (`profile-wrap config ack`); the screen reports that refusal.

## Security model

* The server binds `127.0.0.1` only, on a port the OS picks, and refuses a Host header that is not
  loopback on that port (DNS-rebinding guard).
* A per-launch random token is in the launch URL and in the nav links. A page without it gets 403.
  Every `/api/*` call sends it in `X-PW-Token`; a POST also needs this server's own `Origin`.
* Strict CSP: scripts and styles only from the server, no inline code, no external origin. The page is
  built from text nodes, never from HTML strings.
* No call leaves the machine except the provider call you start (Test connection, Generate draft), to the
  provider you chose. `--selftest` uses a throwaway demo workspace, a loopback socket and no provider.
* Fonts: system fonts, with IBM Plex Sans (SIL OFL) used when installed. No font file ships in
  `gui_assets/`. The mark is a plain rounded square with three lines; no LinkedIn logo.

## Accessibility

Skip link, landmarks, one h1 per screen, labelled controls, visible focus ring, a live status line,
light and dark by system setting with a Theme button, reduced-motion respected, and keyboard shortcuts
Alt+1 to Alt+5 for the five screens. Every control is a real button, link, input or select.

## Files

`profile_wrap/gui/` holds the server (`server.py`), the screens' logic (`logic.py`), the window
(`window.py`), the selftest and the CLI hook (`cli_ext.py`). The page assets are in `gui_assets/`
(`index.html`, `gui.css`, `gui.js`, `mark.svg`); a wheel needs `gui_assets` force-included as
`profile_wrap/_data/gui_assets`, and a frozen build needs it added as data (`--add-data`).
