"""A stand-in agent CLI for tests: `fake_agent.py <mode> <prompt>`.

Modes: plan (prints a plan; tries to write a file, which must not survive), apply (edits
deck.json and adds notes.md), sleep (hangs, for timeouts), env (prints visible env vars),
escape (tries to write outside its working copy via `..` and a symlink), fail (exit 3).
"""

import json
import os
import sys
import time
from pathlib import Path

mode, prompt = sys.argv[1], " ".join(sys.argv[2:])
cwd = Path.cwd()
if mode == "plan":
    print(f"PLAN for: {prompt}")
    print("1. retitle the platform slide")
    (cwd / "plan_side_effect.txt").write_text("should be discarded")
elif mode == "apply":
    deck = json.loads((cwd / "deck.json").read_text())
    deck["slides"][0]["title"] = "Retitled by agent"
    (cwd / "deck.json").write_text(json.dumps(deck, indent=2))
    (cwd / "notes.md").write_text("# Notes\\nDone.\\n")
    print("APPLIED")
elif mode == "sleep":
    print("sleeping", flush=True)
    time.sleep(60)
elif mode == "env":
    print("HOME=" + os.environ.get("HOME", ""))
    print("SECRET=" + os.environ.get("STUDIO_TEST_SECRET", "<absent>"))
    print("AGENT_FLAG=" + os.environ.get("AGENT_FLAG", "<absent>"))
elif mode == "escape":
    (cwd.parent / "escaped.txt").write_text("outside")
    target = cwd.parent.parent
    (cwd / "link").symlink_to(target)
    print("tried")
elif mode == "fail":
    print("boom")
    sys.exit(3)
