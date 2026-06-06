"""Pydantic schemas for the FAQ module."""
from pydantic import BaseModel
from typing import List, Optional

class FAQCategoryResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: str
    audience: Optional[str] = None
    source: Optional[str] = None
    reviewed_at: Optional[str] = None
    q_count: int

    class Config:
        from_attributes = True


class FAQItemResponse(BaseModel):
    id: int
    q_num: str
    question: str
    answer: str
    tags: List[str]

    class Config:
        from_attributes = True


class FAQCategoryDetailResponse(BaseModel):
    category: FAQCategoryResponse
    items: List[FAQItemResponse]
