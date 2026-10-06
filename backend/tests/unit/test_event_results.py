"""Instructor results for a Training Event's Knowledge Checks.

Answers have been graded on the server and written to the learner record since the quiz moved
off the browser, but nothing read them back: an instructor could not see who answered what or
which question a cohort keeps missing. These cover the read side -- who may see a cohort's
results, and that the numbers are exactly what the learner record holds.

They drive the HTTP surface, as test_content_authorization does, because a guard is only real once
FastAPI runs it.
"""

import csv
import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from proving_ground.models.event import EventParticipant, TrainingEvent
from proving_ground.models.range import Range
from proving_ground.models.walkthrough_progress import WalkthroughProgress
from tests.unit.test_content_authorization import as_user, make_content, make_user  # noqa: F401

RESULTS = "/api/v1/training-events/{}/results"


def _guide():
    """Two steps, three questions: q1 and q2 in step 1, q3 in step 2."""

    def q(qid, key):
        return {
            "id": qid,
            "prompt": f"Question {qid}?",
            "explanation": "why",
            "options": [
                {"id": "a", "text": "A", "correct": key == "a"},
                {"id": "b", "text": "B", "correct": key == "b"},
                {"id": "c", "text": "C", "correct": key == "c"},
            ],
        }

    return {
        "title": "Guide",
        "phases": [
            {
                "id": "p1",
                "name": "Phase 1",
                "steps": [
                    {
                        "id": "s1",
                        "title": "One",
                        "content": "x",
                        "quiz": [q("q1", "a"), q("q2", "b")],
                    },
                    {"id": "s2", "title": "Two", "content": "y", "quiz": [q("q3", "c")]},
                ],
            }
        ],
    }


def _answer(qid, step, chosen, key):
    return {
        "question_id": qid,
        "step_id": step,
        "selected_option_id": chosen,
        "correct": chosen == key,
        "correct_option_id": key,
        "explanation": "why",
        "answered_at": "2026-10-06T12:00:00+00:00",
    }


@pytest.fixture
def cohort(db_session):
    """An event with two students on their own ranges, plus every other kind of person."""
    author = make_user(db_session, username="author", role="engineer")
    guide = make_content(db_session, owner=author, published=True)
    guide.walkthrough_data = _guide()
    db_session.commit()

    people = {
        "author": author,
        "ana": make_user(db_session, username="ana", role="student"),
        "ben": make_user(db_session, username="ben", role="student"),
        "cal": make_user(db_session, username="cal", role="student"),  # joined, never answered
        "teacher": make_user(
            db_session, username="teacher", role="student"
        ),  # instructor by event role
        "marker": make_user(
            db_session, username="marker", role="student"
        ),  # evaluator by event role
        "watcher": make_user(db_session, username="watcher", role="student"),  # observer
        "stranger": make_user(db_session, username="stranger", role="student"),  # not in the event
        "boss": make_user(db_session, username="boss", role="admin"),  # not in the event
    }

    event = TrainingEvent(
        name="Pilot",
        start_datetime=datetime(2026, 10, 6, tzinfo=timezone.utc),
        created_by_id=author.id,
    )
    db_session.add(event)
    db_session.commit()

    def seat(user, role, *, with_range=False):
        range_id = None
        if with_range:
            lab = Range(
                name=f"lab-{user.username}",
                created_by=author.id,
                student_guide_id=guide.id,
                assigned_to_user_id=user.id,
            )
            db_session.add(lab)
            db_session.commit()
            range_id = lab.id
        db_session.add(
            EventParticipant(event_id=event.id, user_id=user.id, role=role, range_id=range_id)
        )
        db_session.commit()
        return range_id

    ana_range = seat(people["ana"], "student", with_range=True)
    ben_range = seat(people["ben"], "student", with_range=True)
    seat(people["cal"], "student", with_range=True)
    seat(people["teacher"], "instructor")
    seat(people["marker"], "evaluator")
    seat(people["watcher"], "observer")

    # ana: q1 right, q2 right, q3 wrong (chose a); finished step s1
    db_session.add(
        WalkthroughProgress(
            range_id=ana_range,
            user_id=people["ana"].id,
            completed_steps=["s1"],
            quiz_answers={
                "q1": _answer("q1", "s1", "a", "a"),
                "q2": _answer("q2", "s1", "b", "b"),
                "q3": _answer("q3", "s2", "a", "c"),
            },
        )
    )
    # ben: q1 wrong (chose b), q2 not answered, q3 right; finished both steps
    db_session.add(
        WalkthroughProgress(
            range_id=ben_range,
            user_id=people["ben"].id,
            completed_steps=["s1", "s2"],
            quiz_answers={"q1": _answer("q1", "s1", "b", "a"), "q3": _answer("q3", "s2", "c", "c")},
        )
    )
    db_session.commit()
    return event, people


