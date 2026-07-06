"""Tests for cost estimation functionality."""

import tempfile
from pathlib import Path

import pytest

from coderev.cost import (
    CostEstimate,
    CostEstimator,
    count_tokens,
    count_tokens_approximate,
    get_model_pricing,
    is_known_model,
    MODEL_PRICING,
    DEFAULT_PRICING,
)


class TestCountTokens:
    """Tests for token counting functions."""
    
    def test_count_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert count_tokens_approximate("") == 0
    
    def test_count_tokens_simple_text(self):
        """Simple text should return reasonable token count."""
        text = "Hello, world!"
        tokens = count_tokens_approximate(text)
        # Should be roughly 3-5 tokens
        assert 2 <= tokens <= 10
    
    def test_count_tokens_code(self):
        """Code with special characters should count tokens correctly."""
        code = """def hello():
    print("Hello, world!")
    return True
"""
        tokens = count_tokens_approximate(code)
        # Code typically has more tokens per character
        assert tokens > 10
    
    def test_count_tokens_special_chars_increase_count(self):
        """Special characters should increase token count."""
        plain = "hello world hello world"
        special = "{[()]}<>{}+=!@#$%"
        
        plain_tokens = count_tokens_approximate(plain)
        special_tokens = count_tokens_approximate(special)
        
        # Special characters should result in more tokens per char
        plain_ratio = plain_tokens / len(plain)
        special_ratio = special_tokens / len(special)
        
        assert special_ratio >= plain_ratio
    
    def test_count_tokens_with_model(self):
        """count_tokens should work with different models."""
        text = "def foo(): return 42"
        
        claude_tokens = count_tokens(text, "claude-3-sonnet")
        gpt_tokens = count_tokens(text, "gpt-4o")
        
        # Both should return reasonable values
        assert claude_tokens > 0
        assert gpt_tokens > 0


