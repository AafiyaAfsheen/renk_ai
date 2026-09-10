from agents.constructor.src.constructor_agent.constructor_agent_function import (
    appears_stepwise,
    build_integrated_program_prompt,
)


def test_stepwise_program_is_detected():
    code = '''# Step 1: parse input
import sys

def parse_limit():
    return 10

def main():
    print(parse_limit())

if __name__ == "__main__":
    main()

# Step 2: check primes
import math

def is_prime(n):
    return True

if __name__ == "__main__":
    main()
'''
    assert appears_stepwise(code) is True


def test_integrated_program_prompt_forces_single_artifact():
    prompt = build_integrated_program_prompt(
        project="Prime number checker",
        algorithm_steps=[
            {
                "step_number": 1,
                "step_title": "Parse input",
                "instructions": ["Read a limit parameter."],
            },
            {
                "step_number": 2,
                "step_title": "Check prime numbers",
                "instructions": ["Generate primes and print them."],
            },
        ],
    )
    assert "ONE coherent program" in prompt
    assert "single final implementation" in prompt.lower()
    assert 'if __name__ == "__main__"' in prompt
