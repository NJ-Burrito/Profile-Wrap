# Token and API version reference

## Token

- `njli auth` runs the 3-legged OAuth flow on the user's own app: localhost redirect
  (`linkedin.redirect_uri`, default `http://localhost:8765/callback`), state check, 3-minute wait,
  IPv4 fallback when IPv6 is off. `--paste-redirect` is for SSH and containers.
- Scopes: `openid profile w_member_social` (least scope; changing scopes invalidates old tokens).
- Client id and secret and `token.json` live in the config directory only, with user-only
  permissions. The secret is typed at a hidden prompt. Never ask the user to paste either into chat.
- Lifetime about 60 days, no refresh token for an ordinary app. `njli auth check` shows the state
  (`ok`, `warn` from `linkedin.token_warn_days`, `expired`, `missing`).
- A 401 from LinkedIn means the token is no longer accepted: run `njli auth` again.

## Versions

- Every API call carries `Linkedin-Version: YYYYMM`; there is no default on LinkedIn's side.
- `linkedin.api_version: auto` picks the newest version in `data/linkedin-versions.json` that is
  not past its sunset date. A pinned version past its sunset is refused before any request; one
  within `linkedin.sunset_warn_days` warns.
- `njli api-versions` prints the dated table. `--refresh` lists versions found on the versioning
  page that the table lacks, marks them `unverified` with no sunset date, and writes the result
  to the data directory (never into the plugin). A human checks the dates against LinkedIn's page.
- The table says when it was retrieved; a table older than 180 days warns.
