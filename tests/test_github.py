"""Tests for GitHub integration."""

import pytest
from unittest.mock import patch, MagicMock

from coderev.github import GitHubClient, PullRequest, detect_language_from_filename


class TestGitHubClient:
    """Tests for GitHubClient."""
    
    def test_parse_pr_url_full(self):
        url = "https://github.com/owner/repo/pull/123"
        owner, repo, pr_num = GitHubClient.parse_pr_url(url)
        
        assert owner == "owner"
        assert repo == "repo"
        assert pr_num == 123
    
    def test_parse_pr_url_without_protocol(self):
        url = "github.com/myorg/myrepo/pull/456"
        owner, repo, pr_num = GitHubClient.parse_pr_url(url)
        
        assert owner == "myorg"
        assert repo == "myrepo"
        assert pr_num == 456
    
    def test_parse_pr_url_invalid(self):
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            GitHubClient.parse_pr_url("https://example.com/not/a/pr")
    
    def test_init_requires_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="GitHub token required"):
                GitHubClient(token=None)
    
    @patch("coderev.github.httpx.Client")
    def test_get_pull_request(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Mock PR metadata response
        pr_response = MagicMock()
        pr_response.json.return_value = {
            "title": "Add feature",
            "body": "This PR adds a new feature",
            "base": {"ref": "main"},
            "head": {"ref": "feature-branch"},
            "user": {"login": "developer"},
            "additions": 50,
            "deletions": 10,
            "html_url": "https://github.com/owner/repo/pull/1",
        }
        
        # Mock files response
        files_response = MagicMock()
        files_response.json.return_value = [
            {"filename": "main.py", "patch": "+print('hello')"},
        ]
        
        mock_client.get.side_effect = [pr_response, files_response]
        
        with GitHubClient(token="test-token") as client:
            pr = client.get_pull_request("owner", "repo", 1)
        
        assert pr.title == "Add feature"
        assert pr.base_branch == "main"
        assert pr.head_branch == "feature-branch"
        assert pr.additions == 50
        assert pr.deletions == 10
        assert len(pr.files) == 1


class TestPullRequest:
    """Tests for PullRequest dataclass."""
    
    def test_changed_lines(self):
        pr = PullRequest(
            number=1,
            title="Test",
            description=None,
            base_branch="main",
            head_branch="feature",
            author="dev",
            files=[],
            additions=100,
            deletions=25,
            url="https://github.com/owner/repo/pull/1",
        )
        
        assert pr.changed_lines == 125


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
        ("unknown.xyz", ""),
    ])
    def test_detect_language(self, filename, expected):
        assert detect_language_from_filename(filename) == expected
