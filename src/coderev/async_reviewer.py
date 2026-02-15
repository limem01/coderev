"""Async code review functionality for parallel processing."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import anthropic

from coderev.config import Config
from coderev.prompts import SYSTEM_PROMPT, build_review_prompt, build_diff_prompt
from coderev.reviewer import (
    BinaryFileError,
    Issue,
    RateLimitError,
    ReviewResult,
    is_binary_file,
)


class AsyncCodeReviewer:
    """Async code reviewer for parallel file processing.
    
    Uses asyncio to review multiple files concurrently, significantly
    reducing total review time for large codebases.
    
    Example:
        async def main():
            reviewer = AsyncCodeReviewer(api_key="your-key")
            files = [Path("a.py"), Path("b.py"), Path("c.py")]
            results = await reviewer.review_files_async(files)
            for path, result in results.items():
                print(f"{path}: {result.score}/100")
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        config: Config | None = None,
        max_concurrent: int = 5,
    ):
        """Initialize async reviewer.
        
        Args:
            api_key: Anthropic API key.
            model: Model to use for reviews.
            config: Configuration object.
            max_concurrent: Maximum concurrent API calls (default 5).
        """
        self.config = config or Config.load()
        self.api_key = api_key or self.config.api_key
        self.model = model or self.config.model
        self.max_concurrent = max_concurrent
        
        if not self.api_key:
            raise ValueError(
                "API key required. Set CODEREV_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self._client: anthropic.AsyncAnthropic | None = None
        self._semaphore: asyncio.Semaphore | None = None
    
    @property
    def client(self) -> anthropic.AsyncAnthropic:
        """Lazy-initialize async client."""
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client
    
    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy-initialize semaphore for rate limiting."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore
    
    async def close(self) -> None:
        """Close the async client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
    
    async def __aenter__(self) -> "AsyncCodeReviewer":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
    
    async def _call_api(self, prompt: str) -> dict[str, Any]:
        """Call the Anthropic API asynchronously.
        
        Uses a semaphore to limit concurrent requests and avoid rate limits.
        """
        async with self.semaphore:
            try:
                message = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
            except anthropic.RateLimitError as e:
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
                if e.status_code == 429:
                    raise RateLimitError(
                        message=f"API rate limit exceeded (HTTP 429): {e.message}",
                        original_error=e,
                    ) from e
                raise
        
        response_text = message.content[0].text
        
        # Extract JSON from response
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
        if json_match:
            response_text = json_match.group(1)
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
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
    
    async def review_code_async(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        context: str | None = None,
    ) -> ReviewResult:
        """Review a code snippet asynchronously."""
        focus = focus or self.config.focus
        prompt = build_review_prompt(code, language, focus, context)
        
        response = await self._call_api(prompt)
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        
        return ReviewResult(
            summary=response.get("summary", "Review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )
    
    async def review_file_async(
        self,
        file_path: Path | str,
        focus: list[str] | None = None,
    ) -> ReviewResult:
        """Review a single file asynchronously.
        
        Args:
            file_path: Path to the file to review.
            focus: Optional list of focus areas for the review.
            
        Returns:
            ReviewResult containing the review findings.
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
        
        # File I/O is blocking, but typically fast enough
        # For very large codebases, could use aiofiles
        try:
            code = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise BinaryFileError(
                file_path,
                f"Cannot decode file as UTF-8 (likely binary): {file_path}"
            ) from e
        
        language = self._detect_language(file_path) if self.config.language_hints else None
        
        result = await self.review_code_async(code, language, focus, context=str(file_path))
        
        for issue in result.issues:
            issue.file = str(file_path)
        
        return result
    
    async def _review_file_safe(
        self,
        file_path: Path,
        focus: list[str] | None,
    ) -> tuple[str, ReviewResult]:
        """Review a file with error handling, returning (path, result) tuple."""
        path_str = str(file_path)
        try:
            result = await self.review_file_async(file_path, focus)
            return (path_str, result)
        except BinaryFileError as e:
            return (path_str, ReviewResult(
                summary=f"Skipped: {e.message}",
                issues=[],
                score=-1,
            ))
        except Exception as e:
            return (path_str, ReviewResult(
                summary=f"Error reviewing file: {e}",
                issues=[],
                score=0,
            ))
    
    async def review_files_async(
        self,
        file_paths: list[Path | str],
        focus: list[str] | None = None,
    ) -> dict[str, ReviewResult]:
        """Review multiple files in parallel.
        
        Uses asyncio.gather to process files concurrently, bounded by
        max_concurrent to avoid overwhelming the API.
        
        Args:
            file_paths: List of file paths to review.
            focus: Optional list of focus areas for the review.
            
        Returns:
            Dictionary mapping file paths to their review results.
        """
        paths = [Path(p) for p in file_paths]
        
        tasks = [
            self._review_file_safe(path, focus)
            for path in paths
        ]
        
        results_list = await asyncio.gather(*tasks)
        
        return dict(results_list)
    
    async def review_diff_async(
        self,
        diff: str,
        focus: list[str] | None = None,
    ) -> ReviewResult:
        """Review a git diff asynchronously."""
        focus = focus or self.config.focus
        prompt = build_diff_prompt(diff, focus)
        
        response = await self._call_api(prompt)
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        
        return ReviewResult(
            summary=response.get("summary", "Diff review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            raw_response=response,
        )


async def review_files_parallel(
    file_paths: list[Path | str],
    api_key: str | None = None,
    focus: list[str] | None = None,
    max_concurrent: int = 5,
    config: Config | None = None,
) -> dict[str, ReviewResult]:
    """Convenience function to review files in parallel.
    
    Example:
        import asyncio
        from coderev.async_reviewer import review_files_parallel
        
        results = asyncio.run(review_files_parallel([
            "src/main.py",
            "src/utils.py",
            "src/config.py",
        ]))
    """
    async with AsyncCodeReviewer(
        api_key=api_key,
        config=config,
        max_concurrent=max_concurrent,
    ) as reviewer:
        return await reviewer.review_files_async(file_paths, focus)
