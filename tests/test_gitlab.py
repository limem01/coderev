"""Tests for GitLab integration."""

import pytest
from unittest.mock import patch, MagicMock

from coderev.gitlab import GitLabClient, MergeRequest, detect_language_from_filename


class TestGitLabClient:
    """Tests for GitLabClient."""
    
    def test_parse_mr_url_full(self):
        url = "https://gitlab.com/owner/repo/-/merge_requests/123"
        project_path, mr_iid = GitLabClient.parse_mr_url(url)
        
        assert project_path == "owner/repo"
        assert mr_iid == 123
    
    def test_parse_mr_url_nested_group(self):
        url = "https://gitlab.com/group/subgroup/project/-/merge_requests/456"
        project_path, mr_iid = GitLabClient.parse_mr_url(url)
        
        assert project_path == "group/subgroup/project"
        assert mr_iid == 456
    
    def test_parse_mr_url_self_hosted(self):
        url = "https://gitlab.example.com/myorg/myrepo/-/merge_requests/789"
        project_path, mr_iid = GitLabClient.parse_mr_url(url)
        
        assert project_path == "myorg/myrepo"
        assert mr_iid == 789
    
    def test_parse_mr_url_without_protocol(self):
        url = "gitlab.com/owner/repo/-/merge_requests/101"
        project_path, mr_iid = GitLabClient.parse_mr_url(url)
        
        assert project_path == "owner/repo"
        assert mr_iid == 101
    
    def test_parse_mr_url_invalid(self):
        with pytest.raises(ValueError, match="Invalid GitLab MR URL"):
            GitLabClient.parse_mr_url("https://example.com/not/a/mr")
    
    def test_parse_mr_url_invalid_github(self):
        with pytest.raises(ValueError, match="Invalid GitLab MR URL"):
            GitLabClient.parse_mr_url("https://github.com/owner/repo/pull/123")
    
    def test_init_requires_token(self):
        from coderev.config import Config, GitLabConfig
        mock_config = MagicMock(spec=Config)
        mock_config.gitlab = GitLabConfig(token=None, api_base=None)
        
        with pytest.raises(ValueError, match="GitLab token required"):
            GitLabClient(token=None, config=mock_config)
    
    @patch("coderev.gitlab.httpx.Client")
    def test_get_merge_request(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Mock MR metadata response
        mr_response = MagicMock()
        mr_response.json.return_value = {
            "iid": 1,
            "title": "Add feature",
            "description": "This MR adds a new feature",
            "source_branch": "feature-branch",
            "target_branch": "main",
            "author": {"username": "developer"},
            "web_url": "https://gitlab.com/owner/repo/-/merge_requests/1",
            "project_id": 123,
        }
        
        # Mock changes response
        changes_response = MagicMock()
        changes_response.json.return_value = {
            "changes": [
                {
                    "old_path": "main.py",
                    "new_path": "main.py",
                    "diff": "+print('hello')\n-print('world')",
                    "new_file": False,
                    "renamed_file": False,
                    "deleted_file": False,
                },
            ]
        }
        
        mock_client.get.side_effect = [mr_response, changes_response]
        
        with GitLabClient(token="test-token") as client:
            mr = client.get_merge_request("owner/repo", 1)
        
        assert mr.title == "Add feature"
        assert mr.source_branch == "feature-branch"
        assert mr.target_branch == "main"
        assert mr.additions == 1
        assert mr.deletions == 1
        assert len(mr.files) == 1
        assert mr.project_id == 123
    
    @patch("coderev.gitlab.httpx.Client")
    def test_post_note(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        response = MagicMock()
        response.json.return_value = {"id": 1, "body": "Test note"}
        mock_client.post.return_value = response
        
        with GitLabClient(token="test-token") as client:
            result = client.post_note(123, 1, "Test comment")
        
        assert result["body"] == "Test note"
        mock_client.post.assert_called_once()
    
    @patch("coderev.gitlab.httpx.Client")
    def test_custom_api_base(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        client = GitLabClient(
            token="test-token",
            api_base="https://gitlab.mycompany.com/api/v4",
        )
        
        assert client.api_base == "https://gitlab.mycompany.com/api/v4"


class TestMergeRequest:
    """Tests for MergeRequest dataclass."""
    
    def test_changed_lines(self):
        mr = MergeRequest(
            iid=1,
            title="Test",
            description=None,
            source_branch="feature",
            target_branch="main",
            author="dev",
            files=[],
            additions=100,
            deletions=25,
            url="https://gitlab.com/owner/repo/-/merge_requests/1",
            project_id=123,
        )
        
        assert mr.changed_lines == 125
    
    def test_minimal_mr(self):
        mr = MergeRequest(
            iid=42,
            title="Fix bug",
            description="This fixes the bug",
            source_branch="fix/bug-42",
            target_branch="develop",
            author="fixer",
            files=[{"new_path": "fix.py", "diff": "+fixed"}],
            additions=1,
            deletions=0,
            url="https://gitlab.com/test/project/-/merge_requests/42",
            project_id=456,
        )
        
        assert mr.iid == 42
        assert mr.author == "fixer"
        assert len(mr.files) == 1


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


class TestGitLabClientContextManager:
    """Tests for GitLabClient context manager behavior."""
    
    @patch("coderev.gitlab.httpx.Client")
    def test_context_manager_closes_client(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        with GitLabClient(token="test-token") as client:
            pass
        
        mock_client.close.assert_called_once()
    
    @patch("coderev.gitlab.httpx.Client")
    def test_context_manager_returns_self(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        client = GitLabClient(token="test-token")
        with client as ctx:
            assert ctx is client
