from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlatformModel(BaseModel):
    """Shared strict base model for platform schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class RetrievalQuery(PlatformModel):
    query: str = Field(min_length=1)
    top_k: int = Field(ge=1)


class RetrievedChunk(PlatformModel):
    text: str = Field(min_length=1)
    score: float


class RetrievalResponse(PlatformModel):
    chunks: list[RetrievedChunk]
