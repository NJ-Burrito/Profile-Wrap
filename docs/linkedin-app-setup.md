# Setting up your own LinkedIn developer app

You post through your own free developer app. Nothing here costs money. Not legal advice; the portal's wording and screens change, so follow what you see there.

## 1. Create the app

1. Open the LinkedIn Developer Portal and choose Create app.
2. The form asks for a LinkedIn Page to associate with the app. Official pages do not say whether a Page is required for the self-serve products; if the form asks, create a minimal Page you administer. See the unknowns list in `references/linkedin-api.md` (U1).
3. Name the app something only you will recognise, and upload any logo.

## 2. Add the two products

On the app's Products tab, add:

- **Share on LinkedIn** (grants the `w_member_social` scope)
- **Sign In with LinkedIn using OpenID Connect** (grants `openid` and `profile`)

Both are self-serve. Do not apply for the Community Management API: it is a vetted partner product and not needed for posting.

## 3. Register the redirect

On the Auth tab add exactly this redirect URL:

    http://localhost:8765/callback

(or the value you set in `linkedin.redirect_uri`). If the portal refuses an http address, use the Token Generator in the portal as a manual fallback and paste the token with `profile-wrap auth --paste-redirect`. See `references/linkedin-api.md` (U2).

## 4. Sign in once

    profile-wrap auth

You are asked for the client id and the client secret (the secret is typed into a hidden prompt). They are stored in the config directory with user-only permissions, never in the workspace. Your browser opens the consent page; press Allow. The token is valid for about 60 days.

- On a server or over SSH: `profile-wrap auth --paste-redirect` prints a link, you open it anywhere, press Allow, and paste back the address the browser ends on.
- Check the state any time with `profile-wrap auth check`. `profile-wrap doctor` and the board warn from 10 days before expiry.
- There is no refresh token for an ordinary app. Run `profile-wrap auth` again before the token expires; if you are still signed in to LinkedIn in that browser, the consent step is skipped.
- If you change the scopes, earlier tokens stop working.

## 5. Check it

    profile-wrap selftest

It reads your member id and checks the API version. It never posts.

## 6. Pick the posting mode

- `copy`: you paste the block yourself.
- `api_click` (default): you press Allow on the board, then Post now.
- `api_scheduled`: the scheduled job posts at the slot. Read `TERMS-AND-RISK.md` first; you must type the acknowledgement.

## Keep safe

- Never paste the client secret or the token into chat, an issue or a commit. `profile-wrap leaks scan --workspace` checks before you push a workspace.
- The package never asks for, stores or uses your LinkedIn sign-in details.
