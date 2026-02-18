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
# Updated as of February 2025
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude models
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (1.00, 5.00),
    # Aliases
    "claude-3-opus": (15.00, 75.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3.5-sonnet": (3.00, 15.00),
    "claude-3.5-haiku": (1.00, 5.00),
    # OpenAI models
    "gpt-4": (30.00, 60.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4-turbo-preview": (10.00, 30.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1-preview": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o1": (15.00, 60.00),
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = (10.00, 30.00)

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
    if any(prefix in model_lower for prefix in ["gpt-", "o1", "davinci", "curie"]):
        tiktoken_count = count_tokens_tiktoken(text, model)
        if tiktoken_count is not None:
            return tiktoken_count
    
    # Fall back to approximation
    return count_tokens_approximate(text)


def get_model_pricing(model: str) -> tuple[float, float]:
    """Get pricing for a model.
    
    Args:
        model: Model name or alias.
        
    Returns:
        Tuple of (input_price_per_1m, output_price_per_1m) in USD.
    """
    # Check exact match first
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    
    # Check case-insensitive
    model_lower = model.lower()
    for key, value in MODEL_PRICING.items():
        if key.lower() == model_lower:
            return value
    
    # Check partial match for model families
    for key, value in MODEL_PRICING.items():
        if model_lower.startswith(key.lower().split("-")[0]):
            return value
    
    return DEFAULT_PRICING


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
    
    @property
    def total_tokens(self) -> int:
        """Total estimated tokens (input + output)."""
        return self.input_tokens + self.estimated_output_tokens
    
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
    
    def __init__(self, model: str = "claude-3-sonnet"):
        """Initialize the cost estimator.
        
        Args:
            model: Model name to estimate costs for.
        """
        self.model = model
        self.input_price, self.output_price = get_model_pricing(model)
    
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
        
        return self.estimate_code(code, language, focus, context=str(file_path))
    
    def estimate_files(
        self,
        file_paths: Sequence[Path | str],
        focus: list[str] | None = None,
    ) -> CostEstimate:
        """Estimate total cost for reviewing multiple files.
        
        Binary files are automatically skipped.
        
        Args:
            file_paths: List of file paths.
            focus: List of focus areas (optional).
            
        Returns:
            Combined CostEstimate for all files.
        """
        total_input_tokens = 0
        total_output_tokens = 0
        file_count = 0
        skipped_count = 0
        
        for path in file_paths:
            path = Path(path)
            
            try:
                estimate = self.estimate_file(path, focus)
                total_input_tokens += estimate.input_tokens
                total_output_tokens += estimate.estimated_output_tokens
                file_count += 1
            except (FileNotFoundError, ValueError, UnicodeDecodeError):
                skipped_count += 1
                continue
        
        # Calculate total costs
        input_cost = (total_input_tokens / 1_000_000) * self.input_price
        output_cost = (total_output_tokens / 1_000_000) * self.output_price
        
        return CostEstimate(
            input_tokens=total_input_tokens,
            estimated_output_tokens=total_output_tokens,
            model=self.model,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
            file_count=file_count,
            skipped_files=skipped_count,
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
