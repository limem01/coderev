"""CodeRev - AI-powered code review CLI tool."""

from coderev.reviewer import (
    CodeReviewer,
    ReviewResult,
    Issue,
    BinaryFileError,
    RateLimitError,
    is_binary_file,
)
from coderev.async_reviewer import AsyncCodeReviewer, review_files_parallel
from coderev.config import Config
from coderev.ignore import CodeRevIgnore

__version__ = "0.3.3"
__all__ = [
    "CodeReviewer",
    "AsyncCodeReviewer",
    "review_files_parallel",
    "ReviewResult", 
    "Issue",
    "BinaryFileError",
    "RateLimitError",
    "is_binary_file",
    "Config",
    "CodeRevIgnore",
]