class TestGetModelPricing:
    """Tests for model pricing retrieval."""
    
    def test_exact_model_match(self):
        """Exact model names should return correct pricing."""
        pricing = get_model_pricing("claude-3-sonnet-20240229")
        assert pricing == MODEL_PRICING["claude-3-sonnet-20240229"]
    
    def test_model_alias(self):
        """Model aliases should return correct pricing."""
        pricing = get_model_pricing("claude-3-sonnet")
        assert pricing == MODEL_PRICING["claude-3-sonnet"]
    
    def test_openai_model(self):
        """OpenAI models should return correct pricing."""
        pricing = get_model_pricing("gpt-4o")
        assert pricing == MODEL_PRICING["gpt-4o"]
    
    def test_unknown_model_returns_default(self):
        """Unknown models should return default pricing."""
        pricing = get_model_pricing("unknown-model-xyz")
        assert pricing == DEFAULT_PRICING
    
    def test_case_insensitive(self):
        """Model names should be case-insensitive."""
        lower = get_model_pricing("claude-3-sonnet")
        upper = get_model_pricing("CLAUDE-3-SONNET")
        assert lower == upper

    def test_claude_4_family_pricing(self):
        """Current-generation Claude models should have explicit pricing."""
        assert get_model_pricing("claude-opus-4-20250514") == (15.00, 75.00)
        assert get_model_pricing("claude-opus-4-1-20250805") == (15.00, 75.00)
        assert get_model_pricing("claude-sonnet-4-20250514") == (3.00, 15.00)
        assert get_model_pricing("claude-haiku-4-5-20251001") == (1.00, 5.00)
        assert get_model_pricing("claude-3-7-sonnet-20250219") == (3.00, 15.00)

    def test_claude_4_aliases(self):
        """Short aliases should resolve to the same pricing as the dated IDs."""
        assert get_model_pricing("claude-opus-4") == get_model_pricing(
            "claude-opus-4-20250514"
        )
        assert get_model_pricing("claude-sonnet-4") == get_model_pricing(
            "claude-sonnet-4-20250514"
        )
        assert get_model_pricing("claude-3.7-sonnet") == (3.00, 15.00)

    def test_gpt_41_family_pricing(self):
        """GPT-4.1 family should have explicit pricing."""
        assert get_model_pricing("gpt-4.1") == (2.00, 8.00)
        assert get_model_pricing("gpt-4.1-mini") == (0.40, 1.60)
        assert get_model_pricing("gpt-4.1-nano") == (0.10, 0.40)

    def test_newer_reasoning_models_pricing(self):
        """o3/o4 reasoning models should have explicit pricing."""
        assert get_model_pricing("o3-mini") == (1.10, 4.40)
        assert get_model_pricing("o4-mini") == (1.10, 4.40)

    def test_dated_suffix_resolves_to_most_specific_base(self):
        """Dated/suffixed IDs must resolve to the most specific base model,
        not the first family sharing a provider prefix (regression: these
        previously all matched ``gpt-4`` / ``claude-3-opus`` pricing)."""
        # gpt-4o family: must NOT fall back to the pricier gpt-4 (30/60).
        assert get_model_pricing("gpt-4o-2024-08-06") == (2.50, 10.00)
        assert get_model_pricing("gpt-4o-mini-2024-07-18") == (0.15, 0.60)
        # gpt-4-turbo dated ID keeps turbo pricing, not base gpt-4.
        assert get_model_pricing("gpt-4-turbo-2024-04-09") == (10.00, 30.00)
        # Claude dated IDs resolve to their own tier, not opus.
        assert get_model_pricing("claude-sonnet-4-20250514") == (3.00, 15.00)
        assert get_model_pricing("o3-mini-2025-01-31") == (1.10, 4.40)

    def test_longest_prefix_respects_token_boundary(self):
        """Prefix matching must end on a '-'/'.' boundary so a shorter key
        does not swallow an unrelated longer model name."""
        # "gpt-4" is a string-prefix of "gpt-45x" but not a token match.
        assert get_model_pricing("gpt-45x-model") == DEFAULT_PRICING
        # A bare gpt-4 dated variant still resolves to gpt-4.
        assert get_model_pricing("gpt-4-0613") == (30.00, 60.00)

    def test_hyphenated_base_aliases(self):
        """Anthropic uses hyphens in real IDs; date-less hyphenated aliases
        must resolve to the correct tier (regression: only dotted aliases
        like ``claude-3.5-sonnet`` existed)."""
        assert get_model_pricing("claude-3-5-sonnet") == (3.00, 15.00)
        assert get_model_pricing("claude-3-5-haiku") == (1.00, 5.00)
        assert get_model_pricing("claude-3-7-sonnet") == (3.00, 15.00)
        assert get_model_pricing("claude-opus-4-1") == (15.00, 75.00)
        assert get_model_pricing("claude-haiku-4-5") == (1.00, 5.00)

    def test_latest_suffix_resolves_to_base(self):
        """Anthropic's moving ``-latest`` aliases must resolve to their base
        tier's pricing, not fall back to DEFAULT_PRICING (regression: these
        previously mis-priced to 10/30)."""
        assert get_model_pricing("claude-3-5-sonnet-latest") == (3.00, 15.00)
        assert get_model_pricing("claude-3-7-sonnet-latest") == (3.00, 15.00)
        assert get_model_pricing("claude-3-5-haiku-latest") == (1.00, 5.00)
        assert get_model_pricing("claude-opus-4-1-latest") == (15.00, 75.00)
        # -latest forms are recognized as known, not estimated guesses.
        assert is_known_model("claude-3-5-sonnet-latest") is True
        assert is_known_model("claude-3-5-haiku-latest") is True

    def test_unknown_latest_still_falls_back(self):
        """A ``-latest`` on an unknown base must not spuriously resolve."""
        assert get_model_pricing("totally-unknown-latest") == DEFAULT_PRICING
        assert is_known_model("totally-unknown-latest") is False


class TestIsKnownModel:
    """Tests for is_known_model / DEFAULT_PRICING fallback detection."""

    def test_exact_model_is_known(self):
        assert is_known_model("claude-3-sonnet-20240229") is True

    def test_alias_is_known(self):
        assert is_known_model("gpt-4o") is True

    def test_case_insensitive_is_known(self):
        assert is_known_model("CLAUDE-3-SONNET") is True

    def test_dated_prefix_variant_is_known(self):
        # Resolves via longest-prefix match, so still counts as known.
        assert is_known_model("gpt-4o-2024-08-06") is True
        assert is_known_model("gpt-4-0613") is True

    def test_unknown_model_is_not_known(self):
        assert is_known_model("unknown-model-xyz") is False

    def test_boundary_mismatch_is_not_known(self):
        # "gpt-45x" is a string-prefix collision, not a real token match.
        assert is_known_model("gpt-45x-model") is False

    def test_known_model_with_default_priced_rates_still_known(self):
        # gpt-4-turbo happens to be priced identically to DEFAULT_PRICING;
        # it must still report as known (detection is not value-based).
        assert get_model_pricing("gpt-4-turbo") == DEFAULT_PRICING
        assert is_known_model("gpt-4-turbo") is True


