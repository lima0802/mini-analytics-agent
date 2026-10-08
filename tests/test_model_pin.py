"""The LLM model must be pinned to an exact model ID.

An alias like "...-latest" can point to a new model the day the provider releases one: answers,
cost and eval scores would change with no code change and no pull request. A pinned ID means a
model upgrade is a deliberate one-line change that goes through CI and the eval gate.
"""

from agent.nodes import MODEL


def test_model_is_pinned_to_an_exact_id():
    assert MODEL == "claude-opus-5-5"  # change deliberately, in its own PR, and re-run the eval
    assert "latest" not in MODEL
