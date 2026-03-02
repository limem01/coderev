"""GitLab integration for CodeRev."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, quote

import httpx

from coderev.config import Config


@dataclass
class MergeRequest:
    """Represents a GitLab merge request."""
    
    iid: int  # Internal ID within the project
    title: str
    description: str | None
    source_branch: str
    target_branch: str
    author: str
    files: list[dict[str, Any]]
    additions: int
    deletions: int
    url: str
    project_id: int
    
    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


class GitLabClient:
    """Client for GitLab API interactions."""
    
    DEFAULT_API_BASE = "https://gitlab.com/api/v4"
    
    def __init__(
        self,
        token: str | None = None,
        config: Config | None = None,
        api_base: str | None = None,
    ):
        self.config = config or Config.load()
        self.token = token or self.config.gitlab.token
        self.api_base = api_base or self.config.gitlab.api_base or self.DEFAULT_API_BASE
        
        if not self.token:
            raise ValueError(
                "GitLab token required. Set GITLAB_TOKEN environment variable "
                "or add to .coderev.toml under [gitlab]"
            )
        
        self.client = httpx.Client(
            headers={
                "PRIVATE-TOKEN": self.token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    
    def __enter__(self) -> GitLabClient:
        return self
    
    def __exit__(self, *args: Any) -> None:
        self.client.close()
    
    @staticmethod
    def parse_mr_url(url: str) -> tuple[str, int]:
        """Parse a GitLab MR URL into (project_path, mr_iid).
        
        Supports URLs like:
        - https://gitlab.com/owner/repo/-/merge_requests/123
        - https://gitlab.example.com/group/subgroup/repo/-/merge_requests/456
        - gitlab.com/owner/repo/-/merge_requests/123
        """
        parsed = urlparse(url)
        
        # If no scheme, urlparse puts everything in path
        if not parsed.scheme:
            # Remove hostname from path (e.g., "gitlab.com/owner/repo/-/merge_requests/123")
            path = parsed.path.strip("/")
            # Remove the hostname part (everything before the first / after gitlab domain)
            if path.startswith("gitlab"):
                parts = path.split("/", 1)
                if len(parts) > 1:
                    path = parts[1]
        else:
            path = parsed.path.strip("/")
        
        # Match pattern: <project_path>/-/merge_requests/<iid>
        match = re.match(r"(.+?)/-/merge_requests/(\d+)", path)
        if not match:
            raise ValueError(f"Invalid GitLab MR URL: {url}")
        
        return match.group(1), int(match.group(2))
    
    def _get_project_id(self, project_path: str) -> int:
        """Get the project ID from its path."""
        encoded_path = quote(project_path, safe="")
        response = self.client.get(f"{self.api_base}/projects/{encoded_path}")
        response.raise_for_status()
        return response.json()["id"]
    
    def get_merge_request(
        self,
        project_path: str,
        mr_iid: int,
    ) -> MergeRequest:
        """Fetch a merge request with its changed files."""
        encoded_path = quote(project_path, safe="")
        
        # Get MR metadata
        mr_response = self.client.get(
            f"{self.api_base}/projects/{encoded_path}/merge_requests/{mr_iid}"
        )
        mr_response.raise_for_status()
        mr_data = mr_response.json()
        
        # Get MR changes (includes diffs)
        changes_response = self.client.get(
            f"{self.api_base}/projects/{encoded_path}/merge_requests/{mr_iid}/changes"
        )
        changes_response.raise_for_status()
        changes_data = changes_response.json()
        
        # Calculate additions/deletions from changes
        additions = 0
        deletions = 0
        files = []
        
        for change in changes_data.get("changes", []):
            # Count additions/deletions from diff
            diff = change.get("diff", "")
            for line in diff.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
            
            files.append({
                "old_path": change.get("old_path"),
                "new_path": change.get("new_path"),
                "diff": diff,
                "new_file": change.get("new_file", False),
                "renamed_file": change.get("renamed_file", False),
                "deleted_file": change.get("deleted_file", False),
            })
        
        return MergeRequest(
            iid=mr_iid,
            title=mr_data["title"],
            description=mr_data.get("description"),
            source_branch=mr_data["source_branch"],
            target_branch=mr_data["target_branch"],
            author=mr_data["author"]["username"],
            files=files,
            additions=additions,
            deletions=deletions,
            url=mr_data["web_url"],
            project_id=mr_data["project_id"],
        )
    
    def post_note(
        self,
        project_id: int,
        mr_iid: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a comment (note) to a merge request."""
        response = self.client.post(
            f"{self.api_base}/projects/{project_id}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        response.raise_for_status()
        return response.json()
    
    def post_discussion(
        self,
        project_id: int,
        mr_iid: int,
        body: str,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Post a discussion (threaded comment) to a merge request.
        
        For inline comments, provide a position dict with:
        - base_sha: SHA of the base commit
        - start_sha: SHA of the start commit
        - head_sha: SHA of the head commit
        - position_type: "text"
        - new_path: file path
        - new_line: line number (for additions)
        - old_line: line number (for deletions)
        """
        payload: dict[str, Any] = {"body": body}
        
        if position:
            payload["position"] = position
        
        response = self.client.post(
            f"{self.api_base}/projects/{project_id}/merge_requests/{mr_iid}/discussions",
            json=payload,
        )
        response.raise_for_status()
        return response.json()
    
    def approve_merge_request(
        self,
        project_id: int,
        mr_iid: int,
    ) -> dict[str, Any]:
        """Approve a merge request."""
        response = self.client.post(
            f"{self.api_base}/projects/{project_id}/merge_requests/{mr_iid}/approve"
        )
        response.raise_for_status()
        return response.json()
    
    def unapprove_merge_request(
        self,
        project_id: int,
        mr_iid: int,
    ) -> dict[str, Any]:
        """Remove approval from a merge request."""
        response = self.client.post(
            f"{self.api_base}/projects/{project_id}/merge_requests/{mr_iid}/unapprove"
        )
        response.raise_for_status()
        return response.json()


def detect_language_from_filename(filename: str) -> str:
    """Detect language from filename for GitLab files."""
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
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".vue": "vue",
        ".svelte": "svelte",
    }
    
    for ext, lang in extension_map.items():
        if filename.endswith(ext):
            return lang
    return ""
