# Install the Profile-Wrap desktop app

Profile-Wrap is an independent tool. It is not affiliated with LinkedIn. The desktop app is the same
software as the command line, in a native window. The builds are **not code-signed**, so Windows and
macOS show a warning the first time. This page shows each step.

## 1. Download

Open the [latest release](https://github.com/NJ-Burrito/profile-wrap/releases/latest) and take the file for your machine:

| Your computer | File |
|---|---|
| Windows (64-bit) | `profile-wrap-<version>-windows-x64.zip` |
| Mac with Apple silicon (M1 and later) | `profile-wrap-<version>-macos-arm64.zip` |
| Mac with an Intel chip | `profile-wrap-<version>-macos-x64.zip` |
| Linux (64-bit) | `profile-wrap-<version>-linux-x64.tar.gz` |

Optional check: download `SHA256SUMS` from the same page and compare.

```text
Windows (PowerShell):  Get-FileHash .\profile-wrap-<version>-windows-x64.zip -Algorithm SHA256
macOS / Linux:         shasum -a 256 profile-wrap-<version>-*.zip   (or sha256sum)
```

The release also carries a GitHub build-provenance attestation: `gh attestation verify <file> --repo NJ-Burrito/profile-wrap`.

## 2. Unzip

Unzip into a folder you keep, for example `%LOCALAPPDATA%\Profile-Wrap` or `~/Applications/Profile-Wrap`. The folder
is self-contained: no installer, no admin rights, nothing written outside it except your workspace and settings.

## 3. First run

Start `Profile-Wrap.exe` (Windows) or `Profile-Wrap` (macOS, Linux). A window opens. On the very first run the app
creates a **demo workspace** in `~/profile-wrap/default` (a fictional persona, no network, no account) so you can look
around the board, the providers screen and the settings before you add your own facts. To use your own data, run
`Profile-Wrap init` from a terminal in the install folder, or follow the quickstart in the README.

If the window cannot open (no web view on the machine), the app opens your default browser on `127.0.0.1` instead.
Nothing listens on any other address.

## Windows: SmartScreen

Because the file is unsigned, Windows may say "Windows protected your PC".

1. Click **More info**.
2. Click **Run anyway**.

You do this once per downloaded copy. If the zip shows "This file came from another computer", right-click the zip,
choose **Properties**, tick **Unblock**, then unzip.

## macOS: Gatekeeper

macOS may say the app "cannot be opened because the developer cannot be verified".

1. In Finder, **right-click** (or Control-click) `Profile-Wrap`, choose **Open**, then **Open** again in the dialog.
2. If there is no Open button, open **System Settings > Privacy & Security**, scroll to the message about
   `Profile-Wrap`, and click **Open Anyway**. Confirm with your password.
3. As a last resort, in Terminal: `xattr -dr com.apple.quarantine ~/Applications/Profile-Wrap`.

Apple silicon requires a signature on downloaded code; the build is ad-hoc signed by PyInstaller, which is why the
steps above are enough.

## Linux

- Extract with `tar xzf profile-wrap-<version>-linux-x64.tar.gz` and run `./Profile-Wrap/Profile-Wrap`.
- The native window needs GTK 3 and WebKitGTK (Debian and Ubuntu: `sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1`;
  Fedora: `sudo dnf install gtk3 webkit2gtk4.1`). Without them the app opens your browser instead.
- Keys: the keychain needs a running Secret Service or KWallet. On a headless machine use the environment variable (below).
- The build targets glibc systems at least as new as Ubuntu 22.04.

## Where your keys are stored

API keys you paste into the Providers screen go to your **operating-system keychain** (macOS Keychain, Windows
Credential Locker, Linux Secret Service or KWallet), under the service name `profile-wrap`. They are never written to a
config file, the ledger, a log, or the board. Only the last four characters are shown. If there is no keychain (for
example a headless Linux box), set `PROFILE_WRAP_<PROVIDER>_API_KEY` (for example `PROFILE_WRAP_ANTHROPIC_API_KEY`) in the
environment instead. The app never proxies, shares or uploads a key; it is sent only to the provider you chose.
Details: `docs/PROVIDERS.md`.

## Check that it works

```text
Profile-Wrap --selftest
```

starts the local server without a window, checks every screen and exits 0. It makes no network call.

## Update

Download the newer release and unzip it over the old folder (or into a new one). Your workspace and keys are not
inside the app folder, so they stay. See `UPDATING.md`.

## Uninstall

1. Delete the `Profile-Wrap` folder.
2. Optional: delete the workspace `~/profile-wrap/` (your facts, drafts, ledger) and the settings folder
   (`%APPDATA%\profile-wrap` on Windows, `~/Library/Application Support/profile-wrap` on macOS, `~/.config/profile-wrap` on Linux).
3. Optional: remove saved keys. Windows: Credential Manager > Windows Credentials > entries named `profile-wrap`.
   macOS: Keychain Access > search `profile-wrap`. Linux: your keyring manager (Seahorse), or
   `python -c "import keyring; keyring.delete_password('profile-wrap','anthropic')"` per provider.
4. If you set up scheduled jobs, remove them first with `Profile-Wrap schedule remove`.
