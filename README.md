<div align="center">

<img src="docs/assets/hero.gif" alt="Profile-Wrap turns an idea into a checked LinkedIn post. You tap Allow." width="640">

# Your LinkedIn, on autopilot.

# You stay the boss.

### Pick how you want it. All free. 👇

| 🧩 Plugin | 🧠 Skills | 🔌 MCP server | 🖥️ Desktop app |
|:---:|:---:|:---:|:---:|
| For **Claude Code** and **Codex** | For any AI agent that reads skills | For any app that speaks MCP | No AI app? Use this |
| [Install ↓](#plugin) | [Install ↓](#skills) | [Install ↓](#mcp) | [Download ↓](#app) |

</div>

<a id="plugin"></a>

## 🧩 Plugin

Needs [uv](https://docs.astral.sh/uv/) once: `uv tool install profile-wrap`

Claude Code, type these two lines:

```
/plugin marketplace add NJ-Burrito/profile-wrap
/plugin install profile-wrap@profile-wrap
```

Codex: `codex plugin marketplace add NJ-Burrito/profile-wrap` ([Codex guide](docs/CODEX.md)).

Then say: **"set up Profile-Wrap"**. Claude Code gets 5 skills, 6 commands and the MCP server in one go.

<a id="skills"></a>

## 🧠 Skills

5 skills: **setup**, **plan**, **write**, **visuals**, **ship**.

Get them on [Smithery](https://smithery.ai/skills/naderalzghoulbusiness), or copy the [`.agents/skills`](.agents/skills) folder into your agent.

<a id="mcp"></a>

## 🔌 MCP server

8 tools: check your setup, see your calendar, draft a post, check facts, read your board, and post only what you allowed. Needs [uv](https://docs.astral.sh/uv/).

```
claude mcp add profile-wrap -- uvx profile-wrap-mcp
```

Other apps: [MCP guide](docs/MCP.md). Also on the [MCP Registry](https://registry.modelcontextprotocol.io).

<a id="app"></a>

## 🖥️ Desktop app

[🪟 Windows](https://github.com/NJ-Burrito/profile-wrap/releases/latest) · [🍎 Mac (Apple chip)](https://github.com/NJ-Burrito/profile-wrap/releases/latest) · [💻 Mac (Intel chip)](https://github.com/NJ-Burrito/profile-wrap/releases/latest) · [🐧 Linux](https://github.com/NJ-Burrito/profile-wrap/releases/latest)

Not sure which Mac you have? Click the Apple menu, then About This Mac.

## 3 steps (any of the four)

1️⃣ **Install** it

2️⃣ **Ask** for your week of posts

3️⃣ **Tap Allow** on each post you like

That is all.

Stuck? [Step-by-step guide with pictures of what you will see](docs/INSTALL-DESKTOP.md)

![Your review board: every post waits here until you tap Allow](docs/assets/board.png)

👆 Your board. Every post waits here until you say go.

## What it does for you

📅 Plans your week of posts

✍️ Writes them in your voice

🔑 Uses your own ChatGPT, Claude or Gemini account

✅ Checks every post before it goes out

👀 Shows you each one first. You approve.

⏰ Posts at a good time

🌍 Works in English and Arabic

## Is it safe?

🔒 It uses LinkedIn's own official way in

🙈 It never asks for your LinkedIn password

📭 It never reads your private messages

🛑 Nothing goes out unless you tap Allow

🆓 Free, and you can stop it any time

## Questions

**Is it free?**
Yes. The app is free. Writing uses your own AI account (ChatGPT, Claude, Gemini, or a free local one).

**Do I need to code?**
No. Install, ask, tap. That is it.

**Which one should I pick?**
Use Claude Code or Codex? Take the plugin. Another AI app? The MCP server. None? The desktop app.

**Mac or Windows?**
Both. Linux too.

**Arabic?**
Yes. Arabic and English, side by side.

**What if I don't like a post?**
Tap Reject, or ask for a better one. Nothing posts without you.

<br>

[For developers →](docs/FOR-DEVELOPERS.md)

Profile-Wrap is not affiliated with or endorsed by LinkedIn. Free and open source under the [MIT licence](LICENSE).
