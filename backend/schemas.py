"""Request/response pydantic models."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    password: str


class SessionPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)


class ChatIn(BaseModel):
    session_id: Optional[str] = None
    model: str
    content: str = Field(min_length=1)
    think: Optional[Literal["low", "medium", "high"]] = None
    use_tools: bool = True
    regenerate: bool = False