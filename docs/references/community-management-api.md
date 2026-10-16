# LinkedIn Community Management API: reference

Retrieved 2026-10-12; re-verify before each release.

Scope: a generic reference for developers of a free, personal-use LinkedIn tool. It explains what the Community Management API is, why reading analytics and comments and writing social actions is partner-gated, and what this package therefore does.

Evidence labels used below:
- [V] verified in this package's code or tests.
- SECONDARY: quoted from LinkedIn/Microsoft developer documentation as summarized in a prior review; re-read the live page before reuse.
- INFERRED: reasoning from the documents, not stated by them.
- [U] unknown, not verified.

## 1. What the API is

The Community Management API is a vetted LinkedIn product. It covers member and organization social actions: commenting, replying, reacting, and reading comments and reactions on posts.

SECONDARY (LinkedIn Learn, Community Management API overview and permissions tables, pages updated 2026-04 to 2026-08):
- `w_member_social_feed`: "Post, comment, and react on posts on behalf of an authenticated member."
- `r_member_social_feed`: "Restricted ... This permission is granted to select developers only."
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access

SECONDARY (migration guide, updated 2026-05-15): comment and reaction create/delete calls moved from `w_member_social` to `w_member_social_feed`.
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-api-migration-guide

Older text on the getting-access page still lists `w_member_social` as covering comments and likes. INFERRED: that wording is stale, because the migration guide and current permission tables place these actions under `_feed`.
- Source: https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access

## 2. Eligibility for a personal app

SECONDARY (Community Management app review page, revised 2026-02-11):
- "At this time, our Community Management APIs are only available to registered legal organizations for commercial use cases only."
- "Personal email addresses won't pass the vetting process."
- "LinkedIn reserves the right to review applications and select partners at its discretion and a partner might not be upgraded even if they meet these minimum requirements."
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review

SECONDARY (Quick start, Step 1): create a LinkedIn Page, then a developer application.
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/quick-start

SECONDARY (Community Management overview, FAQ): "`r_member_social` is a **closed** permission. We're not accepting access requests at this time due to resource constraints."
- Source: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview

INFERRED: a personal developer without a registered organization does not meet the documented Development tier criteria. No document addresses sole proprietors [U].

Development tier limits (SECONDARY, increasing-access page): 500 API calls per app per 24 hours, 100 per member per 24 hours, no BATCH_GET, no social-action webhooks.

## 3. Why a personal app cannot rely on it

- Reading comment text and authors on your own member posts through this API is not available to a personal app. Aggregate counts through member post analytics are a separate, approvable permission [U for personal use].
- Writing comments, replies and reactions requires `w_member_social_feed`, which is gated by the vetting above. Without it the API returns 403 on those routes [V for the package's test attempt; exact error code not reproduced here].
- No free official route to these actions was found [U beyond the docs read].

## 4. Terms that limit automation

SECONDARY (LinkedIn API Terms of Use, last revised 2022-12-13; fetched through a summarizing tool, quotes capped):
- General restrictions include using "the Content or the APIs to automate posting on the LinkedIn Services."
- Scraping or crawling LinkedIn content outside the APIs is prohibited.
- Source: https://www.linkedin.com/legal/l/api-terms-of-use

SECONDARY (User Agreement, section 8.2): bots or unauthorized automated methods that "comment on, like, share, or re-share posts" are banned.
- Source: https://www.linkedin.com/legal/

INFERRED: a fully unattended agent that comments or reacts is at risk under these terms even with approval. A human-initiated design (a person chooses each action and approves it) matches the documents better. Whether comments or reactions count as "posting" under the API Terms is not defined in the text read [U].

## 5. What this package does

- [V] The package has no invitation, messaging or direct-message read code.
- [V] Comments and likes through `/v2/socialActions` exist only in an experimental extra. The extra is off by default, requires a typed acknowledgement, and requires a selftest younger than 30 days before it runs.
- [A] That endpoint is undocumented and may be closed by LinkedIn at any time.
- Analytics are imported manually from the LinkedIn Analytics export. No live analytics API call is made by default.
- Engagement is draft-first: the package writes drafts, and a person decides whether to send anything.
- Social actions are available only through the experimental opt-in extra described above.

## 6. Unknowns

- [U] Whether any `/rest` or `/v2` social-action path accepts `w_member_social` alone. Other API versions were not tested.
- [U] Whether a member-actor comment is allowed on a post the actor does not own. The docs are silent on ownership.
- [U] Exact access-request questions and free-text limits; the form sits behind login and was not reviewed.
- [U] Whether the API Terms "automate posting" clause reaches comments, reactions, or scheduled own-account posts. Only LinkedIn can say; a Developer Support ticket is the route.
- [U] Whether a sole proprietor with a business email, Page and website could pass "registered legal organization" vetting.
- [U] Review turnaround for Development tier. Not documented on the pages read.
- [U] Which of the `r_member_social_feed` and `r_organization_social_feed` permissions governs social-metadata reads on a member-owned post.
- [U] Whether the endpoint in section 5 remains available.

## Sources (retrieved 2026-10-12)

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/reactions-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/social-metadata-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-api-migration-guide
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review
- https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access
- https://learn.microsoft.com/en-us/linkedin/marketing/quick-start
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- https://www.linkedin.com/legal/l/api-terms-of-use

Not legal advice. Read the current terms yourself.
