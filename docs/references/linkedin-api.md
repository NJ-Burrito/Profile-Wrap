# LinkedIn official API: posting to your own personal profile

Retrieved 2026-10-10; re-verify before each release.

Scope: how the account owner posts to their own LinkedIn profile with LinkedIn's official API. Stats/analytics are out of scope for this package. Primary sources are Microsoft Learn (the host of LinkedIn's API docs) and linkedin.com. Anything from a third-party page is labelled SECONDARY. Items labelled INFERRED are our reading, not a quoted statement.

## Short answer

- Posting to your own profile is self-serve: add the "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect" products to a developer app, run a 3-legged OAuth flow with scopes `openid profile w_member_social`, then call `POST https://api.linkedin.com/rest/posts`.
- Access tokens last 60 days. Ordinary apps get no refresh token, so repeat the browser consent about every 60 days.
- Package facts [V]: the package calls only `/v2/userinfo`, `/rest/posts`, `/rest/images` and `/rest/documents`. It posts nothing without a ledger-first pending row, and it never retries a POST. Default redirect is `http://localhost:8765/callback`; default scopes are `openid profile w_member_social`.

## 1. Developer app setup

| Fact | Source (retrieved 2026-10-10) |
|---|---|
| "Share on LinkedIn" grants `w_member_social`; add it in the Developer Portal under the app's Products tab. | https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin |
| "Sign in with LinkedIn using OpenID Connect" grants `openid`, `profile`, `email`; add it from the Products tab. | https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2 |
| Both are Open Permissions (Consumer): "available to all developers, and may be added via self-service ... under the Products tab". | https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access |
| The redirect URL is set on the app's Auth tab. URLs must be absolute, parameters are ignored, and no `#` is allowed. The doc says "via HTTPS" and shows only https examples. | https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow (Step 1) |
| LinkedIn Help: a Page association is required "for certain functionality and products". No individual alternative is named. | https://www.linkedin.com/help/learning/answer/a1665329 (summary only) |
| The marketing quick-start (for Community Management and Ads, not Share) says step 1 is "Create a LinkedIn Page". | https://learn.microsoft.com/en-us/linkedin/marketing/quick-start |
| SECONDARY: some third-party guides say every developer app must be associated with a Page, even for personal posting. Not confirmed by primary docs. | Third-party guide (not cited further) |

Scopes: `openid`, `profile`, `w_member_social`. `email` is optional and omitted (least scope; the OAuth doc says to "request the least number of scope permissions").

Practical reading (INFERRED): the app-creation form may ask for a Page. Primary docs do not say a Page is mandatory for the two self-serve products. If the app shows "Verify", the Page super admin must approve the verification request. See U1.

## 2. OAuth 2.0 three-legged flow with a localhost redirect

Source for all rows: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow (page updated 2026-05-15).

| Item | Fact |
|---|---|
| Authorization URL | `GET https://www.linkedin.com/oauth/v2/authorization` with `response_type=code`, `client_id`, `redirect_uri`, `state`, `scope` (URL-encoded, space-delimited). |
| `redirect_uri` | Must match one registered on the Auth tab exactly. |
| Authorization code | "30-minute lifespan and must be used immediately". |
| Token endpoint | `POST https://www.linkedin.com/oauth/v2/accessToken`, `Content-Type: application/x-www-form-urlencoded`, with `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`. |
| Token lifetime | "Currently, all access tokens are issued with a 60-day lifespan" (`expires_in` 5184000 s). |
| Refresh token | "Programmatic refresh tokens are available for a limited set of partners." Otherwise, repeat the authorization. If the member is still logged in and the token has not expired, the consent screen may be skipped. |
| Scope change | "If you request a different scope than the previously granted scope, all the previous access tokens are invalidated." |
| Token tools | Developer Portal Token Generator and Token Inspector: https://learn.microsoft.com/en-us/linkedin/marketing/quick-start (Step 8). |

Localhost redirect: the doc shows only https examples and does not state whether `http://localhost:PORT/callback` is accepted. The package default is `http://localhost:8765/callback`. Not verified against primary docs; see U2. Documented fallbacks: the Postman callback `https://oauth.pstmn.io/v1/callback`, or the Developer Portal Token Generator (manual token, no redirect).

## 3. Member URN

Source: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2

- `GET https://api.linkedin.com/v2/userinfo` with `Authorization: Bearer <access token>` (requires `openid profile`).
- Response fields include `sub` ("Subject Identifier"), `name`, `picture`, `locale`, and optional `email`.
- The Share doc says the `author` is the "Person URN of the Member" and points to the OIDC page to retrieve it: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- INFERRED: author = `urn:li:person:` + `sub`. The doc never states this in one sentence; the first successful post confirms it. See U3.

## 4. Posting with the Posts API

Source for endpoint, headers and bodies: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api (page dated 2026-05-13).

Headers (all required): `Authorization: Bearer <token>`, `X-Restli-Protocol-Version: 2.0.0`, `Linkedin-Version: YYYYMM`, `Content-Type: application/json`. Per the versioning page: "No unversioned calls ... the latest version is not applied by default"; a missing or sunset version returns an error. Source: https://learn.microsoft.com/en-us/linkedin/marketing/versioning

