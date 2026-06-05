"""Pydantic schemas for the feed module — extracted from the legacy main.py."""
from pydantic import BaseModel


class FlagFeedPayload(BaseModel):
    item_id: str


class ModActionPayload(BaseModel):
    item_id: str
    item_type: str  # 'feed' or 'question'
    action: str     # 'approve', 'flag', 'remove'
