"""Pydantic schemas for the quiz module — extracted from the legacy main.py."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class StartQuizPayload(BaseModel):
    difficulty: str


class SubmitPayload(BaseModel):
    quiz_id: str
    answers: Dict[str, int]


class QuestionPayload(BaseModel):
    """Body for POST /api/admin/questions — used by QuizManagers to seed the bank."""
    id: str
    topic: str
    difficulty: str
    question: str
    options: List[str]
    correct_index: int
    explanation: Optional[str] = ""
    status: Optional[str] = "published"
