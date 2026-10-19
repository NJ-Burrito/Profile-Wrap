# Model providers and API keys

Profile-Wrap can draft text through your own Claude Code install (the default since 0.1) or through
an API key you own. Pick one with `profile-wrap providers use`. Profile-Wrap never ships a key,
never pools or resells keys, and never proxies your requests: each call goes from your machine
to the provider you chose.

| id | what it talks to | key needed | default model (edit it) |
|---|---|---|---|
| `claude-code` | your installed, unmodified `claude` CLI, through `claude_runner` | no | `sonnet` alias |
| `anthropic` | Anthropic Messages API | yes | `claude-sonnet-5-5` |
| `openai` | OpenAI chat completions | yes | `gpt-4o-mini` |
| `openrouter` | OpenRouter chat completions | yes | `openrouter/auto` |
| `ollama` | local server at `http://localhost:11434/v1` | no | `llama3.2` |
| `gemini` | Gemini native `generateContent` | yes | `gemini-2.5-flash` |

The default model names are starting points, not a recommendation, and were not checked against each
vendor's live model list. Set the one you want: `profile-wrap providers use openai --model <name>`.
`--base-url` points an adapter at a self-hosted or proxied endpoint (https, or http on localhost).

## Commands

```text
profile-wrap providers list                   # providers, key state (last 4 characters), the one in use
profile-wrap providers set-key openai         # hidden prompt; or --stdin to read one line from a pipe
profile-wrap providers use openai --model X   # records provider and model in config/providers.json
profile-wrap providers test [openai]          # one cheap call; prints PASS/FAIL and the status code
```

A key is never taken from the command line (it would land in shell history). `config/providers.json`
holds the provider id, model and optional base URL only; it is not a config section, so
`profile-wrap config validate` ignores it.

## Where keys live

1. **OS keychain** through the optional `keyring` package: macOS Keychain, Windows Credential
   Locker, Linux Secret Service or KWallet. Install with `uv pip install keyring`.
2. **Environment variable** `PROFILE_WRAP_<PROVIDER>_API_KEY` (for example
   `PROFILE_WRAP_ANTHROPIC_API_KEY`; hyphens become underscores). Use this on a headless Linux
   machine, in CI, and for scheduled jobs.

Reads try the keychain first, then the variable. Reads never prompt, so a scheduled job cannot hang
on a locked keychain: with no key it exits non-zero and prints the exact fix, for example

```text
FAIL anthropic: missing_key: no API key for anthropic. Run `profile-wrap providers set-key anthropic` or set the environment variable PROFILE_WRAP_ANTHROPIC_API_KEY.
```

Writes go to the keychain only. If there is none, `set-key` refuses and names the variable.
A key is never written to a config file, the ledger, a log, board data, the demo data or an error
message; errors from a provider have key-shaped text and the key itself replaced by `[REDACTED]`.
`profile-wrap leaks scan` flags the shapes `sk-`, `sk-ant-`, `sk-or-v1-` (OpenRouter) and `AIza`
(Gemini) in any file (rules in `profile_wrap/providers/keypatterns.py`).

## Interface

`provider.complete(system, messages, *, json_schema=None, tools=None, max_tokens=1024, timeout=60)`
returns `Result(text, usage, raw_id, provider, model)`. No streaming. `messages` is a list of
`{"role": "user"|"assistant", "content": str}`. `json_schema` asks for JSON: OpenAI-compatible servers
get `response_format`, Anthropic and Gemini get the schema in the instructions (Gemini also asks for a
JSON MIME type); the caller still validates the reply. `tools` is reserved: the API adapters refuse it
with `unsupported`; tool-using or file-editing jobs stay on `claude-code`.

Failures raise `ProviderError(kind, message, status)` with kind `missing_key`, `auth`, `rate_limit`,
`server`, `network`, `timeout`, `bad_response`, `unsupported` or `config`.

## Terms in short

- `claude-code` starts the user's own unmodified `claude` binary and never reads, copies or stores
  Claude sign-in tokens. Subscription users need no API key.
- Every API key belongs to the person running Profile-Wrap and bills to them. Use project-scoped keys
  with a spend limit where the provider offers it; for Gemini create a key restricted to the Gemini API.
- Never put a key in a repository, a screenshot or a shared workspace folder.

## Not done / not verified

- Live calls to the real vendor APIs were not made; the adapters are tested against local mock
  servers shaped like the documented request and response formats.
- Gemini through its OpenAI-compatible endpoint is **not** offered: the endpoint URL was not verified.
  The native adapter is the only Gemini path.
- Scheduler wiring (`schedule/runner.py` mapping a job to `provider:<id>`) is outside this package and
  not done here.

