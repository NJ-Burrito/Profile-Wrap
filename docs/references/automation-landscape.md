# LinkedIn automation landscape

Retrieved 2026-10-12; re-verify before each release.

This survey covers the kinds of tools people use to automate LinkedIn activity (comments, reactions, posting, messaging), what LinkedIn's published rules say about each kind, and where this package stands. It is a reference, not a recommendation to automate anything.

Quotes are verbatim from the cited page at retrieval time. Where a quote's date is not shown on the page, it is marked "date not verified".

## Categories of tools

### 1. Official API (LinkedIn partner programs)

- **Share on LinkedIn** (the `w_member_social` permission): lets an app publish posts for a member. Comment and reaction endpoints under the same product have been returning 403 errors with codes such as `partnerApiSocialActions.CREATE` and `partnerApiReactions.CREATE` since 2024. Forum reports from 2024, 2025 and 2026 describe the same error family.
- **Community Management API**: a vetted partner product that covers comments, reactions and reads on Pages and some member content. Development tier comes first, then Standard after review.
- **Eligibility, per LinkedIn's migration guide (Microsoft Learn, LinkedIn Community Management API, version li-lms-2026-06, retrieved 2026-10-12):**
  - "At this time, our Community Management APIs are only available to registered legal organizations for commercial use cases only."
  - "Personal email addresses won't pass the vetting process."
  - A verified Page for the organization is required.
- Development tier limits stated in the same guide: 500 calls per app per 24 hours, 100 per member per 24 hours.
- LinkedIn publishes no review turnaround for Development tier. Third-party guesses range from days to four weeks; treat them as unverified.
- No public first-hand report of approval for a one-person or personal project was found. Reddit and Hacker News were not indexed by the search tools used, so "not found" there means not indexed, not nonexistent.

### 2. Scheduling and publishing platforms (official API underneath)

Commercial and self-hosted schedulers connect to LinkedIn through the official API, usually for Page or organization accounts. Pricing is typically a monthly subscription. Their comment or inbox features depend on the same Community Management API approval as any other app. Whether they are permitted for a given use depends on the approval the platform itself holds.

### 3. Browser extensions and cloud browser SaaS

Tools that click, type and scroll inside the user's logged-in LinkedIn page, or run a hosted browser on the user's behalf, to send connection requests, messages or comments. These act through the web interface rather than the API. Most are paid.

### 4. Session-based tools

Tools that act as the user's logged-in session, using stored session tokens or the user's sign-in details, and call LinkedIn's internal web endpoints. Some expose their functions to AI assistants through a wrapper. Hosted versions present a single API to developers, but the underlying mechanism is still the user's session.

### 5. Unofficial API wrappers

Open-source libraries that reproduce LinkedIn's internal web API calls. Their own READMEs say so. The `linkedin-api` library's README states that its use "would violate Linkedin's Terms of Use" (GitHub README, date not verified). Its author states they are not responsible for accounts being restricted.

### 6. Scripted UI and login bots

Mobile or desktop UI automation (Appium, Selenium, Playwright) that logs in with a member's sign-in details and drives the app. Some publish features for spreading requests across proxies or pacing them to avoid being flagged. Those features are a detection-avoidance mechanism and are not part of any approach this package supports.

### 7. AI drafting with a human click

The AI writes a draft. A person reads it, edits it if needed, and clicks Post. No LinkedIn action is taken without that click. Every source surveyed agrees this is the lowest-risk approach. It is also the only category this package integrates.

## What the rules say, by category

| Category | Published rule or statement | Source and date |
|---|---|---|
| Official API | Use only under the app's approved products and the member's consent. Community Management API is for registered legal organizations, commercial use. | Microsoft Learn migration guide, retrieved 2026-10-12 |
| Session-based and unofficial wrappers | Stated by the library authors as a breach of LinkedIn's terms. | Library READMEs, date not verified |
| Browser and login bots | Restriction notices collected from vendors cite profile-view volume and "viewing patterns that indicate the use of an automated tool". No LinkedIn-published rule on comment-only automation was found. | Vendor-quoted notices, date not verified |

Ban rates quoted by commercial sources are unverified and are not cited here as fact.

## How this package is positioned

1. **Official API only.** Nothing in this package logs in as a member, reads session tokens, or drives a browser. An approved Community Management API app is the only route that could post comments or reactions. Until one is approved, the package works in draft mode.
2. **Draft first.** Every comment or reaction starts as a draft file for review.
3. **Human gates.** A person approves each action before it is sent. The package does not schedule unattended engagement.
4. **No disguise.** The package does not hide that it is software, does not rotate identities or networks, and does not try to avoid LinkedIn's detection systems.

## Not supported by this package

The package will never integrate the following. Vendor and project names appear only in this section.

- **Session-based services that run as the user's logged-in account**: Unipile (API and its MCP and workflow wrappers), and any similar hosted session service.
- **Unofficial API libraries**: `linkedin-api` by tomquirk and its forks, and any library that calls LinkedIn's internal web endpoints.
- **Session-mode MCP servers**: the session mode of southleft/linkedin-mcp. Its OAuth mode is official, but this package does not depend on it.
- **Browser extensions and cloud-browser SaaS**: Expandi-class and Waalaxy-class tools, Ligo, and Chrome comment-automation extensions sold on marketplaces.
- **Scripted UI and login bots**: Android or desktop bots that log in with a member's sign-in details, and any tool that advertises proxy rotation or request pacing to avoid detection.
- **Paid partner platforms used as a route around the API gate**: Publora, Zernio, SocialPilot, Publer and ContentStudio inbox features.
- **Browser automation libraries used on LinkedIn**: Selenium or Playwright scripts that like or comment on LinkedIn pages.

## Open questions

- Whether the legacy `/v2/socialActions` comment endpoint accepts a Share-on-LinkedIn-only token today. Not tested; not supported by this package until verified against LinkedIn's own documentation.
- Whether LinkedIn's Marketing API version sunset on 2026-10-15 removes the legacy endpoints. Not verified against the changelog.
- Whether a personal or one-person Page can be approved for Development tier. No public record found.
- Real review times for Development tier. No LinkedIn figure published.
- Real restriction rates for comment-only automation. Not sourced from LinkedIn.

## Sources

- LinkedIn, Community Management API migration guide, Microsoft Learn (version li-lms-2026-06): https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-api-migration-guide?view=li-lms-2026-06
- LinkedIn API partner support guide, Microsoft Learn: https://learn.microsoft.com/en-us/linkedin/shared/linkedin-api-partner-support-guide
- Make community forum, 403 on comment and reaction endpoints (2024 and 2025 threads): https://community.make.com/t/cant-create-a-comment-on-a-linkedin-post-anymore/32176 ; https://community.make.com/t/403-permissions-error-linkedin-repost-like-commenting/88270
- Make community forum, Community Management API approval stall (2025): https://community.make.com/t/linkedin-oauth-errors-and-making-comments-how-have-you-overcome-them/85484

Not legal advice. Read the current terms yourself.
