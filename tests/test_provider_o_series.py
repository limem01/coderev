"""Regression tests for OpenAI o-series and router-prefix provider detection.

`cost.py` already prices and tokenizes the o3/o4 reasoning models as OpenAI
models, but both `config.detect_provider` and
`providers.detect_provider_from_model` only knew about `o1` (and matched it
loosely), so `--model o3-mini` / `o4-mini` was routed to the Anthropic client.
These tests pin the boundary-aware o-series matching and the router-prefix
stripping, and assert both entry points agree.
"""

import pytest

from coderev.config import detect_provider
from coderev.providers import detect_provider_from_model


# Every id both entry points must agree on, with the expected provider.
CASES = [
    # o-series reasoning models (the bug: o3/o4 fell through to anthropic).
    ("o1", "openai"),
    ("o1-mini", "openai"),
    ("o1-preview", "openai"),
    ("o3", "openai"),
    ("o3-mini", "openai"),
    ("o3-pro", "openai"),
    ("o4-mini", "openai"),
    ("o4-mini-2025-04-16", "openai"),
    ("O3-MINI", "openai"),  # case-insensitive
    # Classic OpenAI families still route correctly.
    ("gpt-4", "openai"),
    ("gpt-4o", "openai"),
    ("gpt-4o-mini", "openai"),
    ("gpt-3.5-turbo", "openai"),
    ("davinci-002", "openai"),
    # Router / proxy prefixes are stripped before matching.
    ("openai/o3-mini", "openai"),
    ("openai/gpt-4o", "openai"),
    ("azure/gpt-4o", "openai"),
    ("openrouter/openai/gpt-4o", "openai"),
    ("openrouter/openai/o4-mini", "openai"),
    ("anthropic/claude-3-5-sonnet-20241022", "anthropic"),
    ("openrouter/anthropic/claude-3.5-sonnet", "anthropic"),
    # Anthropic and unknowns default to anthropic.
    ("claude-3-opus", "anthropic"),
    ("claude-3-5-sonnet", "anthropic"),
    ("us.anthropic.claude-3-5-sonnet-20240620-v1:0", "anthropic"),
    ("unknown-model", "anthropic"),
    # Boundary: names that merely begin with the o-series letters are NOT the
    # o-series (real ids use a dash or the bare name).
    ("o3pro", "anthropic"),
    ("orca-2", "anthropic"),
    ("o2-something", "anthropic"),
]


@pytest.mark.parametrize("model,expected", CASES)
def test_detect_provider(model, expected):
    assert detect_provider(model) == expected


@pytest.mark.parametrize("model,expected", CASES)
def test_detect_provider_from_model(model, expected):
    assert detect_provider_from_model(model) == expected


@pytest.mark.parametrize("model,_expected", CASES)
def test_entry_points_agree(model, _expected):
    # The providers helper delegates to config -- they must never disagree.
    assert detect_provider_from_model(model) == detect_provider(model)


def test_o3_o4_no_longer_misroute():
    """The specific regression: o3/o4 used to return 'anthropic'."""
    for model in ("o3", "o3-mini", "o4-mini", "openai/o3-mini"):
        assert detect_provider(model) == "openai"
        assert detect_provider_from_model(model) == "openai"
