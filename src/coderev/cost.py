"""Cost estimation for CodeRev reviews.

Provides token counting and cost estimation before running reviews,
helping users understand the expected API costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from coderev.prompts import SYSTEM_PROMPT, build_review_prompt
from coderev.reviewer import is_binary_file


# Pricing per 1M tokens (input, output) in USD
# Updated as of January 2026
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude 3 models
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (1.00, 5.00),
    # Anthropic Claude 3.7 models
    "claude-3-7-sonnet-20250219": (3.00, 15.00),
    # Anthropic Claude 4 models
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-opus-4-1-20250805": (15.00, 75.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # Aliases
    "claude-3-opus": (15.00, 75.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3.5-sonnet": (3.00, 15.00),
    "claude-3.5-haiku": (1.00, 5.00),
    "claude-3.7-sonnet": (3.00, 15.00),
    # Hyphenated base aliases (match Anthropic's real ID convention so that
    # date-less and "-latest" forms resolve, e.g. "claude-3-5-sonnet-latest").
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (1.00, 5.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-opus-4.1": (15.00, 75.00),
    "claude-opus-4-1": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4.5": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI models
    "gpt-4": (30.00, 60.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4-turbo-preview": (10.00, 30.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-3.5-turbo": (0.50, 1.50),
    # OpenAI GPT-4.1 family
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    # OpenAI reasoning models
    "o1-preview": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    # Google Gemini models. Commonly routed through LiteLLM/OpenRouter with a
    # "gemini/" or "google/" prefix (handled by _resolve_pricing); dated/version
    # suffixes like "-002" or "-001" resolve via longest-prefix matching.
    # Prices are the standard (non-batch) per-1M-token rates for the base
    # (lower-context) tier -- Gemini bills a higher rate above 128k/200k tokens,
    # matching how the Anthropic/OpenAI entries above use a single flat rate.
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-flash-8b": (0.0375, 0.15),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = (10.00, 30.00)

# AWS Bedrock and Google Vertex expose the same underlying models under
# dot-separated ids rather than the slash-separated ids LiteLLM/OpenRouter use.
# A Bedrock id looks like "anthropic.claude-3-5-sonnet-20240620-v1:0", and its
# cross-region inference profiles prepend a region prefix
# ("us.anthropic.claude-...", "eu.anthropic.claude-...", "apac.anthropic..."),
# while Vertex appends an "@<date>" version ("claude-3-5-sonnet@20240620").
# We peel these leading tokens so the underlying model prices correctly instead
# of hitting DEFAULT_PRICING. The tokens are matched exactly (never as a bare
# dot split) so real alias dots like "claude-3.5-sonnet" are left untouched --
# "claude-3" is not a provider prefix.
_BEDROCK_REGION_PREFIXES = frozenset({"us", "eu", "apac", "ap", "global", "us-gov"})
_CLOUD_VENDOR_PREFIXES = frozenset({
    "anthropic", "openai", "google", "meta", "mistral", "cohere",
    "amazon", "deepseek", "ai21", "stability",
})
_CLOUD_PROVIDER_PREFIXES = _BEDROCK_REGION_PREFIXES | _CLOUD_VENDOR_PREFIXES

# Both Anthropic (Message Batches) and OpenAI (Batch API) charge 50% of the
# standard per-token rate for asynchronous batch requests. Reviews that don't
# need a synchronous result can be gated/budgeted at this reduced rate.
BATCH_DISCOUNT = 0.5

# Average characters per token (approximation)
# Claude uses ~3.5-4 chars/token for English code
# GPT models use ~4 chars/token
CHARS_PER_TOKEN = 4.0

# Estimated output tokens as a ratio of input tokens
# Code reviews typically produce 20-40% of input size as output
OUTPUT_RATIO = 0.30


def count_tokens_approximate(text: str) -> int:
    """Count tokens using character-based approximation.
    
    This is a simple heuristic that works reasonably well for code:
    - Average of ~4 characters per token
    - Adjusted for code which has more short tokens (brackets, operators)
    
    Args:
        text: The text to count tokens for.
        
    Returns:
        Estimated token count.
    """
    if not text:
        return 0
    
    # Basic character count divided by average chars per token
    base_count = len(text) / CHARS_PER_TOKEN
    
    # Adjust for code-specific patterns (more tokens per char due to symbols)
    # Count special characters that are typically single tokens
    special_chars = sum(1 for c in text if c in '{}[]()<>,.;:=+-*/%!&|^~@#$?\\"\'\n\t')
    
    # Blend the estimates
    adjusted_count = base_count + (special_chars * 0.2)
    
    return int(adjusted_count)


def count_tokens_tiktoken(text: str, model: str) -> int | None:
    """Count tokens using tiktoken (for OpenAI models).
    
    Args:
        text: The text to count tokens for.
        model: The model name to get encoding for.
        
    Returns:
        Token count, or None if tiktoken is not available.
    """
    try:
        import tiktoken
    except ImportError:
        return None
    
    try:
        # Try to get encoding for the specific model
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fall back to cl100k_base (GPT-4, GPT-3.5-turbo)
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
    
    try:
        return len(encoding.encode(text))
    except Exception:
        return None


def count_tokens(text: str, model: str = "claude-3-sonnet") -> int:
    """Count tokens in text.
    
    Uses tiktoken for OpenAI models when available, falls back to
    character-based approximation otherwise.
    
    Args:
        text: The text to count tokens for.
        model: The model name (affects tokenization).
        
    Returns:
        Estimated token count.
    """
    model_lower = model.lower()
    
    # Try tiktoken for OpenAI models
    if any(prefix in model_lower for prefix in ["gpt-", "o1", "o3", "o4", "davinci", "curie"]):
        tiktoken_count = count_tokens_tiktoken(text, model)
        if tiktoken_count is not None:
            return tiktoken_count
    
    # Fall back to approximation
    return count_tokens_approximate(text)


def _resolve_pricing(model: str) -> tuple[tuple[float, float], bool]:
    """Resolve pricing for a model.

    Args:
        model: Model name or alias.

    Returns:
        Tuple of ((input_price_per_1m, output_price_per_1m), matched) where
        ``matched`` is True if the model resolved to a known pricing entry and
        False if it fell back to ``DEFAULT_PRICING``.
    """
    # Check exact match first
    if model in MODEL_PRICING:
        return MODEL_PRICING[model], True

    # Check case-insensitive
    model_lower = model.lower()
    for key, value in MODEL_PRICING.items():
        if key.lower() == model_lower:
            return value, True

    # Anthropic publishes moving "-latest" aliases (e.g.
    # "claude-3-5-sonnet-latest"). Strip a trailing "-latest" and resolve the
    # underlying base model so pricing stays accurate instead of falling back
    # to DEFAULT_PRICING.
    if model_lower.endswith("-latest"):
        base = model[: -len("-latest")]
        if base:
            resolved, matched = _resolve_pricing(base)
            if matched:
                return resolved, True

    # Provider-routed IDs. Routers/proxies (LiteLLM, OpenRouter) prefix the
    # model with one or more slash-separated "provider/" segments, e.g.
    # "openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet-20241022", or
    # "openrouter/anthropic/claude-3.5-sonnet". Strip the leading segment and
    # resolve the remainder so these price the same as the bare model instead
    # of falling back to DEFAULT_PRICING. Recursion peels multi-level prefixes.
    # (AWS Bedrock / Google Vertex use dot-separated ids instead -- handled
    # just below.)
    if "/" in model:
        _, _, rest = model.partition("/")
        if rest:
            resolved, matched = _resolve_pricing(rest)
            if matched:
                return resolved, True

    # Cloud-routed IDs (AWS Bedrock / Google Vertex) are dot-separated rather
    # than slash-separated: "anthropic.claude-3-5-sonnet-20240620-v1:0", with an
    # optional region prefix on Bedrock cross-region inference profiles
    # ("us.anthropic.claude-...", "eu.anthropic...", "apac.anthropic..."). Peel a
    # single leading provider/region token (matched exactly against the known
    # set so alias dots like "claude-3.5-sonnet" survive) and re-resolve the
    # remainder, recursing to strip "<region>.<vendor>." two-part prefixes.
    head, dot, rest = model.partition(".")
    if dot and rest and head.lower() in _CLOUD_PROVIDER_PREFIXES:
        resolved, matched = _resolve_pricing(rest)
        if matched:
            return resolved, True

    # Bedrock appends an inference-profile version suffix like ":0" (as in
    # "...-v1:0"). Strip a trailing ":<digits>" and re-resolve the base id.
    if ":" in model:
        base, _, tail = model.rpartition(":")
        if base and tail.isdigit():
            resolved, matched = _resolve_pricing(base)
            if matched:
                return resolved, True

    # Longest-prefix match: a dated/suffixed model ID (e.g.
    # "gpt-4o-2024-08-06" or "claude-sonnet-4-5-20260101") should resolve to
    # the most specific known base model, not the first family that happens
    # to share a provider prefix. Require the match to end on a token
    # boundary ('-' or '.') so "gpt-4" doesn't swallow "gpt-45".
    best_key: str | None = None
    for key in MODEL_PRICING:
        key_lower = key.lower()
        if not model_lower.startswith(key_lower):
            continue
        boundary = model_lower[len(key_lower):len(key_lower) + 1]
        # '-' and '.' delimit version tokens; '@' is Vertex's date separator
        # ("claude-3-5-sonnet@20240620") and ':' a Bedrock version separator.
        if boundary and boundary not in "-.@:":
            continue
        if best_key is None or len(key_lower) > len(best_key):
            best_key = key_lower

    if best_key is not None:
        # Return by exact (case-insensitive) key match found above.
        for key, value in MODEL_PRICING.items():
            if key.lower() == best_key:
                return value, True

    return DEFAULT_PRICING, False


def get_model_pricing(model: str) -> tuple[float, float]:
    """Get pricing for a model.

    Args:
        model: Model name or alias.

    Returns:
        Tuple of (input_price_per_1m, output_price_per_1m) in USD. Unknown
        models fall back to ``DEFAULT_PRICING``; use :func:`is_known_model` to
        detect that case.
    """
    return _resolve_pricing(model)[0]


def is_known_model(model: str) -> bool:
    """Return True if ``model`` resolves to a known pricing entry.

    When this returns False, cost estimates for the model use the conservative
    ``DEFAULT_PRICING`` fallback and should be treated as a rough guess rather
    than an accurate figure.

    Args:
        model: Model name or alias.

    Returns:
        True if pricing is known, False if the default fallback is used.
    """
    return _resolve_pricing(model)[1]


@dataclass
class CostEstimate:
    """Cost estimation result."""
    
    input_tokens: int
    estimated_output_tokens: int
    model: str
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    file_count: int = 1
    skipped_files: int = 0
    pricing_is_estimated: bool = False
    batch_mode: bool = False
    # Path this estimate is for, when it represents a single file.
    path: str | None = None
    # Per-file estimates when this is an aggregate produced with
    # ``estimate_files(..., detailed=True)``. ``None`` for single-file or
    # non-detailed estimates so existing callers are unaffected.
    file_breakdown: list["CostEstimate"] | None = None

    @property
    def total_tokens(self) -> int:
        """Total estimated tokens (input + output)."""
        return self.input_tokens + self.estimated_output_tokens

    def exceeds_budget(self, max_cost_usd: float) -> bool:
        """Return True if the estimated total cost exceeds a budget.

        Useful for gating reviews in CI: fail the pipeline when a change is
        large enough that reviewing it would cost more than allowed.

        Args:
            max_cost_usd: Maximum acceptable total cost in USD. Must be
                non-negative.

        Returns:
            True if ``total_cost_usd`` is strictly greater than the budget.

        Raises:
            ValueError: If ``max_cost_usd`` is negative.
        """
        if max_cost_usd < 0:
            raise ValueError("max_cost_usd must be non-negative")
        return self.total_cost_usd > max_cost_usd
    
    def format_cost(self) -> str:
        """Format cost as human-readable string."""
        if self.total_cost_usd < 0.01:
            return f"${self.total_cost_usd:.4f}"
        elif self.total_cost_usd < 1.00:
            return f"${self.total_cost_usd:.3f}"
        else:
            return f"${self.total_cost_usd:.2f}"
    
    def format_tokens(self) -> str:
        """Format token counts as human-readable string."""
        if self.input_tokens >= 1_000_000:
            return f"{self.input_tokens / 1_000_000:.2f}M"
        elif self.input_tokens >= 1_000:
            return f"{self.input_tokens / 1_000:.1f}K"
        else:
            return str(self.input_tokens)


class CostEstimator:
    """Estimates API costs before running reviews."""
    
    def __init__(self, model: str = "claude-3-sonnet", batch_mode: bool = False):
        """Initialize the cost estimator.

        Args:
            model: Model name to estimate costs for.
            batch_mode: If True, apply the asynchronous Batch API discount
                (:data:`BATCH_DISCOUNT`) to both input and output rates. Use
                this to budget reviews that will be submitted via Anthropic
                Message Batches or the OpenAI Batch API.
        """
        self.model = model
        self.batch_mode = batch_mode
        self.input_price, self.output_price = get_model_pricing(model)
        if batch_mode:
            self.input_price *= BATCH_DISCOUNT
            self.output_price *= BATCH_DISCOUNT
        # Whether pricing was resolved from a known model or fell back to
        # DEFAULT_PRICING (in which case estimates are a rough guess).
        self.pricing_is_estimated = not is_known_model(model)
    
    def estimate_code(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        context: str | None = None,
    ) -> CostEstimate:
        """Estimate cost for reviewing code.
        
        Args:
            code: The code to review.
            language: Programming language (optional).
            focus: List of focus areas (optional).
            context: Additional context (optional).
            
        Returns:
            CostEstimate with token counts and costs.
        """
        # Build the actual prompt that would be sent
        prompt = build_review_prompt(code, language, focus, context)
        full_input = SYSTEM_PROMPT + "\n\n" + prompt
        
        # Count input tokens
        input_tokens = count_tokens(full_input, self.model)
        
        # Estimate output tokens
        estimated_output = int(input_tokens * OUTPUT_RATIO)
        # Minimum output for a basic review
        estimated_output = max(estimated_output, 200)
        
        # Calculate costs
        input_cost = (input_tokens / 1_000_000) * self.input_price
        output_cost = (estimated_output / 1_000_000) * self.output_price
        
        return CostEstimate(
            input_tokens=input_tokens,
            estimated_output_tokens=estimated_output,
            model=self.model,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
            pricing_is_estimated=self.pricing_is_estimated,
            batch_mode=self.batch_mode,
        )

    def estimate_file(
        self,
        file_path: Path | str,
        focus: list[str] | None = None,
    ) -> CostEstimate:
        """Estimate cost for reviewing a file.
        
        Args:
            file_path: Path to the file.
            focus: List of focus areas (optional).
            
        Returns:
            CostEstimate with token counts and costs.
            
        Raises:
            FileNotFoundError: If file doesn't exist.
            ValueError: If file is binary.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if is_binary_file(file_path):
            raise ValueError(f"Cannot estimate cost for binary file: {file_path}")
        
        code = file_path.read_text(encoding="utf-8")
        language = self._detect_language(file_path)

        estimate = self.estimate_code(code, language, focus, context=str(file_path))
        # Record which file this single-file estimate is for so aggregate
        # breakdowns can attribute cost per path.
        estimate.path = str(file_path)
        return estimate
    
    def estimate_files(
        self,
        file_paths: Sequence[Path | str],
        focus: list[str] | None = None,
        detailed: bool = False,
    ) -> CostEstimate:
        """Estimate total cost for reviewing multiple files.

        Binary files are automatically skipped.

        Args:
            file_paths: List of file paths.
            focus: List of focus areas (optional).
            detailed: When True, attach a per-file breakdown to the returned
                aggregate's ``file_breakdown`` (sorted by descending total
                cost) so callers can see which files dominate the estimate.
                The per-file estimates sum to the aggregate totals.

        Returns:
            Combined CostEstimate for all files.
        """
        total_input_tokens = 0
        total_output_tokens = 0
        file_count = 0
        skipped_count = 0
        per_file: list[CostEstimate] = []

        for path in file_paths:
            path = Path(path)

            try:
                estimate = self.estimate_file(path, focus)
                total_input_tokens += estimate.input_tokens
                total_output_tokens += estimate.estimated_output_tokens
                file_count += 1
                if detailed:
                    per_file.append(estimate)
            except (FileNotFoundError, ValueError, UnicodeDecodeError):
                skipped_count += 1
                continue

        # Calculate total costs
        input_cost = (total_input_tokens / 1_000_000) * self.input_price
        output_cost = (total_output_tokens / 1_000_000) * self.output_price

        breakdown: list[CostEstimate] | None = None
        if detailed:
            # Most expensive files first so budgeting attention goes where it
            # matters; ties keep input order (Python sort is stable).
            breakdown = sorted(
                per_file, key=lambda e: e.total_cost_usd, reverse=True
            )

        return CostEstimate(
            input_tokens=total_input_tokens,
            estimated_output_tokens=total_output_tokens,
            model=self.model,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
            file_count=file_count,
            skipped_files=skipped_count,
            pricing_is_estimated=self.pricing_is_estimated,
            batch_mode=self.batch_mode,
            file_breakdown=breakdown,
        )
    
    def estimate_diff(
        self,
        diff: str,
        focus: list[str] | None = None,
    ) -> CostEstimate:
        """Estimate cost for reviewing a diff.
        
        Args:
            diff: Git diff string.
            focus: List of focus areas (optional).
            
        Returns:
            CostEstimate with token counts and costs.
        """
        from coderev.prompts import build_diff_prompt
        
        prompt = build_diff_prompt(diff, focus)
        full_input = SYSTEM_PROMPT + "\n\n" + prompt
        
        input_tokens = count_tokens(full_input, self.model)
        estimated_output = max(int(input_tokens * OUTPUT_RATIO), 200)
        
        input_cost = (input_tokens / 1_000_000) * self.input_price
        output_cost = (estimated_output / 1_000_000) * self.output_price
        
        return CostEstimate(
            input_tokens=input_tokens,
            estimated_output_tokens=estimated_output,
            model=self.model,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
            pricing_is_estimated=self.pricing_is_estimated,
            batch_mode=self.batch_mode,
        )

    def _detect_language(self, file_path: Path) -> str | None:
        """Detect programming language from file extension."""
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".java": "java",
            ".kt": "kotlin",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".php": "php",
            ".swift": "swift",
            ".sql": "sql",
            ".sh": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
        }
        return extension_map.get(file_path.suffix.lower())
