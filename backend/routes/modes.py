"""GET /api/modes — the hardcoded mode registry, as the UI consumes it."""

from fastapi import APIRouter, Depends

from backend import auth as auth_mod
from backend.config import settings
from backend.modes import DEFAULT_MODE_ID, public_modes

router = APIRouter(prefix="/modes", dependencies=[Depends(auth_mod.require_user)])


@router.get("")
async def modes() -> dict:
    # formatted here, not at import: the warning quotes the live tool budget
    return {"modes": public_modes(settings.tool_max_iter), "default": DEFAULT_MODE_ID}
