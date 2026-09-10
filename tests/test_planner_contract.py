import json

from agents.planner.src.planner.planner_function import (
    build_fallback_plan,
    is_valid_plan,
    planner_failure_payload,
)
from agents.router.src.router.router import _fallback_route


def test_error_plan_is_not_valid():
    failure = {"project": "Error", "algorithm_steps": []}
    assert is_valid_plan(failure) is False


def test_failure_payload_is_structured():
    payload = planner_failure_payload("Planner crashed while parsing response")
    assert payload["status"] == "failed"
    assert "Planner crashed" in payload["reason"]
    assert is_valid_plan(payload) is False


def test_valid_plan_is_accepted():
    plan = {
        "project": "Prime number finder",
        "output_type": "python",
        "algorithm_steps": [
            {
                "step_number": 1,
                "step_title": "Read input",
                "step_description": "Read the target number.",
                "instructions": ["Read an integer from the user."],
                "inputs": [],
                "outputs": [],
                "dependencies": {"requires_previous_steps": [], "provides_for_next_steps": []},
            }
        ],
    }
    assert is_valid_plan(plan) is True


def test_fallback_plan_has_valid_contract():
    plan = build_fallback_plan("build a program to check prime numbers")
    assert is_valid_plan(plan) is True
    assert plan["output_type"] == "python"
    assert len(plan["algorithm_steps"]) >= 2


def test_fallback_router_uses_keyword_detection():
    direct = _fallback_route("what is machine learning?")
    build = _fallback_route("build a prime number checker")
    assert direct["lane"] == "deerflow_direct"
    assert build["lane"] == "build_pipeline"
