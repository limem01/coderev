"""Tests for tiktoken encoding fallback selection in cost estimation.

``count_tokens_tiktoken`` falls back to a base encoding when tiktoken has no
mapping for a (usually too-new) model. It must pick the encoding the model's
family actually uses: ``o200k_base`` for GPT-4o / GPT-4.1 / GPT-5 and the
o1/o3/o4 reasoning series, and ``cl100k_base`` only for the older GPT-4 /
GPT-3.5 / legacy models. Guessing ``cl100k_base`` for an o200k model yields
inaccurate token counts and therefore wrong cost estimates.

tiktoken is an optional dependency and is not installed in CI, so these tests
inject a fake ``tiktoken`` module into ``sys.modules`` to exercise the fallback
path deterministically without the real library.
"""

import sys
import types

import pytest

from coderev.cost import (
    _fallback_encoding_name,
    _strip_routing_prefixes,
    count_tokens_tiktoken,
)


class TestFallbackEncodingName:
    """_fallback_encoding_name maps a model to its base encoding."""

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4o-2024-08-06",
            "GPT-4O",  # case-insensitive
            "chatgpt-4o-latest",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-5",
            "gpt-5-mini",
            "o1",
            "o1-mini",
            "o1-preview",
            "o3-mini",
            "o4-mini",
            "o3",
        ],
    )
    def test_o200k_models(self, model):
        assert _fallback_encoding_name(model) == "o200k_base"

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4",
            "gpt-4-turbo",
            "gpt-4-turbo-preview",
            "gpt-3.5-turbo",
            "text-davinci-003",
            "curie",
        ],
    )
    def test_cl100k_models(self, model):
        assert _fallback_encoding_name(model) == "cl100k_base"

    def test_gpt_4o_not_confused_with_gpt_4(self):
        # gpt-4o* must win over the plain gpt-4 (cl100k) default.
        assert _fallback_encoding_name("gpt-4o") == "o200k_base"
        assert _fallback_encoding_name("gpt-4") == "cl100k_base"

    def test_bare_o_series_requires_boundary(self):
        # "gpt-4o1" is a gpt-4o model, not the "o1" reasoning series, and it
        # must not be misclassified by the bare o-series check.
        assert _fallback_encoding_name("gpt-4o1") == "o200k_base"
        # A token that merely starts with "o1" letters but is unrelated should
        # not trigger the o-series branch.
        assert _fallback_encoding_name("omni-model") == "cl100k_base"

    @pytest.mark.parametrize(
        "model",
        [
            "openai/gpt-4o-mini",  # LiteLLM/OpenRouter
            "azure/gpt-4o",  # Azure OpenAI deployment prefix
            "openrouter/openai/gpt-4o",  # multi-level router prefix
            "openai/o3-mini",
            "openai/gpt-4o-2099-01-01",  # routed + too-new dated id
        ],
    )
    def test_routed_ids_classified_by_bare_name(self, model):
        # A routing prefix must not knock a gpt-4o / o-series model off the
        # o200k_base encoding (regression: prefixes were previously not
        # stripped, so these wrongly resolved to cl100k_base).
        assert _fallback_encoding_name(model) == "o200k_base"

    def test_routed_legacy_stays_cl100k(self):
        assert _fallback_encoding_name("openai/gpt-4-turbo") == "cl100k_base"


class TestStripRoutingPrefixes:
    """_strip_routing_prefixes reduces a routed id to its bare model name."""

    @pytest.mark.parametrize(
        "routed,bare",
        [
            ("openai/gpt-4o-mini", "gpt-4o-mini"),
            ("azure/gpt-4o", "gpt-4o"),
            ("openrouter/openai/gpt-4o", "gpt-4o"),
            # Region/vendor tokens and the trailing ":0" version peel; the
            # "-v1" version token is left for longest-prefix pricing to resolve.
            ("us.anthropic.claude-3-5-sonnet-20240620-v1:0",
             "claude-3-5-sonnet-20240620-v1"),
            ("anthropic.claude-3-5-sonnet-20240620-v1:0",
             "claude-3-5-sonnet-20240620-v1"),
            ("claude-3-5-sonnet@20240620", "claude-3-5-sonnet"),
        ],
    )
    def test_strips(self, routed, bare):
        assert _strip_routing_prefixes(routed) == bare

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o-mini",  # already bare
            "gpt-3.5-turbo",  # alias dot must survive
            "gpt-4.1",  # version dot must survive
            "claude-3.5-sonnet",  # vendor-less alias dot survives
            "o3-mini",
        ],
    )
    def test_leaves_bare_models_untouched(self, model):
        assert _strip_routing_prefixes(model) == model