Version (as of 2026-10-10):
- Latest published: `202609` (versioning page, updated 2026-09-16), sunset 2027-09-15.
- Older versions sunset on dates listed at https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations (updated 2026-09-16). For example, `202510` sunsets 2026-10-15.
- Recommendation: `202609`. A newer version may exist; not verified (U4).

Permissions: `w_member_social` is listed for Posts, Images, Documents and Multi-image: "Post, comment, and like posts on behalf of an authenticated member".

Success response: HTTP 201 with header `x-restli-id` holding the post URN (form `urn:li:share:DEMO000000` or `urn:li:ugcPost:DEMO000000`). The body is empty.

Public URL: the Posts API page shows `https://www.linkedin.com/feed/update/urn:li:ugcPost:DEMO000000/`. The same pattern with `urn:li:share:DEMO000000` is widely used, but the doc shows only the ugcPost form (U5).

Body examples. `<SUB>` is the `sub` from section 3.

(a) Text post
```json
{
  "author": "urn:li:person:<SUB>",
  "commentary": "Post text here",
  "visibility": "PUBLIC",
  "distribution": {
    "feedDistribution": "MAIN_FEED",
    "targetEntities": [],
    "thirdPartyDistributionChannels": []
  },
  "lifecycleState": "PUBLISHED",
  "isReshareDisabledByAuthor": false
}
```

(b) Single image. Step 1, Images API (https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api, dated 2026-06-24):
```
POST https://api.linkedin.com/rest/images?action=initializeUpload
{"initializeUploadRequest": {"owner": "urn:li:person:<SUB>"}}
```
Response 200: `value.uploadUrl` and `value.image` (an `urn:li:image:...` URN).
Step 2: send the file bytes to `uploadUrl` with the Bearer header. The Documents page and older Share page use `curl --upload-file` (HTTP PUT). The Images page defers to the legacy Assets page (U11).
Step 3: add to the post body:
```json
"content": { "media": { "altText": "describe the image", "id": "urn:li:image:<id>" } }
```
Limits: under 36,152,320 pixels; JPG, GIF or PNG; GIF up to 250 frames. `altText` max 4,086 characters, under 120 recommended. The caller must match the image owner. A token with only `w_member_social` cannot GET `rest/images` (write-only), so confirm an upload by posting, not by GET.

(c) Multi-image (https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api): minimum 2, maximum 20 images, non-sponsored only. Upload each image with the Images API first.
```json
"content": { "multiImage": { "images": [
  { "id": "urn:li:image:<id1>", "altText": "slide 1" },
  { "id": "urn:li:image:<id2>", "altText": "slide 2" } ] } }
```

(d) Document / PDF carousel (https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/documents-api, dated 2026-06-24):
```
POST https://api.linkedin.com/rest/documents?action=initializeUpload
{"initializeUploadRequest": {"owner": "urn:li:person:<SUB>"}}
```
Response: `value.uploadUrl` and `value.document` (an `urn:li:document:...` URN). Upload with `curl -i --upload-file file.pdf -H 'Authorization: Bearer <token>' "<uploadUrl>"`. Limits: "The file size can't exceed 100MB and 300 pages. The following file types are supported: PPT, PPTX, DOC, DOCX, and PDF." Post body:
```json
"content": { "media": { "title": "Example.pdf", "id": "urn:li:document:<id>" } }
```
Note: the Posts API table lists carousels as organic "No" and sponsored "Yes". A PDF document post is the organic way to get a swipe-through look; it is not the `carousel` content type.

Other types on the same page (not used by this package): Article, Video, Poll. Hashtags are plain `#tag`.

## 5. ugcPosts status and rate limits

| Claim | Source |
|---|---|
| "The Posts API replaces the ugcPosts API." | Posts API page above |
| Migration table lists ugcPosts among APIs being replaced, status "N/A" (no Active/Deprecated flag). | https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations |
| The Share on LinkedIn page (last updated 2023-12-14) still documents `POST /v2/ugcPosts`. | https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin |

Verdict: ugcPosts is superseded, but no hard sunset date was found (U6). Use `/rest/posts` for new work.

Rate limits:
- Share on LinkedIn page: Member 150 requests per day; Application 100,000 per day (UTC). The 150 figure is documented for ugcPosts.
- Generic doc: limits reset at midnight UTC; excess calls return 429; standard limits "are not published in documentation"; the app's own limits appear in the Developer Portal Analytics tab after one call. https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits
- The per-endpoint cap for `/rest/posts` is not published (U7). A post with images costs one call per step (initializeUpload, upload, post per asset), so a 10-image post can use roughly 21 calls.

## 6. User Agreement automation clauses

Source: https://www.linkedin.com/legal/user-agreement, Section 8.2 "Don'ts" (fetched 2026-10-10 via a page summary; verify wording against the live page before quoting it again, U10).

> "Use bots or other unauthorized automated methods to access the Services, add or download contacts, send or redirect messages, create, comment on, like, share, or re-share posts, or otherwise drive inauthentic engagement;"