class TestPricingIsEstimatedFlag:
    """Tests that CostEstimate carries the unknown-pricing warning flag."""

    def test_known_model_not_estimated(self):
        estimator = CostEstimator(model="gpt-4o")
        assert estimator.pricing_is_estimated is False
        estimate = estimator.estimate_code("print('hi')", language="python")
        assert estimate.pricing_is_estimated is False

    def test_unknown_model_is_estimated(self):
        estimator = CostEstimator(model="totally-made-up-model")
        assert estimator.pricing_is_estimated is True
        estimate = estimator.estimate_code("print('hi')", language="python")
        assert estimate.pricing_is_estimated is True

    def test_estimate_diff_carries_flag(self):
        estimator = CostEstimator(model="totally-made-up-model")
        estimate = estimator.estimate_diff("+ added line\n- removed line")
        assert estimate.pricing_is_estimated is True

    def test_default_flag_is_false(self):
        estimate = CostEstimate(
            input_tokens=1,
            estimated_output_tokens=1,
            model="x",
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )
        assert estimate.pricing_is_estimated is False


class TestCostEstimate:
    """Tests for CostEstimate dataclass."""
    
    def test_total_tokens(self):
        """total_tokens should sum input and output."""
        estimate = CostEstimate(
            input_tokens=1000,
            estimated_output_tokens=500,
            model="claude-3-sonnet",
            input_cost_usd=0.003,
            output_cost_usd=0.0075,
            total_cost_usd=0.0105,
        )
        assert estimate.total_tokens == 1500
    
    def test_format_cost_small(self):
        """Small costs should show 4 decimal places."""
        estimate = CostEstimate(
            input_tokens=100,
            estimated_output_tokens=50,
            model="claude-3-sonnet",
            input_cost_usd=0.0003,
            output_cost_usd=0.00075,
            total_cost_usd=0.00105,
        )
        # Result rounds to 4 decimal places
        assert estimate.format_cost() == "$0.0010"
    
    def test_format_cost_medium(self):
        """Medium costs should show 3 decimal places."""
        estimate = CostEstimate(
            input_tokens=10000,
            estimated_output_tokens=5000,
            model="claude-3-sonnet",
            input_cost_usd=0.03,
            output_cost_usd=0.075,
            total_cost_usd=0.105,
        )
        assert estimate.format_cost() == "$0.105"
    
    def test_format_cost_large(self):
        """Large costs should show 2 decimal places."""
        estimate = CostEstimate(
            input_tokens=1000000,
            estimated_output_tokens=500000,
            model="claude-3-opus",
            input_cost_usd=15.0,
            output_cost_usd=37.5,
            total_cost_usd=52.5,
        )
        assert estimate.format_cost() == "$52.50"
    
    def test_format_tokens_small(self):
        """Small token counts should show as-is."""
        estimate = CostEstimate(
            input_tokens=500,
            estimated_output_tokens=200,
            model="claude-3-sonnet",
            input_cost_usd=0.0015,
            output_cost_usd=0.003,
            total_cost_usd=0.0045,
        )
        assert estimate.format_tokens() == "500"
    
    def test_format_tokens_thousands(self):
        """Thousand-level token counts should show K format."""
        estimate = CostEstimate(
            input_tokens=5000,
            estimated_output_tokens=2000,
            model="claude-3-sonnet",
            input_cost_usd=0.015,
            output_cost_usd=0.03,
            total_cost_usd=0.045,
        )
        assert estimate.format_tokens() == "5.0K"
    
    def test_format_tokens_millions(self):
        """Million-level token counts should show M format."""
        estimate = CostEstimate(
            input_tokens=2500000,
            estimated_output_tokens=1000000,
            model="claude-3-sonnet",
            input_cost_usd=7.5,
            output_cost_usd=15.0,
            total_cost_usd=22.5,
        )
        assert estimate.format_tokens() == "2.50M"


class TestExceedsBudget:
    """Tests for CostEstimate.exceeds_budget."""

    def _estimate(self, total: float) -> CostEstimate:
        return CostEstimate(
            input_tokens=1000,
            estimated_output_tokens=500,
            model="claude-3-sonnet",
            input_cost_usd=total * 0.5,
            output_cost_usd=total * 0.5,
            total_cost_usd=total,
        )

    def test_under_budget(self):
        assert self._estimate(0.10).exceeds_budget(0.50) is False

    def test_over_budget(self):
        assert self._estimate(0.75).exceeds_budget(0.50) is True

    def test_equal_budget_is_not_over(self):
        # Budget is inclusive: exactly at the limit is allowed.
        assert self._estimate(0.50).exceeds_budget(0.50) is False

    def test_zero_budget(self):
        assert self._estimate(0.0001).exceeds_budget(0.0) is True
        assert self._estimate(0.0).exceeds_budget(0.0) is False

    def test_negative_budget_raises(self):
        with pytest.raises(ValueError):
            self._estimate(0.10).exceeds_budget(-1.0)


