# CodeRev API Reference

Complete reference for the CodeRev Python API. All public classes and functions are importable from the top-level `coderev` package.

```python
import coderev
print(coderev.__version__)  # "0.6.0"
```

---

## Table of Contents

- [Core Classes](#core-classes)
  - [CodeReviewer](#codereviewer)
  - [AsyncCodeReviewer](#asynccodereviewer)
  - [ReviewResult](#reviewresult)
  - [Issue](#issue)
  - [InlineSuggestion](#inlinesuggestion)
- [Configuration](#configuration)
  - [Config](#config)
- [Cost Estimation](#cost-estimation)
  - [CostEstimator](#costestimator)
  - [CostEstimate](#costestimate)
- [Custom Rules](#custom-rules)
  - [Rule](#rule)
  - [RuleSet](#ruleset)
- [Review History](#review-history)
  - [ReviewHistory](#reviewhistory)
  - [ReviewEntry](#reviewentry)
  - [HistoryStats](#historystats)
- [Providers](#providers)
  - [BaseProvider](#baseprovider)
  - [AnthropicProvider](#anthropicprovider)
  - [OpenAIProvider](#openaiprovider)
- [Utilities](#utilities)
  - [ReviewCache](#reviewcache)
  - [CodeRevIgnore](#coderevignore)
- [Enums](#enums)
  - [Severity](#severity)
  - [Category](#category)
- [Exceptions](#exceptions)
- [Convenience Functions](#convenience-functions)

---

## Core Classes

### CodeReviewer

The main entry point for reviewing code. Supports Anthropic Claude (default) and OpenAI GPT models.

```python
from coderev import CodeReviewer
```

#### Constructor

```python
CodeReviewer(
    api_key: str | None = None,
    model: str | None = None,
    config: Config | None = None,
    cache_enabled: bool = True,
    cache_ttl_hours: int | None = None,
    cache_dir: Path | str | None = None,
    provider: str | None = None,
    rules: RuleSet | None = None,
    rules_path: Path | str | None = None,
    auto_load_rules: bool = True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str \| None` | `None` | API key. Falls back to config/env vars (`CODEREV_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). |
| `model` | `str \| None` | `None` | Model name. Defaults to config or `claude-3-sonnet-20240229`. |
| `config` | `Config \| None` | `None` | Config object. Loads from `.coderev.toml` if not provided. |
| `cache_enabled` | `bool` | `True` | Enable result caching. |
| `cache_ttl_hours` | `int \| None` | `168` | Cache time-to-live in hours (default: 1 week). |
| `cache_dir` | `Path \| str \| None` | `None` | Custom cache directory. |
| `provider` | `str \| None` | `None` | `"anthropic"` or `"openai"`. Auto-detected from model name if omitted. |
| `rules` | `RuleSet \| None` | `None` | Pre-loaded custom rules. Takes precedence over `rules_path`. |
| `rules_path` | `Path \| str \| None` | `None` | Path to a custom rules YAML file. |
| `auto_load_rules` | `bool` | `True` | Auto-discover `.coderev-rules.yaml` if no rules provided. |

**Examples:**

```python
# Use Claude (default)
reviewer = CodeReviewer()

# Use GPT-4o
reviewer = CodeReviewer(model="gpt-4o")

# Explicit provider and API key
reviewer = CodeReviewer(
    model="gpt-4o",
    provider="openai",
    api_key="sk-...",
)

# Disable cache
reviewer = CodeReviewer(cache_enabled=False)
```

#### Methods

##### `review_code(code, language=None, focus=None, context=None, use_cache=True, rules=None) -> ReviewResult`

Review a code snippet.

```python
result = reviewer.review_code(
    code='def add(a, b): return a + b',
    language="python",
    focus=["bugs", "style"],
)
print(result.summary)
print(f"Score: {result.score}/100")
for issue in result.issues:
    print(f"  [{issue.severity.value}] {issue.message}")
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | `str` | *required* | The code to review. |
| `language` | `str \| None` | `None` | Programming language hint. |
| `focus` | `list[str] \| None` | `None` | Focus areas: `"bugs"`, `"security"`, `"performance"`, `"style"`, `"architecture"`, `"testing"`. |
| `context` | `str \| None` | `None` | Additional context (e.g., file path). |
| `use_cache` | `bool` | `True` | Whether to use/store cached results. |
| `rules` | `RuleSet \| None` | `None` | Override instance rules for this call. |

##### `review_file(file_path, focus=None, use_cache=True, rules=None) -> ReviewResult`

Review a single file from disk.

```python
result = reviewer.review_file("src/main.py", focus=["security"])
```

**Raises:** `FileNotFoundError`, `BinaryFileError`, `ValueError` (file too large), `UnicodeDecodeError`.

##### `review_files(file_paths, focus=None, use_cache=True, rules=None) -> dict[str, ReviewResult]`

Review multiple files. Binary files are automatically skipped.

```python
results = reviewer.review_files(["main.py", "utils.py", "image.png"])
for path, result in results.items():
    print(f"{path}: {result.score}/100 ({len(result.issues)} issues)")
```

##### `review_diff(diff, focus=None, use_cache=True, rules=None) -> ReviewResult`

Review a git diff string.

```python
import subprocess

diff = subprocess.run(
    ["git", "diff", "--staged"],
    capture_output=True, text=True
).stdout

result = reviewer.review_diff(diff)
print(result.summary)
```

##### `review_with_inline_suggestions(code, language=None, focus=None, context=None, use_cache=True, rules=None) -> ReviewResult`

Review code and get line-by-line inline suggestions with precise code replacements.

```python
result = reviewer.review_with_inline_suggestions(
    code=open("main.py").read(),
    language="python",
)
for suggestion in result.suggestions_by_line():
    print(f"{suggestion.line_range}: {suggestion.explanation}")
    print(f"  - {suggestion.original_code}")
    print(f"  + {suggestion.suggested_code}")
```

##### `review_file_with_inline_suggestions(file_path, focus=None, use_cache=True, rules=None) -> ReviewResult`

Convenience method combining file reading with inline suggestions.

```python
result = reviewer.review_file_with_inline_suggestions("main.py")
```

##### `clear_cache() -> int`

Clear all cached review results. Returns the number of entries cleared.

##### `cache_stats() -> dict[str, Any]`

Get cache statistics (total entries, size, expired count, etc.).

##### `prune_cache() -> int`

Remove expired cache entries. Returns the number of entries pruned.

---

### AsyncCodeReviewer

Async version for parallel file processing. Use as an async context manager.

```python
from coderev import AsyncCodeReviewer
```

#### Constructor

```python
AsyncCodeReviewer(
    api_key: str | None = None,
    model: str | None = None,
    config: Config | None = None,
    max_concurrent: int = 5,
    provider: str | None = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | `int` | `5` | Maximum concurrent API calls. Controls rate limiting via semaphore. |

Other parameters match `CodeReviewer`.

#### Usage

```python
import asyncio
from pathlib import Path
from coderev import AsyncCodeReviewer

async def main():
    async with AsyncCodeReviewer(max_concurrent=10) as reviewer:
        results = await reviewer.review_files_async(
            [Path("a.py"), Path("b.py"), Path("c.py")],
            focus=["bugs", "security"],
        )
        for path, result in results.items():
            print(f"{path}: {result.score}/100")

asyncio.run(main())
```

#### Methods

| Method | Description |
|--------|-------------|
| `review_code_async(code, language, focus, context)` | Review a code snippet asynchronously. |
| `review_file_async(file_path, focus)` | Review a single file asynchronously. |
| `review_files_async(file_paths, focus)` | Review multiple files in parallel. |
| `review_diff_async(diff, focus)` | Review a git diff asynchronously. |

#### Convenience Function

```python
from coderev import review_files_parallel

results = asyncio.run(review_files_parallel(
    ["src/main.py", "src/utils.py"],
    model="gpt-4o",
    max_concurrent=5,
))
```

---

### ReviewResult

Returned by all review methods.

```python
from coderev import ReviewResult
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `summary` | `str` | Human-readable review summary. |
| `issues` | `list[Issue]` | List of identified issues. |
| `score` | `int` | Quality score (0-100). `-1` indicates a skipped file. |
| `positive` | `list[str]` | Positive observations about the code. |
| `verdict` | `str \| None` | PR verdict: `"approve"`, `"request_changes"`, or `"comment"`. |
| `inline_suggestions` | `list[InlineSuggestion]` | Line-specific code suggestions. |
| `raw_response` | `dict` | Raw API response for custom parsing. |

| Property/Method | Returns | Description |
|-----------------|---------|-------------|
| `critical_count` | `int` | Number of critical issues. |
| `high_count` | `int` | Number of high-severity issues. |
| `has_blocking_issues` | `bool` | `True` if any critical or high issues exist. |
| `issues_by_severity()` | `list[Issue]` | Issues sorted by severity (critical first). |
| `issues_by_file()` | `dict[str, list[Issue]]` | Issues grouped by file path. |
| `suggestions_by_line()` | `list[InlineSuggestion]` | Inline suggestions sorted by line number. |

---

### Issue

Represents a single code review finding.

```python
from coderev import Issue
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `message` | `str` | Description of the issue. |
| `severity` | `Severity` | `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`. |
| `category` | `Category` | `BUG`, `SECURITY`, `PERFORMANCE`, `STYLE`, or `ARCHITECTURE`. |
| `line` | `int \| None` | Starting line number. |
| `end_line` | `int \| None` | Ending line number. |
| `file` | `str \| None` | File path. |
| `suggestion` | `str \| None` | Human-readable fix suggestion. |
| `code_suggestion` | `str \| None` | Suggested code replacement. |

```python
for issue in result.issues_by_severity():
    print(f"[{issue.severity.value.upper()}] L{issue.line}: {issue.message}")
    if issue.suggestion:
        print(f"  Fix: {issue.suggestion}")
```

---

### InlineSuggestion

A precise, line-level code suggestion with original and replacement code.

```python
from coderev import InlineSuggestion
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `start_line` | `int` | First line of the suggestion. |
| `end_line` | `int` | Last line of the suggestion. |
| `original_code` | `str` | The original code snippet. |
| `suggested_code` | `str` | The suggested replacement. |
| `explanation` | `str` | Why this change is recommended. |
| `severity` | `Severity` | Issue severity. |
| `category` | `Category` | Issue category. |
| `line_range` | `str` *(property)* | Human-readable range, e.g. `"L5"` or `"L5-8"`. |

---

## Configuration

### Config

Loads settings from `.coderev.toml`, environment variables, or constructor arguments.

```python
from coderev import Config
```

#### Loading

```python
# Auto-discover config (cwd → home)
config = Config.load()

# Explicit path
config = Config.load(config_path=Path("my-config.toml"))

# Skip team config resolution
config = Config.load(resolve_extends=False)
```

**Search order:** `.coderev.toml` in current directory, then home directory.

#### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str \| None` | — | Anthropic API key. Env: `CODEREV_API_KEY` or `ANTHROPIC_API_KEY`. |
| `openai_api_key` | `str \| None` | — | OpenAI API key. Env: `OPENAI_API_KEY`. |
| `provider` | `str \| None` | `None` | `"anthropic"` or `"openai"`. Auto-detected if `None`. |
| `model` | `str` | `"claude-3-sonnet-20240229"` | Model name. |
| `focus` | `list[str]` | `["bugs", "security", "performance"]` | Default focus areas. |
| `ignore_patterns` | `list[str]` | `[]` | Glob patterns for files to ignore. |
| `max_file_size` | `int` | `100000` | Max file size in bytes. |
| `language_hints` | `bool` | `True` | Enable language detection from extensions. |
| `github` | `GitHubConfig` | — | GitHub integration settings. |
| `gitlab` | `GitLabConfig` | — | GitLab integration settings. |
| `bitbucket` | `BitbucketConfig` | — | Bitbucket integration settings. |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_provider()` | `str` | Resolved provider name. |
| `get_api_key_for_provider(provider)` | `str \| None` | API key for the specified provider. |
| `validate()` | `list[str]` | List of configuration errors (empty if valid). |

#### Config File Example (`.coderev.toml`)

```toml
[coderev]
model = "claude-3-sonnet-20240229"
focus = ["bugs", "security", "performance"]
ignore_patterns = ["*.test.py", "migrations/*", "*.min.js"]
max_file_size = 100000
language_hints = true

# Optional: team config inheritance
# extends = "gh:myorg/configs/coderev.toml"

[github]
# token = "ghp_xxx"  # or set GITHUB_TOKEN env var

[gitlab]
# token = "glpat-xxx"  # or set GITLAB_TOKEN env var
# api_base = "https://gitlab.example.com"  # for self-hosted

[bitbucket]
# username = "your-username"  # or set BITBUCKET_USERNAME env var
# app_password = "xxx"  # or set BITBUCKET_APP_PASSWORD env var
```

#### Environment Variables

| Variable | Description |
|----------|-------------|
| `CODEREV_API_KEY` | Anthropic API key (primary). |
| `ANTHROPIC_API_KEY` | Anthropic API key (fallback). |
| `OPENAI_API_KEY` | OpenAI API key. |
| `GITHUB_TOKEN` | GitHub personal access token. |
| `GITLAB_TOKEN` | GitLab personal access token. |
| `GITLAB_API_BASE` | GitLab API base URL (self-hosted). |
| `BITBUCKET_USERNAME` | Bitbucket username. |
| `BITBUCKET_APP_PASSWORD` | Bitbucket app password. |

---

## Cost Estimation

### CostEstimator

Estimate API costs before running reviews.

```python
from coderev import CostEstimator
```

#### Constructor

```python
CostEstimator(model: str = "claude-3-sonnet")
```

#### Methods

```python
estimator = CostEstimator(model="gpt-4o")

# Estimate for code string
estimate = estimator.estimate_code(code, language="python")

# Estimate for a single file
estimate = estimator.estimate_file("main.py", focus=["security"])

# Estimate for multiple files (binary files auto-skipped)
estimate = estimator.estimate_files(
    ["main.py", "utils.py", "tests/test_main.py"]
)

# Estimate for a diff
estimate = estimator.estimate_diff(diff_string)

print(estimate.format_cost())     # "$0.0034"
print(estimate.format_tokens())   # "2.4K"
```

### CostEstimate

Returned by all `CostEstimator` methods.

| Attribute | Type | Description |
|-----------|------|-------------|
| `input_tokens` | `int` | Estimated input token count. |
| `estimated_output_tokens` | `int` | Estimated output token count. |
| `model` | `str` | Model name used for pricing. |
| `input_cost_usd` | `float` | Input cost in USD. |
| `output_cost_usd` | `float` | Output cost in USD. |
| `total_cost_usd` | `float` | Total estimated cost in USD. |
| `file_count` | `int` | Number of files included. |
| `skipped_files` | `int` | Number of files skipped (binary, too large, etc.). |
| `total_tokens` | `int` *(property)* | `input_tokens + estimated_output_tokens`. |

#### Standalone Functions

```python
from coderev import count_tokens, get_model_pricing

tokens = count_tokens("def hello(): pass", model="gpt-4o")
input_price, output_price = get_model_pricing("claude-3-sonnet")  # per 1M tokens
```

---

## Custom Rules

Define custom review rules in YAML to enforce project-specific standards.

### Rule

A single review rule.

```python
from coderev import Rule
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique rule identifier. |
| `name` | `str` | Human-readable name. |
| `description` | `str` | What this rule checks. |
| `severity` | `str` | `"critical"`, `"high"`, `"medium"`, or `"low"`. |
| `category` | `str` | `"bug"`, `"security"`, `"performance"`, `"style"`, or `"architecture"`. |
| `pattern` | `str \| None` | Single pattern to match. |
| `patterns` | `list[str]` | Multiple patterns to match. |
| `languages` | `list[str]` | Languages this rule applies to (empty = all). |

### RuleSet

A collection of rules.

```python
from coderev import RuleSet, load_rules, load_rules_from_file

# Auto-discover .coderev-rules.yaml
rules = load_rules()

# Load from specific file
rules = load_rules_from_file("my-rules.yaml")

# Use with reviewer
reviewer = CodeReviewer(rules=rules)

# Or per-review
result = reviewer.review_code(code, rules=rules)
```

#### Built-in Rules

```python
from coderev import list_builtin_rules, get_builtin_rule, BUILTIN_RULES

# List all built-in rule IDs
rule_ids = list_builtin_rules()

# Get a specific built-in rule
rule = get_builtin_rule("no-hardcoded-secrets")
```

#### Rules YAML Format (`.coderev-rules.yaml`)

```yaml
rules:
  - id: no-print-statements
    name: No print statements
    description: Use logging module instead of print()
    severity: medium
    category: style
    pattern: "print("
    languages: [python]

  - id: no-hardcoded-secrets
    name: No hardcoded secrets
    description: API keys and passwords must not be hardcoded
    severity: critical
    category: security
    patterns:
      - "api_key ="
      - "password ="
      - "secret ="

  - id: require-docstrings
    name: Require docstrings
    description: All public functions must have docstrings
    severity: low
    category: style
    languages: [python]
```

---

## Review History

Track and query past reviews.

### ReviewHistory

```python
from coderev import ReviewHistory
```

```python
history = ReviewHistory()

# Query recent reviews
entries = history.get_recent(limit=10)
entries = history.get_by_file("main.py", limit=5)
entries = history.get_by_severity("critical", limit=20)

# Statistics
stats = history.get_stats(days=30)
print(f"Total reviews: {stats.total_reviews}")
print(f"Average score: {stats.average_score:.1f}")

# Export/import
history.export("backup.json")
history.import_from("backup.json")

# Maintenance
history.clear()
```

### ReviewEntry

A single stored review record.

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique entry ID. |
| `timestamp` | `str` | ISO format timestamp. |
| `file_path` | `str \| None` | Reviewed file path. |
| `review_type` | `str` | `"file"`, `"diff"`, `"code"`, or `"pr"`. |
| `model` | `str` | Model used. |
| `score` | `int` | Quality score (0-100). |
| `summary` | `str` | Review summary. |
| `issue_count` | `int` | Total issues found. |
| `critical_count` | `int` | Critical issue count. |
| `high_count` | `int` | High issue count. |
| `medium_count` | `int` | Medium issue count. |
| `low_count` | `int` | Low issue count. |

### HistoryStats

Aggregated statistics from `ReviewHistory.get_stats()`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `total_reviews` | `int` | Total number of reviews. |
| `total_files` | `int` | Unique files reviewed. |
| `total_issues` | `int` | Total issues across all reviews. |
| `average_score` | `float` | Mean quality score. |
| `critical_issues` | `int` | Total critical issues. |
| `high_issues` | `int` | Total high issues. |
| `medium_issues` | `int` | Total medium issues. |
| `low_issues` | `int` | Total low issues. |
| `first_review` | `str \| None` | Timestamp of first review. |
| `last_review` | `str \| None` | Timestamp of most recent review. |
| `reviews_by_type` | `dict[str, int]` | Count by review type. |
| `reviews_by_model` | `dict[str, int]` | Count by model. |

---

## Providers

### BaseProvider

Abstract base class for LLM providers. Extend this to add new providers.

```python
from coderev import BaseProvider
```

| Method | Description |
|--------|-------------|
| `call(system_prompt, user_prompt) -> ProviderResponse` | Synchronous API call. |
| `call_async(system_prompt, user_prompt) -> ProviderResponse` | Asynchronous API call. |
| `parse_json_response(content) -> dict` | Parse JSON from LLM response text. |

### AnthropicProvider

Anthropic Claude provider. Used automatically when model starts with `"claude"`.

### OpenAIProvider

OpenAI GPT provider. Used automatically when model starts with `"gpt-"`, `"o1"`, etc.

### Provider Selection

```python
from coderev import get_provider, detect_provider_from_model

# Auto-detect provider from model name
provider_name = detect_provider_from_model("gpt-4o")  # "openai"
provider_name = detect_provider_from_model("claude-3-sonnet")  # "anthropic"

# Get a provider instance
provider = get_provider(
    provider_name="openai",
    api_key="sk-...",
    model="gpt-4o",
)
```

---

## Utilities

### ReviewCache

File-based cache for review results.

```python
from coderev import ReviewCache

cache = ReviewCache(cache_dir="./my-cache", ttl_hours=24, enabled=True)

# Check for cached result
cached = cache.get(code, model, focus, language)

# Store a result
cache.set(code, model, response_dict, focus, language)

# Maintenance
cache.clear()
cache.prune_expired()
stats = cache.stats()
```

### CodeRevIgnore

Respects `.coderevignore` files (similar to `.gitignore` syntax).

```python
from coderev import CodeRevIgnore

ignore = CodeRevIgnore()  # Auto-discovers .coderevignore
if ignore.should_ignore("path/to/file.min.js"):
    print("Skipped")
```

### `is_binary_file(file_path) -> bool`

Detect binary files using extension checking and content analysis (null bytes, control characters, encoding detection).

```python
from coderev import is_binary_file
from pathlib import Path

is_binary_file(Path("image.png"))  # True
is_binary_file(Path("main.py"))    # False
```

---

## Enums

### Severity

```python
from coderev.reviewer import Severity

Severity.CRITICAL  # .value = "critical", .weight = 4
Severity.HIGH      # .value = "high",     .weight = 3
Severity.MEDIUM    # .value = "medium",   .weight = 2
Severity.LOW       # .value = "low",      .weight = 1
```

### Category

```python
from coderev.reviewer import Category

Category.BUG           # "bug"
Category.SECURITY      # "security"
Category.PERFORMANCE   # "performance"
Category.STYLE         # "style"
Category.ARCHITECTURE  # "architecture"
```

---

## Exceptions

| Exception | Module | Description |
|-----------|--------|-------------|
| `BinaryFileError` | `coderev.reviewer` | Raised when attempting to review a binary file. Has `.file_path` and `.message`. |
| `ProviderError` | `coderev.providers` | Base exception for all provider errors. |
| `RateLimitError` | `coderev.providers` | API rate limit exceeded. Has `.retry_after` (seconds), `.provider`, and `.message` with retry guidance. |
| `RuleValidationError` | `coderev.rules` | Invalid rule definition in YAML. |

```python
from coderev import BinaryFileError, RateLimitError, ProviderError

try:
    result = reviewer.review_file("data.bin")
except BinaryFileError as e:
    print(f"Skipped binary: {e.file_path}")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except ProviderError as e:
    print(f"Provider error: {e}")
```

---

## Convenience Functions

### `review_files_parallel`

One-call parallel review without managing the async context.

```python
import asyncio
from coderev import review_files_parallel

results = asyncio.run(review_files_parallel(
    file_paths=["main.py", "utils.py"],
    api_key=None,         # uses env var
    model="gpt-4o",
    focus=["bugs"],
    max_concurrent=5,
))
```

### `count_tokens(text, model) -> int`

Estimate token count. Uses `tiktoken` for OpenAI models when available, otherwise character-based approximation.

### `get_model_pricing(model) -> tuple[float, float]`

Returns `(input_price_per_1M_tokens, output_price_per_1M_tokens)` in USD.

### `detect_provider_from_model(model) -> str`

Returns `"openai"` or `"anthropic"` based on model name prefix.

### `load_rules(path=None) -> RuleSet`

Auto-discover and load rules from `.coderev-rules.yaml`.

### `find_rules_file() -> Path | None`

Search for a rules file in the current and home directories.

---

## CLI Reference

For CLI usage, run:

```bash
coderev --help
coderev review --help
coderev diff --help
coderev pr --help
coderev mr --help
coderev bpr --help
coderev fix --help
coderev batch --help
coderev estimate --help
coderev tui --help
coderev history --help
coderev config --help
```

See the [README](../README.md) for CLI examples and quick-start guide.
