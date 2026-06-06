"""FAQ routing handlers."""
from fastapi import APIRouter, HTTPException

from app.core import cache, config
from app.modules.faq import storage as faq_storage
from app.modules.faq.schemas import FAQCategoryDetailResponse, FAQCategoryResponse

router = APIRouter()


@router.get("", response_model=dict[str, list[FAQCategoryResponse]])
async def get_faq_categories():
    """Retrieve all FAQ categories from the cache or DB."""
    ttl = getattr(config.settings, "cache_ttl_faq", 900)
    
    def _load():
        return faq_storage.get_all_categories()
        
    categories = cache.get_or_compute("faq_categories:all", ttl=ttl, loader=_load)
    return {"categories": categories}


@router.get("/{category_id}", response_model=FAQCategoryDetailResponse)
async def get_faq_category_detail(category_id: str):
    """Retrieve details of a specific FAQ category and its associated items from cache or DB."""
    ttl = getattr(config.settings, "cache_ttl_faq", 900)
    
    def _load():
        detail = faq_storage.get_category_detail(category_id)
        if not detail:
            return None
        return detail
        
    detail = cache.get_or_compute(f"faq_categories:{category_id}", ttl=ttl, loader=_load)
    if not detail:
        raise HTTPException(status_code=404, detail="FAQ category not found")
    return detail
