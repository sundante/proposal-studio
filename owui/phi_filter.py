"""
title: Proposal Studio PHI warning
author: Proposal Studio contributors
version: 0.1.0
license: Apache-2.0
description: Warns (or blocks) when a typed message looks like it contains PHI.
"""

# Paste into Open WebUI → Admin Panel → Functions → New, then enable it for the Proposal Studio
# model (or globally). Requires the `studio` package in the same Python environment.

from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        BLOCK: bool = Field(default=False, description="Block the message instead of only warning.")

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __event_emitter__=None) -> dict:
        from studio.owui import phi_warning

        warning = phi_warning(body)
        if warning and self.valves.BLOCK:
            raise Exception(f"{warning} The message was not sent.")
        if warning and __event_emitter__ is not None:
            await __event_emitter__(
                {"type": "status", "data": {"description": warning, "done": True}}
            )
        return body
