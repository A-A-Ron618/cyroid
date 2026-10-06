# backend/proving_ground/services/learner_results.py
"""A Training Event's Knowledge Check results, read from the learner record.

Answers are graded on the server and written to `walkthrough_progress.quiz_answers` when a learner
submits them. This reads them back for the people running the event: one row per student, one row
per question, and one row per answer for export. It only reads; nothing here writes to the record.

A student's questions come from the walkthrough on *their* range, because that is the guide they
were actually shown. In a normal event every student's range presents the same guide; if they
differ, questions are listed in the order they are first met.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from proving_ground.api.walkthrough import _range_walkthrough
from proving_ground.models.event import EventParticipant, TrainingEvent
from proving_ground.models.range import Range
from proving_ground.models.user import User
from proving_ground.models.walkthrough_progress import WalkthroughProgress
from proving_ground.schemas.event import (
    LearnerResult,
    ParticipantRole,
    QuestionOptionResult,
    QuestionResult,
)


@dataclass
class AnswerRow:
    """One recorded answer, as exported."""

    username: str
    question_id: str
    step_id: Optional[str]
    selected_option_id: str
    correct: bool
    answered_at: Optional[str]


@dataclass
class EventResults:
    learners: List[LearnerResult]
    questions: List[QuestionResult]
    answers: List[AnswerRow]


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def _steps_and_questions(walkthrough: Optional[dict]):
    """(step ids, questions in order with their step id) for one walkthrough."""
    steps, questions = [], []
    for phase in (walkthrough or {}).get("phases", []) or []:
        for step in phase.get("steps", []) or []:
            steps.append(step.get("id"))
            for question in step.get("quiz", []) or []:
                questions.append((step.get("id"), question))
    return steps, questions


def build_event_results(event: TrainingEvent, db: Session) -> EventResults:
    students = (
        db.query(EventParticipant)
        .filter(
            EventParticipant.event_id == event.id,
            EventParticipant.role == ParticipantRole.STUDENT.value,
        )
        .all()
    )

    learners: List[LearnerResult] = []
    answers: List[AnswerRow] = []
    questions: Dict[str, QuestionResult] = {}  # insertion order = order first met in a guide

    for participant in students:
        user = db.query(User).filter(User.id == participant.user_id).first()
        username = user.username if user else str(participant.user_id)
        walkthrough = None
        progress = None
        if participant.range_id:
            range_obj = db.query(Range).filter(Range.id == participant.range_id).first()
            if range_obj:
                walkthrough = _range_walkthrough(range_obj, db)
            progress = (
                db.query(WalkthroughProgress)
                .filter(
                    WalkthroughProgress.range_id == participant.range_id,
                    WalkthroughProgress.user_id == participant.user_id,
                )
                .first()
            )

        step_ids, guide_questions = _steps_and_questions(walkthrough)
        for step_id, question in guide_questions:
            if question.get("id") not in questions:
                questions[question["id"]] = QuestionResult(
                    question_id=question["id"],
                    step_id=step_id,
                    prompt=question.get("prompt"),
                    options=[
                        QuestionOptionResult(
                            id=option.get("id"),
                            text=option.get("text"),
                            correct=bool(option.get("correct")),
                        )
                        for option in question.get("options", []) or []
                    ],
                )

        recorded = (progress.quiz_answers or {}) if progress else {}
        asked = {question.get("id") for _, question in guide_questions}
        # Keyed by question id, which is the record's own key; only questions this guide asks count.
        mine = [(qid, recorded[qid]) for qid in recorded if qid in asked]
        correct = sum(1 for _, a in mine if a.get("correct"))
        completed = set(progress.completed_steps or []) if progress else set()

        learners.append(
            LearnerResult(
                user_id=participant.user_id,
                username=username,
                range_id=participant.range_id,
                completed_steps=len(completed & set(step_ids)),
                total_steps=len(step_ids),
                answered=len(mine),
                total_questions=len(guide_questions),
                correct=correct,
                score_pct=_pct(correct, len(mine)),
                last_activity=progress.updated_at if progress else None,
            )
        )

        for qid, answer in mine:
            row = questions[qid]
            row.answered += 1
            row.correct += 1 if answer.get("correct") else 0
            for option in row.options:
                if option.id == answer.get("selected_option_id"):
                    option.chosen += 1
            answers.append(
                AnswerRow(
                    username=username,
                    question_id=qid,
                    step_id=answer.get("step_id"),
                    selected_option_id=answer.get("selected_option_id"),
                    correct=bool(answer.get("correct")),
                    answered_at=answer.get("answered_at"),
                )
            )

    for row in questions.values():
        row.correct_pct = _pct(row.correct, row.answered)

    order = list(questions)
    answers.sort(key=lambda a: (a.username, order.index(a.question_id)))
    learners.sort(key=lambda l: (l.username or ""))
    return EventResults(learners=learners, questions=list(questions.values()), answers=answers)
