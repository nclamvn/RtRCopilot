import json
from pathlib import Path

from rtr_copilot.pilot.questions import PilotQuestionSet, load_pilot_questions


def test_pilot_question_contract_is_complete_and_role_labelled() -> None:
    questions = load_pilot_questions()
    assert len(questions) == 32
    assert {item.persona for item in questions} == {
        "staff", "leader", "curator", "admin",
    }
    assert {item.scope for item in questions} == {
        "sot", "file", "research", "document",
    }
    assert {item.expected for item in questions} == {
        "grounded", "honest_null", "denied", "blocked_caveat",
    }


def test_pilot_question_contract_rejects_duplicate_ids() -> None:
    path = Path(__file__).parents[1] / "src/rtr_copilot/pilot/questions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["questions"][1]["question_id"] = payload["questions"][0]["question_id"]
    try:
        PilotQuestionSet.model_validate(payload)
    except ValueError as error:
        assert "pilot_question_id_duplicate" in str(error)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("duplicate pilot question id accepted")
