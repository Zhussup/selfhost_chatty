"""GET /api/images/{image_id} — the bytes of a stored attachment.

Behind the same cookie auth as the rest of /api: the id is unguessable, but the
image is still the user's private data, so it is not served anonymously.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend import auth as auth_mod
from backend import db
from backend.config import settings

router = APIRouter(prefix="/images", dependencies=[Depends(auth_mod.require_user)])


@router.get("/{image_id}")
async def get_image(image_id: str) -> Response:
    row = db.one("SELECT mime, bytes FROM message_images WHERE id=?", (image_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="image not found")
    # The id is a UUID and the bytes never change, so the response is immutable.
    return Response(
        content=row["bytes"],
        media_type=row["mime"] or "application/octet-stream",
        headers={"Cache-Control": f"private, max-age={settings.image_serve_max_age}, immutable"},
    )
