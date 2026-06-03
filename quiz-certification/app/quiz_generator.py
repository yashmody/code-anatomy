"""Quiz generator — samples questions from the bank.

Two quizzes are almost never alike: questions sampled randomly, options shuffled
per question, and as the bank grows, the combinatorial space grows with it.

The bank is the single source of truth. To add new topics, append questions to
data/question_bank.json. No code changes needed.
"""
import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from . import config


def _load_bank() -> List[Dict]:
    with open(config.QUESTION_BANK, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


def _topic_stats() -> Dict:
    """Used by the home page to show coverage."""
    bank = _load_bank()
    out = {"beginner": {}, "intermediate": {}, "advanced": {}}
    for q in bank:
        topic = q["topic"]
        diff = q["difficulty"]
        if diff not in out:
            out[diff] = {}
        out[diff][topic] = out[diff].get(topic, 0) + 1
    return out


def topic_summary() -> Dict:
    """Return a summary of available topics and counts."""
    bank = _load_bank()
    return {
        "total": len(bank),
        "beginner": sum(1 for q in bank if q["difficulty"] == "beginner"),
        "intermediate": sum(1 for q in bank if q["difficulty"] == "intermediate"),
        "advanced": sum(1 for q in bank if q["difficulty"] == "advanced"),
        "topics": sorted(set(q["topic"] for q in bank)),
    }


def generate(difficulty: str, count: int = None) -> Dict:
    """Generate a quiz: select questions, shuffle options, return a quiz envelope.

    Returns a dict with:
      - quiz_id (server-only)
      - questions: list of {id, question, options} — no correct answers
      - server_answers: dict {question_id: correct_index} — never sent to client
    """
    if difficulty not in ("beginner", "intermediate", "advanced"):
        raise ValueError(f"Invalid difficulty: {difficulty}")

    count = count or config.QUESTIONS_PER_QUIZ
    bank = _load_bank()
    pool = [q for q in bank if q["difficulty"] == difficulty]

    if len(pool) < count:
        raise ValueError(
            f"Not enough {difficulty} questions: have {len(pool)}, need {count}. "
            f"Add more to data/question_bank.json."
        )

    selected = random.sample(pool, count)

    # Shuffle options per question; keep a mapping from question_id -> correct index
    client_questions = []
    server_answers = {}
    full_questions = []  # for storage with explanations and metadata

    for q in selected:
        opts = list(q["options"])
        correct_value = opts[q["correct"]]
        # Shuffle
        shuffled = opts[:]
        random.shuffle(shuffled)
        new_correct = shuffled.index(correct_value)

        client_questions.append(
            {
                "id": q["id"],
                "question": q["question"],
                "options": shuffled,
                "topic": q["topic"],
            }
        )
        server_answers[q["id"]] = new_correct
        full_questions.append(
            {
                "id": q["id"],
                "question": q["question"],
                "options": shuffled,
                "correct_index": new_correct,
                "correct_text": correct_value,
                "topic": q["topic"],
                "section": q.get("section", ""),
                "difficulty": q["difficulty"],
                "explanation": q.get("explanation", ""),
            }
        )

    quiz_id = str(uuid.uuid4())
    return {
        "quiz_id": quiz_id,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "difficulty": difficulty,
        "duration_minutes": config.QUIZ_DURATION_MIN,
        "questions": client_questions,        # client-safe
        "server_answers": server_answers,     # server-only
        "full_questions": full_questions,     # for storage at submit time
    }


def grade(server_answers: Dict[str, int], user_answers: Dict[str, int]) -> Dict:
    """Grade a submission against server-stored answers."""
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
        "pass_mark": config.PASS_MARK_CORRECT,
        "passed": correct >= config.PASS_MARK_CORRECT,
        "per_question": per_question,
    }