class _FakeEncoding:
    """Minimal stand-in for a tiktoken encoding.

    Encodes to one integer per whitespace-split word so the returned length is
    deterministic; the name records which base encoding was selected.
    """

    def __init__(self, name):
        self.name = name

    def encode(self, text):
        return list(range(len(text.split())))


def _install_fake_tiktoken(monkeypatch, known_models):
    """Install a fake ``tiktoken`` module.

    Args:
        known_models: set of model names for which ``encoding_for_model``
            succeeds (returning an encoding named after the model). Any other
            model raises ``KeyError``, forcing the fallback path.
    """
    recorded = {}

    def encoding_for_model(model):
        if model in known_models:
            return _FakeEncoding(f"for-model:{model}")
        raise KeyError(model)

    def get_encoding(name):
        recorded["get_encoding"] = name
        return _FakeEncoding(name)

    fake = types.ModuleType("tiktoken")
    fake.encoding_for_model = encoding_for_model
    fake.get_encoding = get_encoding
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    return recorded


class TestCountTokensTiktokenFallback:
    """count_tokens_tiktoken picks the right fallback encoding."""

    def test_unknown_o_series_falls_back_to_o200k(self, monkeypatch):
        # o4-mini is unknown to this (older) tiktoken build -> KeyError ->
        # must fall back to o200k_base, not cl100k_base.
        recorded = _install_fake_tiktoken(monkeypatch, known_models=set())
        count = count_tokens_tiktoken("one two three", "o4-mini")
        assert recorded["get_encoding"] == "o200k_base"
        assert count == 3

    def test_unknown_gpt4o_falls_back_to_o200k(self, monkeypatch):
        recorded = _install_fake_tiktoken(monkeypatch, known_models=set())
        count_tokens_tiktoken("a b c d", "gpt-4o-2099-01-01")
        assert recorded["get_encoding"] == "o200k_base"

    def test_unknown_legacy_gpt4_falls_back_to_cl100k(self, monkeypatch):
        recorded = _install_fake_tiktoken(monkeypatch, known_models=set())
        count_tokens_tiktoken("a b c", "gpt-4-some-future-variant")
        assert recorded["get_encoding"] == "cl100k_base"

    def test_known_model_uses_exact_encoding_no_fallback(self, monkeypatch):
        # When tiktoken knows the model, the fallback is not consulted.
        recorded = _install_fake_tiktoken(
            monkeypatch, known_models={"gpt-4o-mini"}
        )
        count = count_tokens_tiktoken("hello world", "gpt-4o-mini")
        assert "get_encoding" not in recorded
        assert count == 2

    def test_missing_tiktoken_returns_none(self, monkeypatch):
        # Simulate tiktoken not being installed.
        monkeypatch.setitem(sys.modules, "tiktoken", None)
        assert count_tokens_tiktoken("anything", "o3-mini") is None

    def test_routed_id_uses_bare_exact_encoding(self, monkeypatch):
        # The full routed id has no mapping, but the bare model does -- the bare
        # exact encoding must be used instead of a base-encoding guess.
        recorded = _install_fake_tiktoken(
            monkeypatch, known_models={"gpt-4o-mini"}
        )
        count = count_tokens_tiktoken("a b c", "openai/gpt-4o-mini")
        assert "get_encoding" not in recorded  # no base-encoding fallback
        assert count == 3

    def test_routed_unknown_falls_back_to_o200k(self, monkeypatch):
        # Neither the routed id nor its bare form is known -> base-encoding
        # fallback, and it must be o200k_base for a gpt-4o model.
        recorded = _install_fake_tiktoken(monkeypatch, known_models=set())
        count_tokens_tiktoken("a b c d", "azure/gpt-4o-2099-01-01")
        assert recorded["get_encoding"] == "o200k_base"
