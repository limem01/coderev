"""Tests for AWS Bedrock / Google Vertex model-id resolution in cost estimation.

Bedrock and Vertex expose the same underlying Anthropic models under
dot-separated ids rather than the slash-separated ids LiteLLM/OpenRouter use:

* Bedrock: ``anthropic.claude-3-5-sonnet-20240620-v1:0``
* Bedrock cross-region inference profiles add a region prefix:
  ``us.anthropic.claude-...``, ``eu.anthropic.claude-...``, ``apac.anthropic.``
* Vertex: ``claude-3-5-sonnet@20240620``

Before the fix these all fell back to ``DEFAULT_PRICING`` (~3-5x off for Sonnet
input and ~2x off for output), despite the resolver docstring claiming Bedrock/
Vertex coverage. These tests pin the corrected behaviour.
"""

import pytest

from coderev.cost import (
    DEFAULT_PRICING,
    get_model_pricing,
    is_known_model,
    _resolve_pricing,
)


class TestBedrockIds:
    """AWS Bedrock dot-separated ids resolve to the underlying model."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("anthropic.claude-3-5-sonnet-20240620-v1:0", (3.00, 15.00)),
            ("anthropic.claude-3-5-haiku-20241022-v1:0", (1.00, 5.00)),
            ("anthropic.claude-3-opus-20240229-v1:0", (15.00, 75.00)),
            ("anthropic.claude-3-7-sonnet-20250219-v1:0", (3.00, 15.00)),
            ("anthropic.claude-opus-4-1-20250805-v1:0", (15.00, 75.00)),
            ("anthropic.claude-sonnet-4-20250514-v1:0", (3.00, 15.00)),
        ],
    )
    def test_bedrock_ids_resolve(self, model, expected):
        assert get_model_pricing(model) == expected
        assert is_known_model(model) is True

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("us.anthropic.claude-3-7-sonnet-20250219-v1:0", (3.00, 15.00)),
            ("eu.anthropic.claude-sonnet-4-20250514-v1:0", (3.00, 15.00)),
            ("apac.anthropic.claude-3-5-haiku-20241022-v1:0", (1.00, 5.00)),
        ],
    )
    def test_region_prefixed_bedrock_ids_resolve(self, model, expected):
        """Cross-region inference profiles prepend a region token."""
        assert get_model_pricing(model) == expected
        assert is_known_model(model) is True

    def test_bedrock_version_suffix_stripped(self):
        """The trailing ``:<digits>`` inference-profile version is ignored."""
        with_suffix = get_model_pricing("anthropic.claude-3-5-sonnet-20240620-v1:0")
        without_suffix = get_model_pricing("anthropic.claude-3-5-sonnet-20240620-v1")
        assert with_suffix == without_suffix == (3.00, 15.00)


class TestVertexIds:
    """Google Vertex ``@<date>`` ids resolve via longest-prefix matching."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("claude-3-5-sonnet@20240620", (3.00, 15.00)),
            ("claude-3-5-sonnet-v2@20241022", (3.00, 15.00)),
            ("claude-3-5-haiku@20241022", (1.00, 5.00)),
            ("claude-opus-4-1@20250805", (15.00, 75.00)),
        ],
    )
    def test_vertex_ids_resolve(self, model, expected):
        assert get_model_pricing(model) == expected
        assert is_known_model(model) is True


class TestNoRegressions:
    """The dot-peeling must not disturb existing resolution paths."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            # Alias dots ("claude-3.5-sonnet") are NOT provider prefixes.
            ("claude-3.5-sonnet", (3.00, 15.00)),
            ("claude-3.7-sonnet", (3.00, 15.00)),
            ("gemini-2.5-flash", (0.30, 2.50)),
            ("gemini-1.5-pro", (1.25, 5.00)),
            # Slash-routed ids keep working.
            ("openai/gpt-4o-mini", (0.15, 0.60)),
            ("openrouter/anthropic/claude-3.5-sonnet", (3.00, 15.00)),
            # Bare ids keep working.
            ("gpt-4o", (2.50, 10.00)),
            ("claude-3-5-sonnet-latest", (3.00, 15.00)),
        ],
    )
    def test_existing_ids_unchanged(self, model, expected):
        assert get_model_pricing(model) == expected
        assert is_known_model(model) is True


class TestUnknownCloudModels:
    """A cloud-prefixed id for an unpriced model still falls back cleanly."""

    @pytest.mark.parametrize(
        "model",
        [
            "amazon.nova-pro-v1:0",
            "us.amazon.nova-lite-v1:0",
            "meta.llama3-70b-instruct-v1:0",
            "totally-unknown-model@20260101",
        ],
    )
    def test_unknown_models_fall_back(self, model):
        pricing, matched = _resolve_pricing(model)
        assert pricing == DEFAULT_PRICING
        assert matched is False
        assert is_known_model(model) is False
