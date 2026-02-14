"""CodeRev - AI-powered code review CLI tool."""

from coderev.reviewer import (
    CodeReviewer,
    ReviewResult,
    Issue,
    BinaryFileError,
    is_binary_file,
)
from coderev.config import Config
from coderev.ignore import CodeRevIgnore

__version__ = "0.3.3"
__all__ = [
    "CodeReviewer",
    "ReviewResult", 
    "Issue",
    "BinaryFileError",
    "is_binary_file",
    "Config",
    "CodeRevIgnore",
]
