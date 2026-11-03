# Start here — building Proposal Studio in VS Code with Claude Code

## 1. One-time setup (personal machine)
1. Install: VS Code, Git, Python 3.11+, the GitHub CLI (`gh`), and the **Claude Code** extension for
   VS Code. Sign in to Claude Code with your Claude Pro account.
2. `gh auth login` (so Claude Code can push branches and open PRs).
3. Create an empty folder `proposal-studio`, copy **everything in this kit** into it (including the
   hidden `.claude/` folder), and open the folder in VS Code.
4. In the VS Code terminal:
   ```
   git init -b main
   git add . && git commit -m "chore: project spec and build kit"
   gh repo create proposal-studio --public --source . --push
   ```
   (Use `--private` while building if you'd rather publish at v0.1.0.)

Kit contents:
| File | Purpose |
|---|---|
| `vibes/PROJECT_SPEC.md` | The full, decided design |
| `vibes/BUILD_PLAN.md` | Phases 0–10 that `/phase` reads |
| `CLAUDE.md` | Rules Claude Code loads automatically every session |
| `vibes/PROGRESS.md`, `vibes/DECISIONS.md` | State that carries across sessions |
| `.claude/commands/` | Slash commands: `/phase`, `/verify`, `/review`, `/resume`, `/ship` |

## 2. Kickoff prompt (paste into Claude Code once)

```
You're building Proposal Studio, an open-source, fully local and offline proposal workbench
(Open WebUI + Ollama + a Python package `studio`). Read CLAUDE.md, vibes/PROJECT_SPEC.md (fully),
vibes/BUILD_PLAN.md and vibes/PROGRESS.md now.

Don't write code yet. Reply with:
1. A 10-line summary of the architecture in your own words, so I can confirm you've understood it.
2. Up to 8 genuine ambiguities or risks in the spec that would change how you build Phases 0–3,
   each with your recommended resolution.
3. Anything in the target environment (Windows 11, no admin, no Docker, offline runtime, 16 GB
   CPU-only) you think the spec handles badly.

After I answer, record the resolutions in vibes/DECISIONS.md (and fix vibes/PROJECT_SPEC.md where needed),
commit as "docs: resolve pre-build ambiguities", and stop. We'll start with /phase 0 in a new session.
```

## 3. The build loop (one phase per session)
```
/clear
/phase 0          ← builds, tests, commits and pushes to `dev`
/review           ← strict self-review + fixes
```
Check CI is green on `dev`, then promote `dev` → `main` yourself when ready.
Repeat with `/phase 1` … `/phase 10`. Finish with `/ship 0.1.0`.

If a session runs out of usage mid-phase: in the next session run `/clear` then `/resume`.

## 4. Getting the most out of Claude Pro usage
- Use **Sonnet** for phases (`/model sonnet`). Switch to Opus only for a phase that gets stuck
  (Phase 7 or 8 are the likeliest), then back.
- `/clear` between phases. Within a long phase, `/compact` once if the context gets heavy.
- Use plan mode (Shift+Tab) only for Phases 7 and 8, where the VERIFY findings may change the approach.
- Don't paste logs or files into chat; point Claude at paths.
- Build only with the synthetic fixtures. **Never put a real RFP, client deck or your employer's
  template in this repo or a cloud tool.**

## 5. Using it at work (after v0.1.0)
1. On the work laptop, while online: download `proposal-studio-0.1.0-windows.zip` from the GitHub
   Release, unzip, run `scripts\setup.ps1`.
2. Put your template in `templates\`, run `studio template inspect templates\<file>`, and map the
   layouts in `config\layout_map.yaml` (docs/templates.md explains how).
3. Put past proposals in `library\proposals\` and reference docs in `library\reference\`, then run
   `/harvest` once and curate the blocks.
4. Go offline, run `scripts\start.ps1`, open http://localhost:8080 and pick **Proposal Studio**.

Before installing it at work, check that your firm allows open-source tools on work machines. It's
also worth making sure your employment terms are fine with you publishing a personal open-source
project in this area.