> "Develop, support or use software, devices, scripts, robots or any other means or processes (such as crawlers, browser plugins and add-ons or any other technology) to scrape or copy the Services"

> "Override any security feature ... access controls or use limits of the Services"

Interpretation (INFERRED, not legal advice): the prohibition covers "unauthorized" automation. A script that calls the official Posts API with a token the member granted through the app's `w_member_social` consent is the documented, authorized channel. Browser-driving automation that clicks linkedin.com to post, or scraping LinkedIn pages, falls under the quoted clauses and should not be used. Keep the client secret and tokens private. The API Terms of Use say the access token "must be kept secure" (https://www.linkedin.com/legal/l/api-terms-of-use; not read directly, U10).

## Implementation recipe

Setup once, in the browser: create a Page if the form requires one; create the app at https://www.linkedin.com/developers/apps/new; add the products "Share on LinkedIn" and "Sign in with LinkedIn using OpenID Connect"; on the Auth tab add the redirect URL (default `http://localhost:8765/callback`, see U2). Store the client ID, client secret and tokens in a local env file outside any repository.

1. Authorize: open in the browser, listen on the localhost port for `code` and `state`, and verify `state`:
```
https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id=CID&redirect_uri=URLENC(REDIRECT)&state=RANDOM&scope=openid%20profile%20w_member_social
```
2. Exchange the code:
```
POST https://www.linkedin.com/oauth/v2/accessToken
Content-Type: application/x-www-form-urlencoded
grant_type=authorization_code&code=CODE&client_id=CID&client_secret=SECRET&redirect_uri=REDIRECT
-> {"access_token": "...", "expires_in": 5184000, "scope": "..."}
```
Record the issue date and renew before day 60 (renewal at about day 55 is a safe margin).
3. Identify the member: `GET https://api.linkedin.com/v2/userinfo` with the Bearer token. `AUTHOR = "urn:li:person:" + sub`. Cache it.
4. Headers for `/rest/*` calls: `Authorization: Bearer TOKEN`, `X-Restli-Protocol-Version: 2.0.0`, `Linkedin-Version: 202609`, `Content-Type: application/json`.
5. Text post: `POST https://api.linkedin.com/rest/posts` with body (a). Expect 201. `post_urn = response.headers["x-restli-id"]`; the public URL is `https://www.linkedin.com/feed/update/<post_urn>/`.
6. Image or multi-image: per file, `POST /rest/images?action=initializeUpload`; take `value.uploadUrl` and `value.image`; send the bytes to `uploadUrl` with HTTP PUT and the Bearer header; then post with `content.media` (one image) or `content.multiImage.images` (2 to 20).
7. PDF carousel: the same with `POST /rest/documents?action=initializeUpload`, `value.document`, then `content.media {title, id}`. Max 100 MB, 300 pages.
8. Python sketch: `requests.put(upload_url, data=open(p, "rb"), headers={"Authorization": f"Bearer {tok}"})`; check `status_code in (200, 201)`.
9. Never retry a POST blindly: one POST creates one public post. The package never retries a POST and writes a ledger row before any post. Only the account owner runs the posting step.
10. Stats: not covered by this package. Use LinkedIn's own analytics export in the web UI.

## Unknowns

- U1. Whether the app-creation form strictly requires a Page for a personal-only app. Primary docs are silent on individuals; some third-party sources say yes. Also whether the app must be Page-verified before the two products work.
- U2. Whether `http://localhost:PORT/callback` is accepted as a redirect URL. Docs say "via HTTPS" and show only https. Test in the portal; the fallback is the Developer Portal Token Generator.
- U3. The docs never state in one sentence that `sub` equals the numeric part of `urn:li:person:`. Confirm on the first call.
- U4. Whether a version newer than `202609` is live. Latest page seen lists 202609 as of 2026-09-16.
- U5. The public permalink form is documented only as `https://www.linkedin.com/feed/update/urn:li:ugcPost:DEMO000000/`; the `urn:li:share:DEMO000000` form is widely used but not shown in these docs.
- U6. No hard sunset date found for `ugcPosts`; the migration table lists it as replaced with status N/A.
- U7. The per-endpoint daily cap for `/rest/posts`, `/rest/images` and `/rest/documents` is not published. The only documented figure is 150 per member per day for ugcPosts. Read the app's own limit in the Developer Portal after one call.
- U8. Not verified for this package: whether LinkedIn approves individuals for the Community Management API (analytics). Out of scope here.
- U9. Not verified for this package: columns of LinkedIn's own analytics export. Out of scope here.
- U10. The LinkedIn API Terms of Use and the full User Agreement were not read directly (summary fetch only). Re-read https://www.linkedin.com/legal/user-agreement and https://www.linkedin.com/legal/l/api-terms-of-use before quoting clause text in any public deliverable.
- U11. Exact method and headers for the binary upload to `uploadUrl` in the current Images API. The page defers to the legacy Assets page; the examples use `curl --upload-file` (HTTP PUT).
- U12. Not verified: whether API-created posts show up in LinkedIn's analytics export the same way as UI posts.

Not legal advice. Read the current terms yourself.
