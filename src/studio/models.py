"""Shared pydantic models used across modules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Cite(BaseModel):
    """A citation into a source document: heading path and page (or slide) number."""

    model_config = ConfigDict(extra="forbid")

    section: str
    page: int | None = None

    def __str__(self) -> str:
        return f"[{self.section}, p.{self.page}]" if self.page is not None else f"[{self.section}]"


class Section(BaseModel):
    """A run of text under one heading path, from one page/slide of one source file."""

    model_config = ConfigDict(extra="forbid")

    file: str
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = None
    text: str
    kind: Literal["text", "table"] = "text"

    @property
    def section_label(self) -> str:
        """Heading path joined for citations; the file name if there are no headings."""
        return " > ".join(self.heading_path) or self.file


class Chunk(BaseModel):
    """A retrievable piece of a section, with everything needed to cite it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    file_hash: str
    section: str
    page: int | None = None
    text: str

    @property
    def cite(self) -> Cite:
        """Citation for this chunk."""
        return Cite(section=self.section, page=self.page)