## Reading providers (LinkedIn pages, not AI models)

`engagement.reading.provider` chooses how Profile-Wrap reads post comments and counts:

| Provider | Cost | Needs | Limits |
| --- | --- | --- | --- |
| `manual` (default) | free | you paste the numbers | none |
| `apify` | free monthly credit (about $5 on Apify's free plan), paid beyond it | `profile-wrap config ack apify`, `APIFY_TOKEN` | paced to the credit (below), `apify.max_calls_per_day` (20) |
| `tavily` | free plan, 1,000 credits a month | `profile-wrap config ack tavily`, `TAVILY_API_KEY` | paced to the month (below), 100 credits never spent |
| `public` | free | `profile-wrap config ack public` | `public.max_pages_per_day` (30, max 100), `public.gap_seconds` (at least 3) |

`apify` and `tavily` are used through `engagement.reading.providers` (below); `engagement.reading.provider` still
takes `manual`, `export`, `apify` or `public` for a single reader.

`public` reads the pages LinkedIn shows to anyone who is not signed in (`profile_wrap/linkedin/public_reader.py`):
`post_stats`, `post_comments` for a post URL and `profile_posts` for a profile you chose. A post page that answers
HTTP 999, 429 or 403 stops reading for the day. The request carries the neutral `profile-wrap/<version>` User-Agent and nothing else that pretends to be a browser, so guest pages may refuse it; the reader then stops and the chain moves on. Guest pages are rate-limited per address. Guest profile pages are rate-limited per IP, so reads are spread
across the day: `public.profile_max_per_run` (2), `public.profile_gap_minutes` (20, kept across runs) and
`public.profile_max_per_day` (12); a 999 on a profile page pauses profile reads for 6 hours. If the acknowledgement goes stale after an update to the risk text, reading drops back to
`manual` and `profile-wrap doctor` says so. Risk text: `docs/TERMS-AND-RISK.md`.

### Two free tools that complement each other: Apify and Tavily

Turn on either one, or both. When both are on they share the work instead of competing for it:

```json
{ "engagement": { "reading": {
    "providers": ["apify", "tavily", "public"],
    "apify":  { "token_env": "APIFY_TOKEN", "max_calls_per_day": 20 },
    "tavily": { "key_env": "TAVILY_API_KEY", "month_credits": 1000, "reserve_credits": 100, "cache_days": 3 } } } }
```

Run `profile-wrap config ack apify` and `profile-wrap config ack tavily` yourself, and put the token and the key in
environment variables (the config holds only their names; the examples here are placeholders such as
`TAVILY_API_KEY=tvly-xxxxxxxx`). A provider whose acknowledgement is missing or stale is skipped and `doctor` says so.

| Order | Reader | What it is good at | How it is paced |
| --- | --- | --- | --- |
| 1 | `apify` | same-day posts of a profile | Today's allowance is (credit left at the start of today - $0.05 reserve) / days left in Apify's billing cycle, so the free credit lasts the cycle. Unspent days roll forward. A refusal for credit ("usage limit") rests Apify until the cycle ends. The credit is read once a day with a free call. |
| 2 | `tavily` | fills the people and days Apify does not cover | A web search that finds posts about three days late. Today's allowance is (1,000 - 100 reserve - credits used before today this month) / days left in the calendar month. A search is cached for 3 days, full text is fetched one URL per call (1 credit each), and the ledger (`data/tavily_usage.json`) resets with the month. A ledger that cannot be read switches Tavily off; it is never reset to zero. |
| 3 | `public` | last resort | the limits above (profile pages: 2 a run, 20 minutes apart, 12 a day) |

Each person is read by the first reader that can answer. A reader that cannot (allowance used, no key, error) hands
over to the next. A reader that answers with an empty list ends the search for that person, so a quiet person is not
paid for twice. `public` may only be listed last. Code: `profile_wrap/linkedin/readers.py` (`build_chain`,
`ReadingChain`, `ApifyReader`, `TavilyReader`); both services are reached only through `profile_wrap/http.py`, and
`api.apify.com` / `api.tavily.com` stay blocked until their own acknowledgement is valid. Keys are read from the named
environment variable at the moment of the call and are never written to the config, a ledger or a log.
`profile-wrap doctor` lists both readers with what each may still spend today and makes no call.

Try it on one person: `profile-wrap read posts https://www.linkedin.com/in/<name>/` (add `--json` for machine output, `--text` to also buy full text for Tavily-found posts, 1 credit each).

Media posts are the one place where the post address and the comment address differ. If you turn on the experimental
comments extra, `create_comment` repeats a comment once with the `ugcPost` address LinkedIn names when it answers
400 `actual threadUrn: ...`; a second failure is reported, never looped.
