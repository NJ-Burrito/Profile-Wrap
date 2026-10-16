# Terms and risk, in plain words

Not legal advice. This page was written from LinkedIn's public terms as read on 2026-10-10. The wording on LinkedIn's site is what counts; read it again before you turn on anything below. A human re-reads this page against the live terms before every release.

Your own LinkedIn account, your own developer app and your own decisions are involved. The authors of this package cannot promise how LinkedIn will treat any automation, and they do not offer to take on that risk.

## What is low risk

- **Copy mode.** The package writes a copy-ready block. You paste it. No API is used.
- **Click mode (`api_click`, the default).** You press Allow, then press Post now. The post goes through LinkedIn's official Posts API under the `w_member_social` scope that LinkedIn gives to every developer who adds the self-serve "Share on LinkedIn" product. A person starts each post.

## What carries risk, and why

### Unattended posting (`api_scheduled`)

- The LinkedIn API Terms of Use list among the general restrictions: "Use the Content or the APIs to automate posting on the LinkedIn Services" (API Terms of Use, section 3.1, item 26; read 2026-10-10).
- The text does not say whether a scheduled post to your own account is meant. It could be read either way.
- If you turn this on, the `due` job posts at the slot with no one pressing a button. You accept that LinkedIn may limit or close the app or the account.

### API comments and replies (experimental extra, off by default)

- The User Agreement (section 8.2, "Don'ts") bars using "bots or other unauthorized automated methods" to "create, comment on, like, share, or re-share posts" (read 2026-10-10).
- The route the extra uses is the older `socialActions` route. It is not documented for self-serve apps and may already be closed. The package tests it with a non-posting probe and falls back to drafts when LinkedIn says no.
- The package never claims this works. There is no automated test comment on a real post; a manual self-test is described in the extra's documentation.

### Apify reader

- It reads your own posts and comments through a third-party service that scrapes LinkedIn pages. The User Agreement (section 8.2) bars scraping the Services. It is off by default, restricted to your own content, capped per day, and cannot read other people's posts.

### Likes

- Off by default for the same reason as comments.

## What the package never does

No sign-in handling, no browser against linkedin.com, no message reading, no invitation sending, no profile editing, no disguise. See `docs/references/compliance.md`.

## How acknowledgements work

- `njli config ack <action>` asks you to type a fixed sentence. It stores the date and the sha256 of this page and `compliance.md`.
- If an update changes either page, the hash no longer matches. The action goes back to draft or notify, and `njli doctor` and the board say so, until you accept the new text.
- Upgrades never silently weaken a safety setting.

## If something goes wrong

- Run `njli pause --all` to stop every job and API call. Run `njli schedule remove` to remove the scheduled jobs.
- A post marked `needs_check` may or may not be live. Open LinkedIn, look, then confirm with `njli post <slug> --resolve --posted` or `--not-posted`. The package never reposts on its own.
- To stop using the API entirely, remove the app's token from the config directory and delete the app in LinkedIn's developer portal.
