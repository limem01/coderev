"""Tests for OpenAI-model routing in ``count_tokens``.

``count_tokens`` should attempt tiktoken *only* for OpenAI models and fall back
to the character-based approximation for everything else. Provider detection is
delegated to ``config.detect_provider`` (the single source of truth), so the
decision inherits its token-boundary gating and router-prefix peeling rather
than the old private ``any(prefix in model_lower for prefix in [...])`` list,
which matched any id merely *containing* "gpt-"/"o1"/"o3"/"o4" as a substring
and therefore misrouted ids like "o1pro" or "my-gpt-wrapper" to tiktoken.

tiktoken is an optional dependency not installed in CI, so these tests inject a
fake ``tiktoken`` module that records whether it was consulted.
"""

import sys
import types

import pytest

from coderev.cost import count_tokens, count_tokens_approximate


def _install_recording_tiktoken(monkeypatch):
    """Install a fake ``tiktoken`` that records whether it was consulted.

    ``encode`` returns a deterministic, distinctive count (100 per word) so a
    tiktoken result is unmistakable next to the char-based approximation.
    """
    state = {"consulted": False}

    class _Enc:
        def encode(self, text):
            return list(range(100 * len(text.split())))

    def encoding_for_model(model):
        state["consulted"] = True
        return _Enc()

    def get_encoding(name):
        state["consulted"] = True
        return _Enc()

    fake = types.ModuleType("tiktoken")
    fake.encoding_for_model = encoding_for_model
    fake.get_encoding = get_encoding
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    return state


# Ids that must route to tiktoken (OpenAI, per config.detect_provider).
OPENAI_IDS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-3.5-turbo",
    "o1",
    "o1-mini",
    "o3-mini",
    "o4-mini",
    "davinci-002",
    "openai/gpt-4o-mini",       # router prefix peeled
    "openrouter/openai/o3-mini",
    "azure/gpt-4o",
]

# Ids that must NOT route to tiktoken -> approximation is used.
NON_OPENAI_IDS = [
    "claude-3-opus",
    "claude-sonnet-4-20250514",
    "gemini-2.5-pro",
    "anthropic/claude-3-5-sonnet",
    # Substring false positives the old ``in`` check misrouted but a
    # token-boundary detector correctly rejects:
    "o1pro",            # bare o-series needs "o1" exactly or "o1-..."
    "histo3ry",         # merely contains "o3"
    "neo4j-embed",      # merely contains "o4"
    "my-gpt-wrapper",   # "gpt-" is mid-string, not a prefix
]


class TestCountTokensRouting:
    @pytest.mark.parametrize("model", OPENAI_IDS)
    def test_openai_ids_use_tiktoken(self, monkeypatch, model):
        state = _install_recording_tiktoken(monkeypatch)
        count = count_tokens("alpha beta gamma", model)
        assert state["consulted"] is True
        assert count == 300  # 100 per word from the fake encoder

    @pytest.mark.parametrize("model", NON_OPENAI_IDS)
    def test_non_openai_ids_use_approximation(self, monkeypatch, model):
        state = _install_recording_tiktoken(monkeypatch)
        text = "alpha beta gamma"
        count = count_tokens(text, model)
        assert state["consulted"] is False
        assert count == count_tokens_approximate(text)

    def test_openai_falls_back_to_approximation_when_tiktoken_missing(
        self, monkeypatch
    ):
        # OpenAI id but tiktoken not installed -> graceful approximation.
        monkeypatch.setitem(sys.modules, "tiktoken", None)
        text = "alpha beta gamma"
        assert count_tokens(text, "o3-mini") == count_tokens_approximate(text)
