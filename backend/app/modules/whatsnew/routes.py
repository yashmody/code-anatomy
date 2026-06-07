"""What's New routes — read-only library of Adobe updates for signed-in users."""
from fastapi import APIRouter, Depends

from app.core.deps import require_authenticated
from app.modules.whatsnew import storage as whatsnew_storage

router = APIRouter()


@router.get("/api/whatsnew")
async def list_whats_new(user=Depends(require_authenticated)):
    """Recent Adobe updates, newest first, grouped by product.

    Read-only; populated by the weekly content-refresh sync
    (`scripts/sync_adobe_updates.py`). Any signed-in user may read it.
    """
    items = whatsnew_storage.list_recent(limit=100)
    groups: dict[str, dict] = {}
    for it in items:
        g = groups.setdefault(it["product"], {"product": it["product"], "items": []})
        g["items"].append(it)
    # `items` is already newest-first, so first-seen product order is stable.
    return {"items": items, "groups": list(groups.values())}