class TestOnlyInstructorsAndEvaluatorsSeeResults:
    @pytest.mark.parametrize("who", ["author", "teacher", "marker", "boss"])
    def test_instructors_evaluators_and_elevated_roles_can_read(self, as_user, cohort, who):
        event, people = cohort
        assert as_user(people[who]).get(RESULTS.format(event.id)).status_code == 200
        assert as_user(people[who]).get(RESULTS.format(event.id) + ".csv").status_code == 200

    @pytest.mark.parametrize("who", ["ana", "watcher", "stranger"])
    def test_students_observers_and_outsiders_cannot(self, as_user, cohort, who):
        event, people = cohort
        assert as_user(people[who]).get(RESULTS.format(event.id)).status_code == 403
        assert as_user(people[who]).get(RESULTS.format(event.id) + ".csv").status_code == 403

    def test_an_unknown_event_is_not_found(self, as_user, cohort):
        _, people = cohort
        assert as_user(people["author"]).get(RESULTS.format(uuid4())).status_code == 404


class TestTheNumbersAreWhatTheLearnerRecordHolds:
    def test_one_row_per_student_with_their_score(self, as_user, cohort):
        event, people = cohort
        body = as_user(people["author"]).get(RESULTS.format(event.id)).json()
        learners = {row["username"]: row for row in body["learners"]}

        assert set(learners) == {"ana", "ben", "cal"}  # students only, answered or not
        assert (
            learners["ana"]["answered"],
            learners["ana"]["correct"],
            learners["ana"]["score_pct"],
        ) == (3, 2, 66.7)
        assert (
            learners["ben"]["answered"],
            learners["ben"]["correct"],
            learners["ben"]["score_pct"],
        ) == (2, 1, 50.0)
        assert (
            learners["cal"]["answered"],
            learners["cal"]["correct"],
            learners["cal"]["score_pct"],
        ) == (0, 0, None)
        assert (learners["ana"]["completed_steps"], learners["ana"]["total_steps"]) == (1, 2)
        assert (learners["ben"]["completed_steps"], learners["ben"]["total_steps"]) == (2, 2)
        assert learners["ana"]["total_questions"] == 3
        assert learners["cal"]["last_activity"] is None

    def test_one_row_per_question_with_option_counts(self, as_user, cohort):
        event, people = cohort
        body = as_user(people["author"]).get(RESULTS.format(event.id)).json()
        questions = {row["question_id"]: row for row in body["questions"]}

        assert list(questions) == ["q1", "q2", "q3"]  # in the order the guide asks them
        q1, q2, q3 = questions["q1"], questions["q2"], questions["q3"]
        assert (q1["answered"], q1["correct"], q1["correct_pct"]) == (2, 1, 50.0)
        assert (q2["answered"], q2["correct"], q2["correct_pct"]) == (1, 1, 100.0)
        assert (q3["answered"], q3["correct"], q3["correct_pct"]) == (2, 1, 50.0)
        assert q1["step_id"] == "s1" and q1["prompt"] == "Question q1?"
        assert {o["id"]: o["chosen"] for o in q1["options"]} == {"a": 1, "b": 1, "c": 0}
        assert {o["id"]: o["correct"] for o in q3["options"]} == {"a": False, "b": False, "c": True}

    def test_reading_results_changes_nothing(self, as_user, cohort, db_session):
        event, people = cohort
        before = {
            (p.range_id, p.user_id): dict(p.quiz_answers or {})
            for p in db_session.query(WalkthroughProgress)
        }
        as_user(people["author"]).get(RESULTS.format(event.id))
        as_user(people["author"]).get(RESULTS.format(event.id) + ".csv")
        db_session.expire_all()
        after = {
            (p.range_id, p.user_id): dict(p.quiz_answers or {})
            for p in db_session.query(WalkthroughProgress)
        }
        assert before == after


class TestTheCsvExport:
    def test_one_row_per_answer(self, as_user, cohort):
        event, people = cohort
        response = as_user(people["author"]).get(RESULTS.format(event.id) + ".csv")

        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert list(rows[0]) == [
            "username",
            "question_id",
            "step_id",
            "selected_option_id",
            "correct",
            "answered_at",
        ]
        assert len(rows) == 5  # ana 3 + ben 2; cal answered nothing
        assert {
            "username": "ben",
            "question_id": "q1",
            "selected_option_id": "b",
            "correct": "false",
        }.items() <= next(
            r for r in rows if r["username"] == "ben" and r["question_id"] == "q1"
        ).items()
