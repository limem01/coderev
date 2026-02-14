"""GitHub integration for CodeRev."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from coderev.config import Config


@dataclass
class PullRequest:
    """Represents a GitHub pull request."""
    
    number: int
    title: str
    description: str | None
    base_branch: str
    head_branch: str
    author: str
    files: list[dict[str, Any]]
    additions: int
    deletions: int
    url: str
    
    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


class GitHubClient:
    """Client for GitHub API interactions."""
    
    API_BASE = "https://api.github.com"
    
    def __init__(self, token: str | None = None, config: Config | None = None):
        self.config = config or Config.load()
        self.token = token or self.config.github.token
        
        if not self.token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN environment variable "
                "or add to .coderev.toml"
            )
        
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
    
    def __enter__(self) -> GitHubClient:
        return self
    
    def __exit__(self, *args: Any) -> None:
        self.client.close()
    
    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
        """Parse a GitHub PR URL into (owner, repo, pr_number)."""
        # Handle URLs like:
        # https://github.com/owner/repo/pull/123
        # github.com/owner/repo/pull/123
        
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        
        match = re.match(r"([^/]+)/([^/]+)/pull/(\d+)", path)
        if not match:
            raise ValueError(f"Invalid GitHub PR URL: {url}")
        
        return match.group(1), match.group(2), int(match.group(3))
    
    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> PullRequest:
        """Fetch a pull request with its changed files."""
        # Get PR metadata
        pr_response = self.client.get(
            f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
        )
        pr_response.raise_for_status()
        pr_data = pr_response.json()
        
        # Get PR files
        files_response = self.client.get(
            f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        )
        files_response.raise_for_status()
        files_data = files_response.json()
        
        return PullRequest(
            number=pr_number,
            title=pr_data["title"],
            description=pr_data.get("body"),
            base_branch=pr_data["base"]["ref"],
            head_branch=pr_data["head"]["ref"],
            author=pr_data["user"]["login"],
            files=files_data,
            additions=pr_data["additions"],
            deletions=pr_data["deletions"],
            url=pr_data["html_url"],
        )
    
    def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",  # APPROVE, REQUEST_CHANGES, COMMENT
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Post a review to a pull request."""
        payload: dict[str, Any] = {
            "body": body,
            "event": event,
        }
        
        if comments:
            payload["comments"] = comments
        
        response = self.client.post(
            f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        response.raise_for_status()
        return response.json()
    
    def post_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ) -> dict[str, Any]:
        """Post a single review comment on a specific line."""
        response = self.client.post(
            f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            json={
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
            },
        )
        response.raise_for_status()
        return response.json()


def detect_language_from_filename(filename: str) -> str:
    """Detect language from filename for GitHub files."""
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
    }
    
    for ext, lang in extension_map.items():
        if filename.endswith(ext):
            return lang
    return ""
