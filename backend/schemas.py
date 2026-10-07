"""Request/response pydantic models."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.modes import MODES


def _known_mode(value: Optional[str]) -> Optional[str]:
    """Reject an unknown mode id rather than silently running as the default —
    a typo in the UI should be loud, not a quiet change of persona."""
    if value is not None and value not in MODES:
        raise ValueError(f"unknown mode: {value}")
    return value


class LoginIn(BaseModel):
    password: str


class SessionPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    mode: Optional[str] = Field(None, max_length=40)

    @field_validator("mode")
    @classmethod
    def _mode_ok(cls, value: Optional[str]) -> Optional[str]:
        return _known_mode(value)


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
    # Omitted means "keep whatever mode the session already has" — an older
    # client that knows nothing about modes must not reset a Teacher chat.
    mode: Optional[str] = Field(None, max_length=40)
    regenerate: bool = False
    # Edit-and-resend: rewrite this stored user message and drop everything after
    # it before running the turn. Mutually exclusive with `regenerate`.
    edit_message_id: Optional[str] = None

    @field_validator("mode")
    @classmethod
    def _mode_ok(cls, value: Optional[str]) -> Optional[str]:
        return _known_mode(value)
