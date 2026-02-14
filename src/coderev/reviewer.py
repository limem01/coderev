"""Core code review functionality."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import anthropic

from coderev.config import Config
from coderev.prompts import SYSTEM_PROMPT, build_review_prompt, build_diff_prompt


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
        """Call the Anthropic API and parse JSON response."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        
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
        """Review a single file."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if file_path.stat().st_size > self.config.max_file_size:
            raise ValueError(
                f"File too large: {file_path.stat().st_size} bytes "
                f"(max: {self.config.max_file_size})"
            )
        
        code = file_path.read_text(encoding="utf-8")
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
        """Review multiple files and return results by file."""
        results = {}
        for path in file_paths:
            path = Path(path)
            try:
                results[str(path)] = self.review_file(path, focus)
            except Exception as e:
                results[str(path)] = ReviewResult(
                    summary=f"Error reviewing file: {e}",
                    issues=[],
                    score=0,
                )
        return results
