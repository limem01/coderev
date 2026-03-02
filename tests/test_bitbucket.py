"""Tests for Bitbucket integration."""

import pytest
from unittest.mock import patch, MagicMock

from coderev.bitbucket import BitbucketClient, PullRequest, detect_language_from_filename


class TestBitbucketClient:
    """Tests for BitbucketClient."""
    
    def test_parse_pr_url_full(self):
        url = "https://bitbucket.org/myworkspace/myrepo/pull-requests/123"
        workspace, repo_slug, pr_id = BitbucketClient.parse_pr_url(url)
        
        assert workspace == "myworkspace"
        assert repo_slug == "myrepo"
        assert pr_id == 123
    
    def test_parse_pr_url_without_protocol(self):
        url = "bitbucket.org/workspace/repo/pull-requests/456"
        workspace, repo_slug, pr_id = BitbucketClient.parse_pr_url(url)
        
        assert workspace == "workspace"
        assert repo_slug == "repo"
        assert pr_id == 456
    
    def test_parse_pr_url_invalid(self):
        with pytest.raises(ValueError, match="Invalid Bitbucket PR URL"):
            BitbucketClient.parse_pr_url("https://example.com/not/a/pr")
    
    def test_parse_pr_url_invalid_github(self):
        with pytest.raises(ValueError, match="Invalid Bitbucket PR URL"):
            BitbucketClient.parse_pr_url("https://github.com/owner/repo/pull/123")
    
    def test_parse_pr_url_invalid_gitlab(self):
        with pytest.raises(ValueError, match="Invalid Bitbucket PR URL"):
            BitbucketClient.parse_pr_url("https://gitlab.com/owner/repo/-/merge_requests/123")
    
    def test_init_requires_credentials(self):
        from coderev.config import Config, BitbucketConfig
        mock_config = MagicMock(spec=Config)
        mock_config.bitbucket = BitbucketConfig(username=None, app_password=None)
        
        with pytest.raises(ValueError, match="Bitbucket credentials required"):
            BitbucketClient(username=None, app_password=None, config=mock_config)
    
    def test_init_requires_both_credentials(self):
        from coderev.config import Config, BitbucketConfig
        mock_config = MagicMock(spec=Config)
        mock_config.bitbucket = BitbucketConfig(username="user", app_password=None)
        
        with pytest.raises(ValueError, match="Bitbucket credentials required"):
            BitbucketClient(username="user", app_password=None, config=mock_config)
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_get_pull_request(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Mock PR metadata response
        pr_response = MagicMock()
        pr_response.json.return_value = {
            "id": 1,
            "title": "Add feature",
            "description": "This PR adds a new feature",
            "source": {"branch": {"name": "feature-branch"}},
            "destination": {"branch": {"name": "main"}},
            "author": {"display_name": "Developer"},
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/1"}},
        }
        
        # Mock diffstat response
        diffstat_response = MagicMock()
        diffstat_response.json.return_value = {
            "values": [
                {
                    "status": "modified",
                    "old": {"path": "main.py"},
                    "new": {"path": "main.py"},
                    "lines_added": 10,
                    "lines_removed": 5,
                },
            ]
        }
        
        # Mock diff response
        diff_response = MagicMock()
        diff_response.text = """diff --git a/main.py b/main.py
--- a/main.py
+++ b/main.py
@@ -1,5 +1,10 @@
+print('hello')
-print('world')
"""
        
        mock_client.get.side_effect = [pr_response, diffstat_response, diff_response]
        
        with BitbucketClient(username="user", app_password="pass") as client:
            pr = client.get_pull_request("workspace", "repo", 1)
        
        assert pr.title == "Add feature"
        assert pr.source_branch == "feature-branch"
        assert pr.destination_branch == "main"
        assert pr.additions == 10
        assert pr.deletions == 5
        assert len(pr.files) == 1
        assert pr.workspace == "workspace"
        assert pr.repo_slug == "repo"
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_post_comment(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        response = MagicMock()
        response.json.return_value = {"id": 1, "content": {"raw": "Test comment"}}
        mock_client.post.return_value = response
        
        with BitbucketClient(username="user", app_password="pass") as client:
            result = client.post_comment("workspace", "repo", 1, "Test comment")
        
        assert result["content"]["raw"] == "Test comment"
        mock_client.post.assert_called_once()
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_post_inline_comment(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        response = MagicMock()
        response.json.return_value = {
            "id": 1,
            "content": {"raw": "Fix this line"},
            "inline": {"path": "main.py", "to": 10},
        }
        mock_client.post.return_value = response
        
        with BitbucketClient(username="user", app_password="pass") as client:
            result = client.post_inline_comment(
                "workspace", "repo", 1, "Fix this line", "main.py", 10
            )
        
        assert result["inline"]["path"] == "main.py"
        assert result["inline"]["to"] == 10
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_approve_pull_request(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        response = MagicMock()
        response.json.return_value = {"approved": True}
        mock_client.post.return_value = response
        
        with BitbucketClient(username="user", app_password="pass") as client:
            result = client.approve_pull_request("workspace", "repo", 1)
        
        assert result["approved"] is True
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_request_changes(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        response = MagicMock()
        response.json.return_value = {"state": "changes_requested"}
        mock_client.post.return_value = response
        
        with BitbucketClient(username="user", app_password="pass") as client:
            result = client.request_changes("workspace", "repo", 1)
        
        assert result["state"] == "changes_requested"


class TestPullRequest:
    """Tests for PullRequest dataclass."""
    
    def test_changed_lines(self):
        pr = PullRequest(
            id=1,
            title="Test",
            description=None,
            source_branch="feature",
            destination_branch="main",
            author="dev",
            files=[],
            additions=100,
            deletions=25,
            url="https://bitbucket.org/workspace/repo/pull-requests/1",
            workspace="workspace",
            repo_slug="repo",
        )
        
        assert pr.changed_lines == 125
    
    def test_minimal_pr(self):
        pr = PullRequest(
            id=42,
            title="Fix bug",
            description="This fixes the bug",
            source_branch="fix/bug-42",
            destination_branch="develop",
            author="fixer",
            files=[{"new_path": "fix.py", "lines_added": 1, "lines_removed": 0}],
            additions=1,
            deletions=0,
            url="https://bitbucket.org/test/project/pull-requests/42",
            workspace="test",
            repo_slug="project",
        )
        
        assert pr.id == 42
        assert pr.author == "fixer"
        assert len(pr.files) == 1


class TestLanguageDetection:
    """Tests for language detection from filenames."""
    
    @pytest.mark.parametrize("filename,expected", [
        ("main.py", "python"),
        ("app.js", "javascript"),
        ("component.tsx", "typescript"),
        ("server.go", "go"),
        ("lib.rs", "rust"),
        ("Model.java", "java"),
        ("script.sh", "bash"),
        ("config.yml", "yaml"),
        ("config.yaml", "yaml"),
        ("data.json", "json"),
        ("README.md", "markdown"),
        ("App.vue", "vue"),
        ("Component.svelte", "svelte"),
        ("unknown.xyz", ""),
    ])
    def test_detect_language(self, filename, expected):
        assert detect_language_from_filename(filename) == expected


class TestBitbucketClientContextManager:
    """Tests for BitbucketClient context manager behavior."""
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_context_manager_closes_client(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        with BitbucketClient(username="user", app_password="pass") as client:
            pass
        
        mock_client.close.assert_called_once()
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_context_manager_returns_self(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        client = BitbucketClient(username="user", app_password="pass")
        with client as ctx:
            assert ctx is client


class TestDiffParsing:
    """Tests for unified diff parsing."""
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_parse_unified_diff_single_file(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        client = BitbucketClient(username="user", app_password="pass")
        
        diff_content = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
+import os
 import sys
 
 print("hello")
"""
        
        result = client._parse_unified_diff(diff_content)
        
        assert "file.py" in result
        assert "+import os" in result["file.py"]
    
    @patch("coderev.bitbucket.httpx.Client")
    def test_parse_unified_diff_multiple_files(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        client = BitbucketClient(username="user", app_password="pass")
        
        diff_content = """diff --git a/file1.py b/file1.py
--- a/file1.py
+++ b/file1.py
@@ -1 +1 @@
-old
+new
diff --git a/file2.py b/file2.py
--- a/file2.py
+++ b/file2.py
@@ -1 +1 @@
-foo
+bar
"""
        
        result = client._parse_unified_diff(diff_content)
        
        assert len(result) == 2
        assert "file1.py" in result
        assert "file2.py" in result
        assert "-old" in result["file1.py"]
        assert "+new" in result["file1.py"]
        assert "-foo" in result["file2.py"]
        assert "+bar" in result["file2.py"]
