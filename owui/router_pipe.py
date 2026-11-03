"""
title: Proposal Studio
author: Proposal Studio contributors
version: 0.1.0
license: Apache-2.0
description: Local, offline proposal workbench (routes chat to the studio package).
"""

# Paste this file into Open WebUI → Admin Panel → Functions → New (or run `studio owui install`).
# It declares no pip requirements on purpose: `studio` is installed in the same venv instead.

from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        STUDIO_HOME: str = Field(
            default="",
            description="proposal-studio folder (config/, workspace/, library/). "
            "Empty: the STUDIO_HOME environment variable, else Open WebUI's working folder.",
        )
        AUTO_ROUTE: bool = Field(default=True, description="Route plain text automatically.")
        AUTO_THRESHOLD: float = Field(
            default=0.7, ge=0.0, le=1.0, description="Classifier confidence needed to auto-route."
        )

    class UserValves(BaseModel):
        DEFAULT_OPPORTUNITY: str = Field(
            default="", description="Opportunity to use in new chats (e.g. acme-2026)."
        )

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(
        self,
        body: dict,
        __user__: dict | None = None,
        __chat_id__: str | None = None,
        __files__: list | None = None,
        __event_emitter__=None,
        __event_call__=None,
        __task__: str | None = None,
    ):
        from studio.owui import PipeBridge, resolve_root

        user_valves = (__user__ or {}).get("valves")
        bridge = PipeBridge(
            resolve_root(self.valves.STUDIO_HOME),
            route_overrides={
                "auto_route": self.valves.AUTO_ROUTE,
                "auto_threshold": self.valves.AUTO_THRESHOLD,
            },
        )
        async for chunk in bridge.run(
            body,
            user=__user__,
            chat_id=__chat_id__,
            files=__files__ or [],
            emit=__event_emitter__,
            event_call=__event_call__,
            task=__task__,
            default_opportunity=getattr(user_valves, "DEFAULT_OPPORTUNITY", "") or "",
        ):
            yield chunk
