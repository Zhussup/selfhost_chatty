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
    # The fragment of a previous answer the user replied to. Persisted on the
    # user row and folded back into the prompt by build_messages; ignored when
    # `regenerate` is set (the stored row already owns the quote).
    quote: Optional[str] = Field(None, max_length=2000)
    think: Optional[Literal["low", "medium", "high"]] = None
    use_tools: bool = True
    regenerate: bool = False
    # Edit-and-resend: rewrite this stored user message and drop everything after
    # it before running the turn. Mutually exclusive with `regenerate`.
    edit_message_id: Optional[str] = None