# Platforms: Windows, macOS and Linux

nj-linkedin runs on all three. The core is Python 3.10 or newer with the standard library only. The
text and slides lane needs nothing else to start; the GIF lane needs Node 22 or newer, a browser and
ffmpeg. `njli doctor` checks every item below and prints the install line for **your** OS.

## What is needed for what

| You want | You need |
|---|---|
| The demo, copy mode, drafting, the gate, the board | Python 3.10+ (and `tzdata` on Windows) |
| AI drafting and review | the `claude` CLI |
| Slides to PNG or PDF | Node 22+, a Chrome or Chromium, `npx` |
| Animated GIFs | the above plus ffmpeg and ffprobe |
| PDF (document) posts, optional checks | poppler (`pdftotext`, `pdffonts`) |
| Unattended posting | a LinkedIn developer app, a scheduler entry, `api_scheduled` and a typed acknowledgement |

System tools are never bundled. Nothing is written into the plugin directory, nothing edits your
PATH, nothing is installed globally.

## Where things live

| What | Windows | macOS | Linux |
|---|---|---|---|
| Secrets (`linkedin.env`, `token.json`, `ack.json`) | `%APPDATA%\nj-linkedin\<profile>\` | `~/Library/Application Support/nj-linkedin/<profile>/` | `${XDG_CONFIG_HOME:-~/.config}/nj-linkedin/<profile>/` |
| Stable runtime copy, venv, caches | `%APPDATA%\nj-linkedin\` | `~/Library/Application Support/nj-linkedin/` | same root as secrets |
| Workspace (your data, its own git repo) | `~\nj-linkedin\<profile>` | `~/nj-linkedin/<profile>` | `~/nj-linkedin/<profile>` |

Override with `NJLI_CONFIG_DIR`, `NJLI_DATA_DIR`, `NJLI_HOME` or `--workspace`. The CLI refuses a
workspace inside the plugin directory. An existing `~/.config/linkedin` is read only, as input to
`import-legacy`.

Secrets files are mode 0600 on macOS and Linux. On Windows they get an `icacls` ACL for the current
user only; `doctor` cannot inspect ACLs, so it says so instead of passing silently.

## Installing the prerequisites

| Tool | Windows | macOS | Linux |
|---|---|---|---|
| Python 3.10+ | `winget install Python.Python.3.12` or `scoop install python` | `brew install python@3.12` | `sudo apt install python3.12` or `sudo dnf install python3.12` |
| git | `winget install Git.Git` | `brew install git` | `sudo apt install git` |
| Node 22+ | `winget install OpenJS.NodeJS.LTS` | `brew install node@22` or `nvm install 22` | `nvm install 22`, or distro packages |
| ffmpeg | `winget install Gyan.FFmpeg` or `scoop install ffmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| Chrome or Chromium | `winget install Google.Chrome` | `brew install --cask google-chrome` | `sudo apt install chromium` |
| poppler (optional) | `scoop install poppler` | `brew install poppler` | `sudo apt install poppler-utils` |
| uv (optional) | `winget install astral-sh.uv` | `brew install uv` | the installer from astral.sh |

## Starting njli

- **Plugin:** `${CLAUDE_PLUGIN_ROOT}/bin/njli` (macOS, Linux, Git Bash) or `bin\njli.cmd` (Windows).
  The launcher looks for Python 3.13, 3.12, 3.11, 3.10 and then `python3` and `python`. Set
  `NJLI_PYTHON` to force one. On Python 3.9 or older it prints one message with the exact fix and
  stops.
- **Source or wheel:** `uv tool install nj-linkedin` or `pipx install nj-linkedin`, then `njli`.
- **Schedulers** never use the plugin directory. They call the stable copy that
  `njli runtime install` writes: `<python> <data>/runtime/current <arguments>`. The path is stable
  across plugin updates, so jobs keep working until you run `njli runtime sync`.

### Windows

- Use forward or back slashes; paths with spaces and non-ASCII user names are supported. Set
  `PYTHONUTF8=1` if you run scripts yourself (njli sets it for its own runs).
- `tzdata` is installed with the package because Windows has no IANA time zone database.
- `runtime/current` is a symlink when allowed, otherwise a junction, otherwise a plain copy. All
  three run the same way.
- Task Scheduler is used for jobs (installed by `njli schedule install`).

### macOS

- launchd runs jobs with a minimal PATH. The scheduler install captures the absolute paths of
  `node`, `npx`, `ffmpeg`, `ffprobe` and `claude` into the plist. `njli doctor --launchd-dryrun`
  tests that.
- A browser downloaded outside the App Store may be quarantined: run
  `xattr -dr com.apple.quarantine <path-to-browser>`. Apple Silicon needs the arm64 build.
- The keychain login of the `claude` CLI may not be reachable from launchd. If a headless test run
  fails, use an API key (`models.runner.auth = "api_key"`).
- A sleeping laptop coalesces missed intervals; there is no wake-to-run, so the missed-slot rule
  applies (see the scheduling doc).

### Linux

- `systemctl --user` timers are used when available, otherwise a marked crontab block. On a server
  run `loginctl enable-linger <user>` so user timers run when you are logged out.
- Headless machines can use `npx playwright install --with-deps chromium`.

## Behind a proxy or offline

`njli doctor --online` tests the network. Behind a proxy set `HTTPS_PROXY`. Everything except
posting works offline once the renderers are installed.
