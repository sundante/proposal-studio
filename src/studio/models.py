"""Shared pydantic models used across modules."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Cite(BaseModel):
    """A citation into a source document: heading path and page (or slide) number."""

    model_config = ConfigDict(extra="forbid")

    section: str
    page: int | None = None

    def __str__(self) -> str:
        return f"[{self.section}, p.{self.page}]" if self.page is not None else f"[{self.section}]"
