#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTION_BANK_PATH = ROOT / "data" / "question_bank.json"

def main():
    if not QUESTION_BANK_PATH.exists():
        print(f"Error: question bank not found at {QUESTION_BANK_PATH}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: failed to parse JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict) or "questions" not in data:
        print("Error: JSON root must be an object containing a 'questions' list", file=sys.stderr)
        sys.exit(1)

    questions = data["questions"]
    print(f"Loaded {len(questions)} questions.")

    errors = []
    seen_ids = set()

    for idx, q in enumerate(questions):
        loc = f"Question index {idx}"
        
        # Check required fields
        for field in ["id", "topic", "section", "difficulty", "type", "question", "options", "correct", "explanation"]:
            if field not in q:
                errors.append(f"{loc}: missing required field '{field}'")
        
        if "id" in q:
            qid = q["id"]
            loc = f"Question {qid}"
            if qid in seen_ids:
                errors.append(f"{loc}: duplicate ID found")
            seen_ids.add(qid)

            # Check difficulty & ID prefix prefix mapping
            if "difficulty" in q:
                diff = q["difficulty"]
                if diff not in ["beginner", "intermediate", "advanced"]:
                    errors.append(f"{loc}: invalid difficulty '{diff}'")
                else:
                    expected_prefix = {"beginner": "b", "intermediate": "m", "advanced": "a"}[diff]
                    if not qid.startswith(expected_prefix):
                        errors.append(f"{loc}: difficulty '{diff}' requires ID prefix '{expected_prefix}', got '{qid}'")

        if "type" in q and q["type"] != "mcq":
            errors.append(f"{loc}: only 'mcq' type is supported, got '{q['type']}'")

        if "options" in q:
            opts = q["options"]
            if not isinstance(opts, list) or len(opts) < 2:
                errors.append(f"{loc}: 'options' must be a list of at least 2 choices")
            
            if "correct" in q:
                correct = q["correct"]
                if not isinstance(correct, int) or correct < 0 or correct >= len(opts):
                    errors.append(f"{loc}: 'correct' index must be an integer between 0 and {len(opts)-1}, got {correct}")

    if errors:
        print(f"\nValidation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors[:20]:
            print(f"  - {err}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  - ... and {len(errors) - 20} more", file=sys.stderr)
        sys.exit(1)

    print("All questions validated successfully!")

if __name__ == "__main__":
    main()
