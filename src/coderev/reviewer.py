"""Core code review functionality."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# Binary file detection constants
BINARY_EXTENSIONS = frozenset({
    # Images
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg', '.tiff', '.tif',
    # Audio/Video
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.flac', '.ogg', '.webm',
    # Archives
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz',
    # Documents
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    # Executables/Libraries
    '.exe', '.dll', '.so', '.dylib', '.bin', '.o', '.a', '.pyc', '.pyo', '.class',
    # Fonts
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    # Other binary formats
    '.sqlite', '.db', '.sqlite3', '.pkl', '.pickle', '.npy', '.npz',
    '.psd', '.ai', '.sketch', '.fig',
})

# Number of bytes to sample for binary detection
BINARY_CHECK_SIZE = 8192


def _has_excessive_control_chars(chunk: bytes) -> bool:
    """Check if a byte chunk has too many control characters.
    
    Control characters (bytes 0-31 except tab, newline, carriage return, form feed)
    are rarely found in text files. A high ratio indicates binary content.
    """
    if len(chunk) == 0:
        return False
    
    # Count control characters, excluding common whitespace
    # tab (9), newline (10), form feed (12), carriage return (13)
    non_text_bytes = sum(
        1 for byte in chunk 
        if byte < 32 and byte not in (9, 10, 12, 13)
    )
    
    # If more than 10% control chars, likely binary
    return non_text_bytes / len(chunk) > 0.10


def is_binary_file(file_path: Path) -> bool:
    """
    Detect if a file is binary.
    
    Uses a combination of extension checking and content analysis.
    Properly handles UTF-8 encoded text files with unicode characters.
    Returns True if the file appears to be binary, False otherwise.
    """
    # Check extension first (fast path)
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    
    # Check file content
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(BINARY_CHECK_SIZE)
            
            # Empty files are not binary
            if len(chunk) == 0:
                return False
            
            # Null bytes are a strong indicator of binary content
            if b'\x00' in chunk:
                return True
            
            # Check for excessive control characters first
            # This catches files that might decode but are still binary
            if _has_excessive_control_chars(chunk):
                return True
            
            # Try to decode as UTF-8 - this is the most reliable check
            # for distinguishing text from binary
            try:
                chunk.decode('utf-8')
                # Successfully decoded as UTF-8 without excessive control chars
                return False
            except UnicodeDecodeError:
                pass
            
            # Try other common text encodings
            for encoding in ('latin-1', 'cp1252', 'iso-8859-1'):
                try:
                    chunk.decode(encoding)
                    # Already checked control chars above, so this is text
                    return False
                except UnicodeDecodeError:
                    pass
            
            # Could not decode as any text encoding, treat as binary
            return True
            
    except (OSError, IOError):
        # If we can't read the file, let downstream handling deal with it
        return False

from coderev.cache import ReviewCache
from coderev.config import Config
from coderev.prompts import (
    SYSTEM_PROMPT,
    build_review_prompt,
    build_diff_prompt,
    build_inline_suggestions_prompt,
)
from coderev.providers import (
    BaseProvider,
    RateLimitError,
    ProviderError,
    get_provider,
)
from coderev.rules import RuleSet, load_rules


class BinaryFileError(Exception):
    """Raised when attempting to review a binary file."""
    
    def __init__(self, file_path: Path | str, message: str | None = None):
        self.file_path = Path(file_path)
        self.message = message or f"Cannot review binary file: {file_path}"
        super().__init__(self.message)


class Severity(str, Enum):
    """Issue severity levels."""
    
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    
    @property
    def weight(self) -> int:
        """Get numeric weight for sorting."""
        weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return weights.get(self.value, 0)


class Category(str, Enum):
    """Issue category types."""
    
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    ARCHITECTURE = "architecture"


@dataclass
class InlineSuggestion:
    """Represents a line-by-line inline code suggestion.
    
    This captures both the original lines and the suggested replacement,
    allowing for precise, actionable code improvements.
    """
    
    start_line: int
    end_line: int
    original_code: str
    suggested_code: str
    explanation: str
    severity: Severity
    category: Category
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InlineSuggestion":
        """Create an InlineSuggestion from API response data."""
        return cls(
            start_line=data.get("start_line", 1),
            end_line=data.get("end_line", data.get("start_line", 1)),
            original_code=data.get("original_code", ""),
            suggested_code=data.get("suggested_code", ""),
            explanation=data.get("explanation", ""),
            severity=Severity(data.get("severity", "medium")),
            category=Category(data.get("category", "style")),
        )
    
    @property
    def line_range(self) -> str:
        """Get human-readable line range string."""
        if self.start_line == self.end_line:
            return f"L{self.start_line}"
        return f"L{self.start_line}-{self.end_line}"


@dataclass
class Issue:
    """Represents a single code review issue."""
    
    message: str
    severity: Severity
    category: Category
    line: int | None = None
    end_line: int | None = None
    file: str | None = None
    suggestion: str | None = None
    code_suggestion: str | None = None
    
    @classmethod
    def from_dict(cls, data: dict[str, Any], default_file: str | None = None) -> Issue:
        """Create an Issue from API response data."""
        return cls(
            message=data.get("message", "Unknown issue"),
            severity=Severity(data.get("severity", "medium")),
            category=Category(data.get("category", "bug")),
            line=data.get("line"),
            end_line=data.get("end_line"),
            file=data.get("file", default_file),
            suggestion=data.get("suggestion"),
            code_suggestion=data.get("code_suggestion"),
        )


@dataclass
class ReviewResult:
    """Result of a code review."""
    
    summary: str
    issues: list[Issue] = field(default_factory=list)
    score: int = 0
    positive: list[str] = field(default_factory=list)
    verdict: str | None = None  # For PR reviews
    raw_response: dict[str, Any] = field(default_factory=dict)
    inline_suggestions: list[InlineSuggestion] = field(default_factory=list)
    
    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)
    
    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)
    
    @property
    def has_blocking_issues(self) -> bool:
        return self.critical_count > 0 or self.high_count > 0
    
    def issues_by_severity(self) -> list[Issue]:
        """Return issues sorted by severity (critical first)."""
        return sorted(self.issues, key=lambda i: -i.severity.weight)
    
    def issues_by_file(self) -> dict[str, list[Issue]]:
        """Group issues by file."""
        grouped: dict[str, list[Issue]] = {}
        for issue in self.issues:
            key = issue.file or "<unknown>"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(issue)
        return grouped
    
    def suggestions_by_line(self) -> list[InlineSuggestion]:
        """Return inline suggestions sorted by line number."""
        return sorted(self.inline_suggestions, key=lambda s: s.start_line)


class CodeReviewer:
    """Main code reviewer class.
    
    Supports multiple LLM providers (Anthropic Claude, OpenAI GPT).
    The provider is auto-detected from the model name, or can be explicitly set.
    
    Examples:
        # Use Claude (default)
        reviewer = CodeReviewer()
        
        # Use GPT-4
        reviewer = CodeReviewer(model="gpt-4o", api_key="sk-...")
        
        # Explicit provider
        reviewer = CodeReviewer(model="gpt-4o", provider="openai")
    """
    
    def __init__(
        self,
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
    ):
        """Initialize the code reviewer.
        
        Args:
            api_key: API key for the provider. If not provided, uses config/env vars.
            model: Model name to use. Defaults to config or claude-3-sonnet.
            config: Optional Config object. If not provided, loads from file/env.
            cache_enabled: Whether to enable result caching.
            cache_ttl_hours: Cache TTL in hours. Defaults to 168 (1 week).
            cache_dir: Directory for cache storage.
            provider: LLM provider ('anthropic' or 'openai'). Auto-detected if not specified.
            rules: Pre-loaded RuleSet to use (takes precedence over rules_path).
            rules_path: Path to custom rules YAML file.
            auto_load_rules: If True and no rules provided, auto-discover rules file.
        """
        self.config = config or Config.load()
        self.model = model or self.config.model
        
        # Determine provider
        self.provider_name = provider or self.config.get_provider()
        if model:
            # If model is explicitly provided, detect provider from it
            from coderev.config import detect_provider
            self.provider_name = provider or detect_provider(model)
        
        # Get API key for the determined provider
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = self.config.get_api_key_for_provider(self.provider_name)
        
        if not self.api_key:
            if self.provider_name == "openai":
                raise ValueError(
                    "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                    "or pass api_key parameter."
                )
            else:
                raise ValueError(
                    "API key required. Set CODEREV_API_KEY environment variable "
                    "or pass api_key parameter."
                )
        
        # Initialize the provider
        self._provider: BaseProvider = get_provider(
            provider_name=self.provider_name,
            api_key=self.api_key,
            model=self.model,
        )
        
        # Initialize cache
        self.cache = ReviewCache(
            cache_dir=cache_dir,
            ttl_hours=cache_ttl_hours or 168,  # 1 week default
            enabled=cache_enabled,
        )
        
        # Initialize rules
        if rules:
            self.rules = rules
        elif rules_path:
            self.rules = load_rules(rules_path)
        elif auto_load_rules:
            self.rules = load_rules()  # Auto-discover
        else:
            self.rules = RuleSet()
    
    def _call_api(self, prompt: str) -> dict[str, Any]:
        """Call the LLM API and parse JSON response.
        
        Uses the configured provider (Anthropic or OpenAI).
        
        Raises:
            RateLimitError: When the API rate limit is exceeded, with helpful
                retry guidance and timing information.
            ValueError: When the API response cannot be parsed as JSON.
        """
        response = self._provider.call(SYSTEM_PROMPT, prompt)
        return self._provider.parse_json_response(response.content)
    
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
    
    def review_code(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        context: str | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> ReviewResult:
        """Review a code snippet.
        
        Args:
            code: The code to review.
            language: Programming language (optional, for better analysis).
            focus: List of focus areas (e.g., ['security', 'performance']).
            context: Additional context (e.g., file path).
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            ReviewResult containing the review findings.
        """
        focus = focus or self.config.focus
        effective_rules = rules if rules is not None else self.rules
        
        # Check cache first
        if use_cache:
            cached = self.cache.get(code, self.model, focus, language)
            if cached is not None:
                # Reconstruct ReviewResult from cached data
                issues = [Issue.from_dict(i) for i in cached.get("issues", [])]
                return ReviewResult(
                    summary=cached.get("summary", "Review completed (cached)"),
                    issues=issues,
                    score=cached.get("score", 0),
                    positive=cached.get("positive", []),
                    raw_response=cached,
                )
        
        prompt = build_review_prompt(code, language, focus, context, rules=effective_rules)
        response = self._call_api(prompt)
        
        # Cache the result
        if use_cache:
            self.cache.set(code, self.model, response, focus, language)
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        
        return ReviewResult(
            summary=response.get("summary", "Review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )
    
    def review_file(
        self,
        file_path: Path | str,
        focus: list[str] | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> ReviewResult:
        """Review a single file.
        
        Args:
            file_path: Path to the file to review.
            focus: Optional list of focus areas for the review.
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            ReviewResult containing the review findings.
            
        Raises:
            FileNotFoundError: If the file doesn't exist.
            BinaryFileError: If the file is binary and cannot be reviewed.
            ValueError: If the file exceeds the maximum size limit.
            UnicodeDecodeError: If the file cannot be decoded as UTF-8.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Check for binary files before attempting to read
        if is_binary_file(file_path):
            raise BinaryFileError(file_path)
        
        if file_path.stat().st_size > self.config.max_file_size:
            raise ValueError(
                f"File too large: {file_path.stat().st_size} bytes "
                f"(max: {self.config.max_file_size})"
            )
        
        try:
            code = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise BinaryFileError(
                file_path, 
                f"Cannot decode file as UTF-8 (likely binary): {file_path}"
            ) from e
        
        language = self._detect_language(file_path) if self.config.language_hints else None
        
        result = self.review_code(code, language, focus, context=str(file_path), use_cache=use_cache, rules=rules)
        
        # Set file path on all issues
        for issue in result.issues:
            issue.file = str(file_path)
        
        return result
    
    def review_diff(
        self,
        diff: str,
        focus: list[str] | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> ReviewResult:
        """Review a git diff.
        
        Args:
            diff: The git diff string to review.
            focus: List of focus areas (e.g., ['security', 'performance']).
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            ReviewResult containing the review findings.
        """
        focus = focus or self.config.focus
        effective_rules = rules if rules is not None else self.rules
        
        # Check cache first (use 'diff' as language marker for cache key distinction)
        if use_cache:
            cached = self.cache.get(diff, self.model, focus, language="diff")
            if cached is not None:
                issues = [Issue.from_dict(i) for i in cached.get("issues", [])]
                return ReviewResult(
                    summary=cached.get("summary", "Diff review completed (cached)"),
                    issues=issues,
                    score=cached.get("score", 0),
                    positive=cached.get("positive", []),
                    raw_response=cached,
                )
        
        prompt = build_diff_prompt(diff, focus, rules=effective_rules)
        response = self._call_api(prompt)
        
        # Cache the result
        if use_cache:
            self.cache.set(diff, self.model, response, focus, language="diff")
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        
        return ReviewResult(
            summary=response.get("summary", "Diff review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )
    
    def review_with_inline_suggestions(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        context: str | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> ReviewResult:
        """Review code and generate line-by-line inline suggestions.
        
        This method provides precise, actionable code suggestions that map
        directly to specific lines in the original code. Each suggestion
        includes both the original code and the suggested replacement.
        
        Args:
            code: The code to review.
            language: Programming language (optional, for better analysis).
            focus: List of focus areas (e.g., ['security', 'performance']).
            context: Additional context (e.g., file path).
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            ReviewResult containing inline_suggestions with line-specific fixes.
            
        Example:
            result = reviewer.review_with_inline_suggestions(code, language="python")
            for suggestion in result.suggestions_by_line():
                print(f"{suggestion.line_range}: {suggestion.explanation}")
                print(f"  - {suggestion.original_code}")
                print(f"  + {suggestion.suggested_code}")
        """
        focus = focus or self.config.focus
        effective_rules = rules if rules is not None else self.rules
        
        # Use a different cache key marker for inline suggestions
        cache_language = f"inline:{language}" if language else "inline"
        
        # Check cache first
        if use_cache:
            cached = self.cache.get(code, self.model, focus, cache_language)
            if cached is not None:
                inline_suggestions = [
                    InlineSuggestion.from_dict(s) 
                    for s in cached.get("inline_suggestions", [])
                ]
                return ReviewResult(
                    summary=cached.get("summary", "Review completed (cached)"),
                    issues=[],
                    inline_suggestions=inline_suggestions,
                    score=cached.get("score", 0),
                    positive=cached.get("positive", []),
                    raw_response=cached,
                )
        
        prompt = build_inline_suggestions_prompt(code, language, focus, context, rules=effective_rules)
        response = self._call_api(prompt)
        
        # Cache the result
        if use_cache:
            self.cache.set(code, self.model, response, focus, cache_language)
        
        inline_suggestions = [
            InlineSuggestion.from_dict(s) 
            for s in response.get("inline_suggestions", [])
        ]
        
        return ReviewResult(
            summary=response.get("summary", "Inline review completed"),
            issues=[],
            inline_suggestions=inline_suggestions,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )
    
    def review_file_with_inline_suggestions(
        self,
        file_path: Path | str,
        focus: list[str] | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> ReviewResult:
        """Review a file and generate line-by-line inline suggestions.
        
        This is a convenience method that reads a file and calls
        review_with_inline_suggestions with automatic language detection.
        
        Args:
            file_path: Path to the file to review.
            focus: Optional list of focus areas for the review.
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            ReviewResult containing inline_suggestions with line-specific fixes.
            
        Raises:
            FileNotFoundError: If the file doesn't exist.
            BinaryFileError: If the file is binary and cannot be reviewed.
            ValueError: If the file exceeds the maximum size limit.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if is_binary_file(file_path):
            raise BinaryFileError(file_path)
        
        if file_path.stat().st_size > self.config.max_file_size:
            raise ValueError(
                f"File too large: {file_path.stat().st_size} bytes "
                f"(max: {self.config.max_file_size})"
            )
        
        try:
            code = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise BinaryFileError(
                file_path, 
                f"Cannot decode file as UTF-8 (likely binary): {file_path}"
            ) from e
        
        language = self._detect_language(file_path) if self.config.language_hints else None
        
        return self.review_with_inline_suggestions(
            code, language, focus, context=str(file_path), use_cache=use_cache, rules=rules
        )
    
    def review_files(
        self,
        file_paths: list[Path | str],
        focus: list[str] | None = None,
        use_cache: bool = True,
        rules: RuleSet | None = None,
    ) -> dict[str, ReviewResult]:
        """Review multiple files and return results by file.
        
        Binary files are automatically skipped with a descriptive message.
        
        Args:
            file_paths: List of file paths to review.
            focus: List of focus areas for the review.
            use_cache: Whether to use cached results if available.
            rules: Optional rules to use (defaults to instance rules).
            
        Returns:
            Dictionary mapping file paths to their review results.
        """
        results = {}
        for path in file_paths:
            path = Path(path)
            try:
                results[str(path)] = self.review_file(path, focus, use_cache=use_cache, rules=rules)
            except BinaryFileError as e:
                results[str(path)] = ReviewResult(
                    summary=f"Skipped: {e.message}",
                    issues=[],
                    score=-1,  # Indicates skipped, not reviewed
                )
            except Exception as e:
                results[str(path)] = ReviewResult(
                    summary=f"Error reviewing file: {e}",
                    issues=[],
                    score=0,
                )
        return results
    
    def clear_cache(self) -> int:
        """Clear all cached review results.
        
        Returns:
            Number of cache entries cleared.
        """
        return self.cache.clear()
    
    def cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache stats (total_entries, size, expired, etc.).
        """
        return self.cache.stats()
    
    def prune_cache(self) -> int:
        """Remove expired cache entries.
        
        Returns:
            Number of entries pruned.
        """
        return self.cache.prune_expired()
