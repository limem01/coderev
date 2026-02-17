"""Async code review functionality for parallel processing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coderev.config import Config, detect_provider
from coderev.prompts import SYSTEM_PROMPT, build_review_prompt, build_diff_prompt
from coderev.providers import (
    BaseProvider,
    RateLimitError,
    get_provider,
)
from coderev.reviewer import (
    BinaryFileError,
    Issue,
    ReviewResult,
    is_binary_file,
)


class AsyncCodeReviewer:
    """Async code reviewer for parallel file processing.
    
    Uses asyncio to review multiple files concurrently, significantly
    reducing total review time for large codebases.
    
    Supports multiple LLM providers (Anthropic Claude, OpenAI GPT).
    The provider is auto-detected from the model name.
    
    Example:
        async def main():
            # Use Claude (default)
            reviewer = AsyncCodeReviewer(api_key="your-key")
            
            # Use GPT-4
            reviewer = AsyncCodeReviewer(model="gpt-4o", api_key="sk-...")
            
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
        provider: str | None = None,
    ):
        """Initialize async reviewer.
        
        Args:
            api_key: API key for the provider.
            model: Model to use for reviews.
            config: Configuration object.
            max_concurrent: Maximum concurrent API calls (default 5).
            provider: LLM provider ('anthropic' or 'openai'). Auto-detected if not specified.
        """
        self.config = config or Config.load()
        self.model = model or self.config.model
        self.max_concurrent = max_concurrent
        
        # Determine provider
        self.provider_name = provider or self.config.get_provider()
        if model:
            # If model is explicitly provided, detect provider from it
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
        
        self._semaphore: asyncio.Semaphore | None = None
    
    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy-initialize semaphore for rate limiting."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore
    
    async def close(self) -> None:
        """Close the async client (no-op for provider abstraction)."""
        pass
    
    async def __aenter__(self) -> "AsyncCodeReviewer":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
    
    async def _call_api(self, prompt: str) -> dict[str, Any]:
        """Call the LLM API asynchronously.
        
        Uses a semaphore to limit concurrent requests and avoid rate limits.
        """
        async with self.semaphore:
            response = await self._provider.call_async(SYSTEM_PROMPT, prompt)
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
    model: str | None = None,
    focus: list[str] | None = None,
    max_concurrent: int = 5,
    config: Config | None = None,
    provider: str | None = None,
) -> dict[str, ReviewResult]:
    """Convenience function to review files in parallel.
    
    Supports multiple providers (Anthropic, OpenAI).
    
    Example:
        import asyncio
        from coderev.async_reviewer import review_files_parallel
        
        # Use Claude (default)
        results = asyncio.run(review_files_parallel([
            "src/main.py",
            "src/utils.py",
        ]))
        
        # Use GPT-4
        results = asyncio.run(review_files_parallel(
            ["src/main.py"],
            model="gpt-4o",
        ))
    """
    async with AsyncCodeReviewer(
        api_key=api_key,
        model=model,
        config=config,
        max_concurrent=max_concurrent,
        provider=provider,
    ) as reviewer:
        return await reviewer.review_files_async(file_paths, focus)
