"""Bitbucket integration for CodeRev."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from coderev.config import Config


@dataclass
class PullRequest:
    """Represents a Bitbucket pull request."""
    
    id: int
    title: str
    description: str | None
    source_branch: str
    destination_branch: str
    author: str
    files: list[dict[str, Any]]
    additions: int
    deletions: int
    url: str
    workspace: str
    repo_slug: str
    
    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


class BitbucketClient:
    """Client for Bitbucket API interactions."""
    
    API_BASE = "https://api.bitbucket.org/2.0"
    
    def __init__(
        self,
        username: str | None = None,
        app_password: str | None = None,
        config: Config | None = None,
    ):
        self.config = config or Config.load()
        self.username = username or self.config.bitbucket.username
        self.app_password = app_password or self.config.bitbucket.app_password
        
        if not self.username or not self.app_password:
            raise ValueError(
                "Bitbucket credentials required. Set BITBUCKET_USERNAME and "
                "BITBUCKET_APP_PASSWORD environment variables or add to .coderev.toml "
                "under [bitbucket]"
            )
        
        self.client = httpx.Client(
            auth=(self.username, self.app_password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    
    def __enter__(self) -> BitbucketClient:
        return self
    
    def __exit__(self, *args: Any) -> None:
        self.client.close()
    
    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
        """Parse a Bitbucket PR URL into (workspace, repo_slug, pr_id).
        
        Supports URLs like:
        - https://bitbucket.org/workspace/repo/pull-requests/123
        - bitbucket.org/workspace/repo/pull-requests/456
        """
        parsed = urlparse(url)
        
        # If no scheme, urlparse puts everything in path
        if not parsed.scheme:
            path = parsed.path.strip("/")
            # Remove hostname if present
            if path.startswith("bitbucket.org"):
                path = path[len("bitbucket.org"):].strip("/")
        else:
            path = parsed.path.strip("/")
        
        # Match pattern: <workspace>/<repo>/pull-requests/<id>
        match = re.match(r"([^/]+)/([^/]+)/pull-requests/(\d+)", path)
        if not match:
            raise ValueError(f"Invalid Bitbucket PR URL: {url}")
        
        return match.group(1), match.group(2), int(match.group(3))
    
    def get_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> PullRequest:
        """Fetch a pull request with its changed files."""
        # Get PR metadata
        pr_response = self.client.get(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}"
        )
        pr_response.raise_for_status()
        pr_data = pr_response.json()
        
        # Get PR diff/changes
        diffstat_response = self.client.get(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diffstat"
        )
        diffstat_response.raise_for_status()
        diffstat_data = diffstat_response.json()
        
        # Parse diffstat to get files and line counts
        files = []
        additions = 0
        deletions = 0
        
        for item in diffstat_data.get("values", []):
            status = item.get("status")
            old_path = item.get("old", {}).get("path") if item.get("old") else None
            new_path = item.get("new", {}).get("path") if item.get("new") else None
            
            lines_added = item.get("lines_added", 0)
            lines_removed = item.get("lines_removed", 0)
            
            additions += lines_added
            deletions += lines_removed
            
            files.append({
                "old_path": old_path,
                "new_path": new_path,
                "status": status,  # added, removed, modified, renamed
                "lines_added": lines_added,
                "lines_removed": lines_removed,
            })
        
        # Get the actual diff content for each file
        diff_response = self.client.get(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
        )
        diff_response.raise_for_status()
        
        # Parse the unified diff and attach to files
        diff_content = diff_response.text
        file_diffs = self._parse_unified_diff(diff_content)
        
        for file_info in files:
            path = file_info.get("new_path") or file_info.get("old_path")
            if path and path in file_diffs:
                file_info["diff"] = file_diffs[path]
        
        return PullRequest(
            id=pr_id,
            title=pr_data["title"],
            description=pr_data.get("description"),
            source_branch=pr_data["source"]["branch"]["name"],
            destination_branch=pr_data["destination"]["branch"]["name"],
            author=pr_data["author"]["display_name"],
            files=files,
            additions=additions,
            deletions=deletions,
            url=pr_data["links"]["html"]["href"],
            workspace=workspace,
            repo_slug=repo_slug,
        )
    
    def _parse_unified_diff(self, diff_content: str) -> dict[str, str]:
        """Parse unified diff content into a dict of file path -> diff."""
        file_diffs: dict[str, str] = {}
        current_file = None
        current_diff_lines: list[str] = []
        
        for line in diff_content.split("\n"):
            if line.startswith("diff --git"):
                # Save previous file's diff
                if current_file and current_diff_lines:
                    file_diffs[current_file] = "\n".join(current_diff_lines)
                
                # Extract new file path from "diff --git a/path b/path"
                match = re.search(r"b/(.+)$", line)
                if match:
                    current_file = match.group(1)
                    current_diff_lines = []
            elif current_file is not None:
                current_diff_lines.append(line)
        
        # Save last file's diff
        if current_file and current_diff_lines:
            file_diffs[current_file] = "\n".join(current_diff_lines)
        
        return file_diffs
    
    def post_comment(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
        content: str,
    ) -> dict[str, Any]:
        """Post a general comment to a pull request."""
        response = self.client.post(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments",
            json={"content": {"raw": content}},
        )
        response.raise_for_status()
        return response.json()
    
    def post_inline_comment(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
        content: str,
        path: str,
        line: int,
    ) -> dict[str, Any]:
        """Post an inline comment on a specific line of a file."""
        response = self.client.post(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments",
            json={
                "content": {"raw": content},
                "inline": {
                    "path": path,
                    "to": line,
                },
            },
        )
        response.raise_for_status()
        return response.json()
    
    def approve_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> dict[str, Any]:
        """Approve a pull request."""
        response = self.client.post(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/approve"
        )
        response.raise_for_status()
        return response.json()
    
    def unapprove_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> dict[str, Any]:
        """Remove approval from a pull request."""
        response = self.client.delete(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/approve"
        )
        response.raise_for_status()
        return response.json()
    
    def request_changes(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
    ) -> dict[str, Any]:
        """Request changes on a pull request."""
        response = self.client.post(
            f"{self.API_BASE}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/request-changes"
        )
        response.raise_for_status()
        return response.json()


def detect_language_from_filename(filename: str) -> str:
    """Detect language from filename for Bitbucket files."""
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
