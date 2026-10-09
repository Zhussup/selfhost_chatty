"""Request/response pydantic models."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.config import settings
from backend.modes import MODES

# Base64 inflates by 4/3; the cap here is a DoS guard, tighter ones live in attachments.
_MAX_ENCODED_IMAGE = int(settings.image_max_bytes * 4 / 3) + 4


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


class ImageIn(BaseModel):
    """One attachment: raw base64, no `data:` prefix. The real format is sniffed
    from the decoded bytes — nothing the client says about it is trusted."""

    data: str = Field(max_length=_MAX_ENCODED_IMAGE)
    name: Optional[str] = Field(None, max_length=200)
    width: Optional[int] = Field(None, ge=0)
    height: Optional[int] = Field(None, ge=0)


class ChatIn(BaseModel):
    session_id: Optional[str] = None
    model: str
    # Empty is allowed only together with images — see _content_or_images.
    content: str = ""
    # Photos to show the model. Only meaningful for a model whose /api/show
    # capabilities include "vision"; the chat route refuses them otherwise.
    images: Optional[list[ImageIn]] = Field(None, max_length=8)
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

    @model_validator(mode="after")
    def _content_or_images(self) -> "ChatIn":
        """An image-only message is legal; a completely empty one is not."""
        if not self.content.strip() and not self.images:
            raise ValueError("content is required unless images are attached")
        return self

    @field_validator("mode")
    @classmethod
    def _mode_ok(cls, value: Optional[str]) -> Optional[str]:
        return _known_mode(value)