class TestCostEstimator:
    """Tests for CostEstimator class."""
    
    def test_init_default_model(self):
        """Should initialize with default Claude model."""
        estimator = CostEstimator()
        assert "claude" in estimator.model.lower()
    
    def test_init_custom_model(self):
        """Should initialize with custom model."""
        estimator = CostEstimator(model="gpt-4o")
        assert estimator.model == "gpt-4o"
    
    def test_estimate_code_simple(self):
        """Should estimate cost for simple code."""
        estimator = CostEstimator(model="claude-3-sonnet")
        code = "def hello(): return 'Hello, World!'"
        
        estimate = estimator.estimate_code(code)
        
        assert estimate.input_tokens > 0
        assert estimate.estimated_output_tokens >= 200  # Minimum output
        assert estimate.total_cost_usd > 0
        assert estimate.model == "claude-3-sonnet"
    
    def test_estimate_code_with_focus(self):
        """Focus areas should be included in prompt."""
        estimator = CostEstimator()
        code = "def foo(): pass"
        
        estimate_no_focus = estimator.estimate_code(code)
        estimate_with_focus = estimator.estimate_code(code, focus=["security", "performance"])
        
        # With focus areas, prompt is slightly longer
        assert estimate_with_focus.input_tokens >= estimate_no_focus.input_tokens
    
    def test_estimate_file(self):
        """Should estimate cost for a file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            f.flush()
            
            estimator = CostEstimator()
            estimate = estimator.estimate_file(f.name)
            
            assert estimate.input_tokens > 0
            assert estimate.total_cost_usd > 0
        
        Path(f.name).unlink()
    
    def test_estimate_file_not_found(self):
        """Should raise FileNotFoundError for missing files."""
        estimator = CostEstimator()
        
        with pytest.raises(FileNotFoundError):
            estimator.estimate_file("/nonexistent/file.py")
    
    def test_estimate_files_multiple(self):
        """Should estimate total cost for multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create test files
            (tmpdir / "file1.py").write_text("def a(): pass")
            (tmpdir / "file2.py").write_text("def b(): return 42")
            (tmpdir / "file3.py").write_text("class C:\n    def d(self): pass")
            
            estimator = CostEstimator()
            estimate = estimator.estimate_files([
                tmpdir / "file1.py",
                tmpdir / "file2.py",
                tmpdir / "file3.py",
            ])
            
            assert estimate.file_count == 3
            assert estimate.skipped_files == 0
            assert estimate.input_tokens > 0
    
    def test_estimate_files_skips_binary(self):
        """Should skip binary files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create test files
            (tmpdir / "code.py").write_text("def hello(): pass")
            (tmpdir / "binary.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
            
            estimator = CostEstimator()
            estimate = estimator.estimate_files([
                tmpdir / "code.py",
                tmpdir / "binary.png",
            ])
            
            assert estimate.file_count == 1
            assert estimate.skipped_files == 1
    
    def test_estimate_diff(self):
        """Should estimate cost for a diff."""
        diff = """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
-    return 'world'
+    return 'Hello, World!'
+    # Added comment
"""
        
        estimator = CostEstimator()
        estimate = estimator.estimate_diff(diff)
        
        assert estimate.input_tokens > 0
        assert estimate.estimated_output_tokens >= 200
        assert estimate.total_cost_usd > 0
    
    def test_different_models_different_costs(self):
        """Different models should have different costs."""
        code = "def example(): return [x*2 for x in range(100)]"
        
        sonnet = CostEstimator(model="claude-3-sonnet")
        opus = CostEstimator(model="claude-3-opus")
        haiku = CostEstimator(model="claude-3-haiku")
        
        sonnet_estimate = sonnet.estimate_code(code)
        opus_estimate = opus.estimate_code(code)
        haiku_estimate = haiku.estimate_code(code)
        
        # Opus should be most expensive, haiku least
        assert opus_estimate.total_cost_usd > sonnet_estimate.total_cost_usd
        assert sonnet_estimate.total_cost_usd > haiku_estimate.total_cost_usd


class TestModelPricingCoverage:
    """Tests for model pricing coverage."""
    
    def test_anthropic_models_have_pricing(self):
        """All common Anthropic models should have pricing."""
        models = [
            "claude-3-opus",
            "claude-3-sonnet", 
            "claude-3-haiku",
            "claude-3.5-sonnet",
            "claude-3.5-haiku",
        ]
        for model in models:
            pricing = get_model_pricing(model)
            assert pricing != DEFAULT_PRICING, f"Missing pricing for {model}"
    
    def test_openai_models_have_pricing(self):
        """All common OpenAI models should have pricing."""
        models = [
            "gpt-4",
            "gpt-4-turbo",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
            "o1",
            "o1-mini",
        ]
        for model in models:
            # Check that the model is explicitly in MODEL_PRICING
            assert model in MODEL_PRICING or model.lower() in [k.lower() for k in MODEL_PRICING], f"Missing pricing for {model}"
