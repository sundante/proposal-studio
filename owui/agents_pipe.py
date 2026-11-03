"""
title: Proposal Studio Agents
author: Proposal Studio contributors
version: 0.1.0
license: Apache-2.0
description: One "Agent · …" model per local agent CLI, sandboxed with plan, approve and apply.
"""

# Paste into Open WebUI → Admin Panel → Functions → New (or run `studio owui install`).
# It declares no pip requirements on purpose: `studio` is installed in the same venv instead.

from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        STUDIO_HOME: str = Field(
            default="",
            description="proposal-studio folder. Empty: the STUDIO_HOME environment variable.",
        )

    def __init__(self):
        self.type = "manifold"
        self.valves = self.Valves()

    def pipes(self):
        from studio.owui import agent_models, resolve_root

        return agent_models(resolve_root(self.valves.STUDIO_HOME))

    async def pipe(
        self,
        body: dict,
        __user__: dict | None = None,
        __chat_id__: str | None = None,
        __event_emitter__=None,
        __event_call__=None,
        __task__: str | None = None,
    ):
        from studio.owui import PipeBridge, agent_from_model, resolve_root

        bridge = PipeBridge(resolve_root(self.valves.STUDIO_HOME))
        async for chunk in bridge.run(
            body,
            user=__user__,
            chat_id=__chat_id__,
            emit=__event_emitter__,
            event_call=__event_call__,
            task=__task__,
            agent=agent_from_model(body.get("model", "")),
        ):
            yield chunk
