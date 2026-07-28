"""Regression tests for OpenAI's ChatGPT-tuned model ids (``chatgpt-4o-latest``).

``cost.py`` already tokenizes (``_fallback_encoding_name`` knows ``chatgpt-4o``)
these as OpenAI models, but ``config.detect_provider`` and its delegate
``providers.detect_provider_from_model`` only matched the ``gpt-`` prefix -- so
``--model chatgpt-4o-latest`` fell through to the Anthropic default and was
handed to the Anthropic client, an immediate auth/model error. These tests pin
the ``chatgpt-`` prefix routing (including router-prefixed ids), assert both
entry points agree, and check that ``chatgpt-4o`` prices at the gpt-4o rate
instead of ``DEFAULT_PRICING``.
"""

import pytest

from coderev.config import detect_provider
from coderev.cost import DEFAULT_PRICING, get_model_pricing, is_known_model
from coderev.providers import detect_provider_from_model


CASES = [
    ("chatgpt-4o-latest", "openai"),
    ("chatgpt-4o", "openai"),
    ("CHATGPT-4O-LATEST", "openai"),  # case-insensitive
    # Router / proxy prefixes are stripped before matching.
    ("openai/chatgpt-4o-latest", "openai"),
    ("openrouter/openai/chatgpt-4o-latest", "openai"),
    ("azure/chatgpt-4o-latest", "openai"),
    # Boundary: an unrelated id that merely contains "chatgpt" is not matched by
    # a prefix test, and plain gpt-/claude ids still route as before.
    ("gpt-4o", "openai"),
    ("claude-3-5-sonnet", "anthropic"),
    ("my-chatgpt-clone", "anthropic"),  # prefix, not substring
]


@pytest.mark.parametrize("model,expected", CASES)
def test_detect_provider(model, expected):
    assert detect_provider(model) == expected


@pytest.mark.parametrize("model,expected", CASES)
def test_detect_provider_from_model(model, expected):
    assert detect_provider_from_model(model) == expected


@pytest.mark.parametrize("model,_expected", CASES)
def test_entry_points_agree(model, _expected):
    assert detect_provider_from_model(model) == detect_provider(model)


def test_chatgpt_no_longer_misroutes():
    """The specific regression: chatgpt-4o-latest used to return 'anthropic'."""
    for model in ("chatgpt-4o-latest", "chatgpt-4o", "openai/chatgpt-4o-latest"):
        assert detect_provider(model) == "openai"
        assert detect_provider_from_model(model) == "openai"


@pytest.mark.parametrize(
    "model",
    ["chatgpt-4o", "chatgpt-4o-latest", "CHATGPT-4O-LATEST", "openai/chatgpt-4o-latest"],
)
def test_chatgpt_prices_at_gpt4o_rate(model):
    # ChatGPT-4o bills at the gpt-4o rate, not DEFAULT_PRICING.
    assert get_model_pricing(model) == get_model_pricing("gpt-4o")
    assert get_model_pricing(model) != DEFAULT_PRICING
    assert is_known_model(model)
