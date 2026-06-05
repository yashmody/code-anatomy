"""
DEV ONLY — fast-quiz shim for certificate-generation testing.

Lets a developer complete a 2-question quiz and receive a real certificate
without sitting through the full attempt. Gated by config.DEV_MODE; has
no effect when DEV_MODE=false.

REMOVAL CHECKLIST (all 5 sites must be reverted together):
  1. Delete this file.
  2. app/main.py        — remove `dev_quiz` from the `from . import` line
                        — remove the DEV ONLY block in quiz_start()
                          (the _dev_* variables + the `if payload.dev_quiz` branch)
                        — remove the `dev_pass_mark` line + `pass_mark=` kwarg in quiz_submit()
  3. app/quiz_generator.py — remove the `pass_mark` param from grade()
                             (backward-compatible default; safe to leave if you prefer)
  4. templates/home.html  — remove the {% if dev_mode %} dev-mode-bar block,
                             its inline CSS rules, and its JS listener
  5. templates/quiz.html  — remove the #devQuizBanner <div>,
                             the isDevQuiz / sessionStorage lines in startQuiz(),
                             the `dev_quiz` flag in the fetch body,
                             the `if (quiz.dev_mode)` banner-show block, and
                             the `quiz.duration_minutes ||` fallback in deadlineMs
"""

DEV_QUIZ_COUNT        = 2   # questions per fast-quiz
DEV_QUIZ_PASS_MARK    = 1   # pass if ≥ 1 of 2 correct
DEV_QUIZ_DURATION_MIN = 5   # minutes on the timer
