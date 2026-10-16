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
