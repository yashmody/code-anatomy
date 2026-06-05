"""Quiz generator — samples questions from the PostgreSQL database.

Two quizzes are almost never alike: questions sampled randomly, options shuffled
per question, and as the bank grows, the combinatorial space grows.
Avoids repeat questions by reviewing user history, falling back to incorrect answers on exhaustion.
"""
import random
import uuid
import datetime
from typing import Dict, List

from sqlalchemy import select

from . import config
from .db import get_session
from .models import Question, Attempt


def topic_summary() -> Dict:
    """Return a summary of available published topics and counts from the DB."""
    with get_session() as session:
        questions = session.scalars(
            select(Question).where(Question.status == "published")
        ).all()
        
    if not questions:
        return {
            "total": 0,
            "beginner": 0,
            "intermediate": 0,
            "advanced": 0,
            "topics": [],
        }
        
    return {
        "total": len(questions),
        "beginner": sum(1 for q in questions if q.difficulty == "beginner"),
        "intermediate": sum(1 for q in questions if q.difficulty == "intermediate"),
        "advanced": sum(1 for q in questions if q.difficulty == "advanced"),
        "topics": sorted(set(q.topic for q in questions)),
    }


def generate(difficulty: str, user_email: str, count: int = None) -> Dict:
    """Generate a quiz dynamically:
    
    1. Select published questions that the user has NOT answered yet.
    2. Shuffles the options per question, keeping correct mappings server-side.
    3. Falls back to questions the user previously answered incorrectly if pool is low.
    4. Resets user question pool if there are still not enough questions.
    """
    if difficulty not in ("beginner", "intermediate", "advanced"):
        raise ValueError(f"Invalid difficulty: {difficulty}")

    count = count or config.QUESTIONS_PER_QUIZ
    
    with get_session() as session:
        # 1. Fetch user's answered question IDs from their attempts history
        attempts = session.scalars(
            select(Attempt).where(Attempt.user_email == user_email)
        ).all()
        
        answered_ids = set()
        for a in attempts:
            payload = a.payload or {}
            user_answers = payload.get("user_answers", {})
            answered_ids.update(user_answers.keys())
            
        # 2. Query published questions of the chosen difficulty, excluding answered ones
        query = select(Question).where(
            Question.difficulty == difficulty,
            Question.status == "published"
        )
        if answered_ids:
            # SQLAlchemy not_in requires a non-empty sequence
            query = query.where(Question.id.not_in(list(answered_ids)))
            
        pool = list(session.scalars(query).all())
        
        # 3. Exhaustion Fallback Phase A: Prioritize wrong answers
        if len(pool) < count:
            wrong_ids = set()
            for a in attempts:
                payload = a.payload or {}
                grading = payload.get("grading", {})
                for qid, res in grading.items():
                    if not res.get("is_correct", False):
                        wrong_ids.add(qid)
            
            if wrong_ids:
                # Select previously wrong answers that aren't already in our pool
                current_pool_ids = {q.id for q in pool}
                wrong_query = select(Question).where(
                    Question.id.in_(list(wrong_ids)),
                    Question.difficulty == difficulty,
                    Question.status == "published"
                )
                if current_pool_ids:
                    wrong_query = wrong_query.where(Question.id.not_in(list(current_pool_ids)))
                
                wrong_pool = session.scalars(wrong_query).all()
                pool.extend(wrong_pool)

        # 4. Exhaustion Fallback Phase B: Completely reset the pool (allow any published)
        if len(pool) < count:
            reset_query = select(Question).where(
                Question.difficulty == difficulty,
                Question.status == "published"
            )
            pool = list(session.scalars(reset_query).all())

        if len(pool) < count:
            raise ValueError(
                f"Not enough {difficulty} questions in DB: have {len(pool)}, need {count}."
            )

        # Sample count questions
        selected = random.sample(pool, count)

        # Shuffle options per question; map ID to correct index
        client_questions = []
        server_answers = {}
        full_questions = []

        for q in selected:
            # Options are JSONB list, copy it
            opts = list(q.options)
            correct_value = opts[q.correct_index]
            
            # Shuffle options
            shuffled = opts[:]
            random.shuffle(shuffled)
            new_correct = shuffled.index(correct_value)

            client_questions.append(
                {
                    "id": q.id,
                    "question": q.question,
                    "options": shuffled,
                    "topic": q.topic,
                }
            )
            server_answers[q.id] = new_correct
            full_questions.append(
                {
                    "id": q.id,
                    "question": q.question,
                    "options": shuffled,
                    "correct_index": new_correct,
                    "correct_text": correct_value,
                    "topic": q.topic,
                    "difficulty": q.difficulty,
                    "explanation": q.explanation or "",
                }
            )

        quiz_id = str(uuid.uuid4())
        return {
            "quiz_id": quiz_id,
            "started_at": datetime.datetime.utcnow().isoformat() + "Z",
            "difficulty": difficulty,
            "duration_minutes": config.QUIZ_DURATION_MIN,
            "questions": client_questions,
            "server_answers": server_answers,
            "full_questions": full_questions,
        }


def grade(server_answers: Dict[str, int], user_answers: Dict[str, int],
          pass_mark: int = None) -> Dict:
    """Grade a submission against server-stored answers."""
    effective_pass_mark = pass_mark if pass_mark is not None else config.PASS_MARK_CORRECT
    total = len(server_answers)
    correct = 0
    per_question = {}
    
    for qid, correct_idx in server_answers.items():
        user_idx = user_answers.get(qid)
        is_correct = user_idx == correct_idx
        if is_correct:
            correct += 1
        per_question[qid] = {
            "user_answer_index": user_idx,
            "correct_answer_index": correct_idx,
            "is_correct": is_correct,
        }
        
    score = correct / total if total > 0 else 0.0
    return {
        "total": total,
        "correct": correct,
        "score": score,
        "pass_mark": effective_pass_mark,
        "passed": correct >= effective_pass_mark,
        "per_question": per_question,
    }
