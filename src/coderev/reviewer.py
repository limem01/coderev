"""Core code review functionality."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import anthropic


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


def is_binary_file(file_path: Path) -> bool:
    """
    Detect if a file is binary.
    
    Uses a combination of extension checking and content analysis.
    Returns True if the file appears to be binary, False otherwise.
    """
    # Check extension first (fast path)
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    
    # Check file content for null bytes (binary indicator)
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(BINARY_CHECK_SIZE)
            # Null bytes are a strong indicator of binary content
            if b'\x00' in chunk:
                return True
            # Check for high ratio of non-printable characters
            # Allow common whitespace and printable ASCII
            non_text_bytes = sum(
                1 for byte in chunk 
                if byte < 32 and byte not in (9, 10, 13)  # tab, newline, carriage return
            )
            # If more than 10% non-text bytes, likely binary
            if len(chunk) > 0 and non_text_bytes / len(chunk) > 0.10:
                return True
    except (OSError, IOError):
        # If we can't read the file, let downstream handling deal with it
        return False
    
    return False

from coderev.config import Config
from coderev.prompts import SYSTEM_PROMPT, build_review_prompt, build_diff_prompt


class BinaryFileError(Exception):
    """Raised when attempting to review a binary file."""
    
    def __init__(self, file_path: Path | str, message: str | None = None):
        self.file_path = Path(file_path)
        self.message = message or f"Cannot review binary file: {file_path}"
        super().__init__(self.message)


class RateLimitError(Exception):
    """Raised when the API rate limit is exceeded.
    
    Provides helpful information about retry timing and suggestions.
    """
    
    def __init__(
        self,
        message: str | None = None,
        retry_after: float | None = None,
        original_error: Exception | None = None,
    ):
        self.retry_after = retry_after
        self.original_error = original_error
        
        if message:
            self.message = message
        else:
            self.message = self._build_message()
        
        super().__init__(self.message)
    
    def _build_message(self) -> str:
        """Build a helpful error message with retry guidance."""
        parts = ["API rate limit exceeded."]
        
        if self.retry_after:
            if self.retry_after < 60:
                parts.append(f"Retry after: {self.retry_after:.0f} seconds.")
            else:
                minutes = self.retry_after / 60
                parts.append(f"Retry after: {minutes:.1f} minutes.")
        
        parts.append("\nSuggestions:")
        parts.append("  - Wait and retry the request")
        parts.append("  - Review fewer files at once")
        parts.append("  - Use --focus to limit review scope")
        parts.append("  - Check your API plan limits at console.anthropic.com")
        
        return "\n".join(parts)


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


class CodeReviewer:
    """Main code reviewer class."""
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        config: Config | None = None,
    ):
        self.config = config or Config.load()
        self.api_key = api_key or self.config.api_key
        self.model = model or self.config.model
        
        if not self.api_key:
            raise ValueError(
                "API key required. Set CODEREV_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
    
    def _call_api(self, prompt: str) -> dict[str, Any]:
        """Call the Anthropic API and parse JSON response.
        
        Raises:
            RateLimitError: When the API rate limit is exceeded, with helpful
                retry guidance and timing information.
            ValueError: When the API response cannot be parsed as JSON.
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as e:
            # Extract retry-after header if available
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_header = e.response.headers.get('retry-after')
                if retry_header:
                    try:
                        retry_after = float(retry_header)
                    except (ValueError, TypeError):
                        pass
            
            raise RateLimitError(
                retry_after=retry_after,
                original_error=e,
            ) from e
        except anthropic.APIStatusError as e:
            # Handle other API errors with context
            if e.status_code == 429:
                # Sometimes rate limits come as 429 status
                raise RateLimitError(
                    message=f"API rate limit exceeded (HTTP 429): {e.message}",
                    original_error=e,
                ) from e
            raise
        
        response_text = message.content[0].text
        
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
        if json_match:
            response_text = json_match.group(1)
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            # Try to salvage partial JSON
            response_text = response_text.strip()
            if not response_text.endswith("}"):
                response_text += "}"
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                raise ValueError(f"Failed to parse API response as JSON: {e}")
    
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
    ) -> ReviewResult:
        """Review a code snippet."""
        focus = focus or self.config.focus
        prompt = build_review_prompt(code, language, focus, context)
        
        response = self._call_api(prompt)
        
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
    ) -> ReviewResult:
        """Review a single file.
        
        Args:
            file_path: Path to the file to review.
            focus: Optional list of focus areas for the review.
            
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
        
        result = self.review_code(code, language, focus, context=str(file_path))
        
        # Set file path on all issues
        for issue in result.issues:
            issue.file = str(file_path)
        
        return result
    
    def review_diff(
        self,
        diff: str,
        focus: list[str] | None = None,
    ) -> ReviewResult:
        """Review a git diff."""
        focus = focus or self.config.focus
        prompt = build_diff_prompt(diff, focus)
        
        response = self._call_api(prompt)
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        
        return ReviewResult(
            summary=response.get("summary", "Diff review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )
    
    def review_files(
        self,
        file_paths: list[Path | str],
        focus: list[str] | None = None,
    ) -> dict[str, ReviewResult]:
        """Review multiple files and return results by file.
        
        Binary files are automatically skipped with a descriptive message.
        """
        results = {}
        for path in file_paths:
            path = Path(path)
            try:
                results[str(path)] = self.review_file(path, focus)
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
