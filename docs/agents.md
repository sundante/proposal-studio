# Agents (`/agent`)

Proposal Studio can hand file tasks to a local agent CLI, for example "tighten the bullets in
deck.json" or "draft speaker notes for every slide". Every run is sandboxed, runs against
**local Ollama models only**, and changes nothing until you approve it twice.

## How a run works

```
/agent opencode tighten the platform slide bullets
```

1. **Plan:** the agent runs in a *throwaway copy* of the sandbox (`workspace/<opp>/agent/`),
   which holds copies of `deck.json`, `digest.json` and `outline.json`. You see its plan, and the
   copy is deleted, so nothing it does while planning survives.
2. **Apply** (after `/approve`): the agent runs again in a fresh working copy with permission to
   edit files there. You see which files changed and a diff.
3. **Copy back** (after a second `/approve`): changed `deck.json`/`digest.json`/`outline.json`
   replace the originals; the previous versions go to `history/`, and a changed `deck.json` must
   still be a valid deck. Any other new files go to `workspace/<opp>/agent/results/`.

In the app, type `/agent opencode <task>`; each step that changes files shows **Run** /
**Cancel** buttons. Agent commands can only be changed in `config/agents.yaml`, never from chat.
From a terminal: `studio agent opencode "<task>"`, which asks before each step (`--yes` skips the
questions).

**Safety defaults:**
- Shell access is off: opencode is configured with `bash: deny`, and Claude Code runs with
  `--restricted`.
- Each run gets an isolated HOME inside the sandbox, so agents can't read your real config or
  credentials.
- Only an allowlisted set of environment variables is passed on, plus the agent's own `env`.
  API keys in your shell are **not** passed.
- Cloud models are refused.
- Every run has a timeout (`default_timeout_s`, 15 min) and a log in
  `workspace/<opp>/agent/logs/`.

Be realistic: on a 16 GB CPU-only laptop each step takes minutes, and small local models
(qwen3:8b) often don't use their file tools well. Short, specific tasks work best.

## Supported agents

| Agent | Status | Install (user-level, online) |
|---|---|---|
| `opencode` | Verified (opencode-ai 1.19.5) | `npm install -g opencode-ai` (or a user prefix) |
| `claude-code` | Verified (2.1.317), via Ollama's Anthropic-compatible API | `npm install -g @anthropic-ai/claude-code` |
| `hermes` | **Disabled**: flags from the hermes-agent 0.19.0 source, not run-tested | `pip install hermes-agent` |

`/agent` (or `studio agent`) with no arguments lists them and says whether each is ready.

### OpenCode

The adapter writes an `opencode.json` into the working copy that sets up local Ollama as the
provider, turns off sharing and autoupdate, and denies web fetch and bash. It sets these env vars
so opencode makes no network calls: `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_DISABLE_AUTOUPDATE`,
`OPENCODE_DISABLE_LSP_DOWNLOAD`, `OPENCODE_DISABLE_DEFAULT_PLUGINS`,
`OPENCODE_DISABLE_EXTERNAL_SKILLS` and `OPENCODE_DISABLE_CLAUDE_CODE`.

### Claude Code (local)

This uses Ollama's Anthropic Messages endpoint:
`ANTHROPIC_BASE_URL=http://localhost:11434`, `ANTHROPIC_AUTH_TOKEN=ollama`,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` and `DISABLE_AUTOUPDATER=1`. Requests never leave
your machine. It may print a warning that it doesn't know the local model's context window;
that's harmless.

### Hermes Agent

It ships disabled, because a live offline run hasn't been verified yet. To try it, install it,
set `enabled: true` under `hermes` in `config/agents.yaml`, and test with a harmless task first.

## Adding or changing an agent

Edit `config/agents.yaml`. Each agent has `plan_cmd` and `apply_cmd` (argument lists with
`{prompt}`, `{model}` and `{workdir}` placeholders), `model` (must be local), optional `env`, and
`files` (written into the working copy; `{model}` is filled in). Check the CLI's own `--help`
before relying on a flag, and keep the plan command read-only where the CLI allows it.
