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

- It reads posts and comments through a third-party service that scrapes LinkedIn pages: your own, and the recent posts of profiles you chose to engage with. The User Agreement (section 8.2) bars scraping the Services. It is off by default, capped per day, and paced so the free monthly credit lasts the whole billing cycle (when the credit is gone it rests until the cycle ends). Your Apify token stays in an environment variable and is sent only to api.apify.com. It is an opt-in you accept with `profile-wrap config ack apify`.

### Tavily reader

- It asks the Tavily search service, which indexes the open web, for the recent public LinkedIn posts of profiles you chose, and can fetch the text of one post page at a time. Profile-Wrap sends Tavily the person's name, a topic word and, for the text, the post address; Tavily's own terms and privacy policy apply to that request, and Profile-Wrap does not open LinkedIn for it. Whether this counts as scraping under the User Agreement (section 8.2) is not defined in the text, so it is an opt-in you accept with `profile-wrap config ack tavily`.
- It is off by default. The free plan gives 1,000 credits a month; Profile-Wrap never spends the last 100, spreads the rest over the days left in the calendar month, caches a search for 3 days and fetches one page per call. Your Tavily key stays in an environment variable and is sent only to api.tavily.com. Tavily finds posts about three days after they appear and may miss a person; it never decides that someone is inactive.
- Apify and Tavily are designed to be used together: Apify first for same-day posts, Tavily for the people and days Apify does not cover, the public reader last. Each has its own acknowledgement and its own limits.

### Public reader

- It opens the public LinkedIn page of a post or a profile, the same page a visitor who is not signed in sees, and reads the structured data on it. No third party is involved and nothing is paid. The User Agreement (section 8.2) bars scraping the Services, so this is an opt-in you accept with `profile-wrap config ack public`.
- It is off by default. It sends plain GET requests only, waits at least 3 seconds between pages, stops at 30 pages a day (you can lower it, up to 100), sends the same neutral profile-wrap User-Agent as every other call (it does not pretend to be a browser), sends no Referer, uses no sign-in, no proxy and no disguise, and stops for the rest of the day when a post page answers 999, 429 or 403. Guest profile pages are rate-limited per IP, so reads are spread across the day: at most 2 profile pages per run, at least 20 minutes apart (kept across runs), 12 a day, and after a 999 on a profile page profile reads pause for 6 hours. LinkedIn may refuse a request that does not look like a browser; then that reader stops and the next one takes over.
- LinkedIn may show less on a public page, change it, or block your address. When it does, reading falls back to manual: paste the numbers yourself.

### Likes

- Off by default for the same reason as comments.

## What the package never does

No sign-in handling, no browser against linkedin.com, no message reading, no invitation sending, no profile editing, no disguise. See `docs/references/compliance.md`.

## How acknowledgements work

- `profile-wrap config ack <action>` asks you to type a fixed sentence. It stores the date and the sha256 of this page and `compliance.md`.
- If an update changes either page, the hash no longer matches. The action goes back to draft or notify, and `profile-wrap doctor` and the board say so, until you accept the new text.
- Upgrades never silently weaken a safety setting.

## If something goes wrong

- Run `profile-wrap pause --all` to stop every job and API call. Run `profile-wrap schedule remove` to remove the scheduled jobs.
- A post marked `needs_check` may or may not be live. Open LinkedIn, look, then confirm with `profile-wrap post <slug> --resolve --posted` or `--not-posted`. The package never reposts on its own.
- To stop using the API entirely, remove the app's token from the config directory and delete the app in LinkedIn's developer portal.
