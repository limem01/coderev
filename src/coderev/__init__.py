"""CodeRev - AI-powered code review CLI tool.

Supports multiple LLM providers:
- Anthropic Claude (default)
- OpenAI GPT-4/GPT-4o

The provider is auto-detected from the model name, or can be explicitly set.

Example:
    from coderev import CodeReviewer
    
    # Use Claude (default)
    reviewer = CodeReviewer()
    
    # Use GPT-4
    reviewer = CodeReviewer(model="gpt-4o")
"""

from coderev.cache import ReviewCache
from coderev.reviewer import (
    CodeReviewer,
    ReviewResult,
    Issue,
    BinaryFileError,
    is_binary_file,
)
from coderev.async_reviewer import AsyncCodeReviewer, review_files_parallel
from coderev.config import Config
from coderev.ignore import CodeRevIgnore
from coderev.providers import (
    RateLimitError,
    ProviderError,
    BaseProvider,
    AnthropicProvider,
    OpenAIProvider,
    get_provider,
    detect_provider_from_model,
)
from coderev.cost import (
    CostEstimator,
    CostEstimate,
    count_tokens,
    get_model_pricing,
)
from coderev.rules import (
    Rule,
    RuleSet,
    RuleValidationError,
    load_rules,
    load_rules_from_file,
    find_rules_file,
    get_builtin_rule,
    list_builtin_rules,
    BUILTIN_RULES,
)
from coderev.history import (
    ReviewHistory,
    ReviewEntry,
    HistoryStats,
)

__version__ = "0.6.0"
__all__ = [
    # Core
    "CodeReviewer",
    "AsyncCodeReviewer",
    "review_files_parallel",
    "ReviewResult", 
    "Issue",
    # Cost estimation
    "CostEstimator",
    "CostEstimate",
    "count_tokens",
    "get_model_pricing",
    # Rules
    "Rule",
    "RuleSet",
    "RuleValidationError",
    "load_rules",
    "load_rules_from_file",
    "find_rules_file",
    "get_builtin_rule",
    "list_builtin_rules",
    "BUILTIN_RULES",
    # History
    "ReviewHistory",
    "ReviewEntry",
    "HistoryStats",
    # Errors
    "BinaryFileError",
    "RateLimitError",
    "ProviderError",
    # Utilities
    "is_binary_file",
    "Config",
    "CodeRevIgnore",
    "ReviewCache",
    # Providers
    "BaseProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "get_provider",
    "detect_provider_from_model",
]
