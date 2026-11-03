"""Status lines from `diff`, `pr`, `mr` and `bpr` must not corrupt machine-readable stdout.

`coderev pr 123 --format json | jq` failed to parse: `pr`, `mr` and `bpr`
printed "Fetching PR #...", the PR/MR title, the additions/deletions line and
"Analyzing changes..." to stdout ahead of the JSON, and with `--post-comments`
"Posting review to ..." / "Review posted successfully!" after it. All four
commands (including `diff`) also printed config errors, "No changes to review" /
"No reviewable file changes found" and error messages to stdout. For
json/markdown/sarif, stdout belongs to the report, so those lines go to stderr.
Rich output keeps them on stdout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.bitbucket import BitbucketClient
from coderev.cli import main
from coderev.github import GitHubClient
from coderev.gitlab import GitLabClient
from coderev.reviewer import RateLimitError, ReviewResult

SAMPLE_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
 x = 1
+y = 2
"""

API_RESPONSE = {
    "summary": "Looks fine",
    "issues": [],
    "score": 88,
    "positive": [],
    "verdict": "approve",
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_config():
    with patch("coderev.cli.Config") as config_cls:
        config = MagicMock()
        config.validate.return_value = []
        config_cls.load.return_value = config
        yield config_cls


@pytest.fixture
def reviewer():
    with patch("coderev.cli.CodeReviewer") as reviewer_cls:
        instance = reviewer_cls.return_value
        instance._call_api.return_value = dict(API_RESPONSE)
        instance.review_diff.return_value = ReviewResult(summary="Diff ok", issues=[], score=91)
        yield instance


# --- remote review commands (pr / mr / bpr) ----------------------------------


@dataclass
class Remote:
    """One remote-review command and what its status lines look like."""

    command: str
    ref: str
    client_path: str
    real_client: type
    parse_name: str
    fetch_name: str
    post_name: str
    fetching: str
    title_line: str
    posting: str
    files: list[dict[str, Any]] = field(default_factory=list)

    def args(self, *extra: str) -> list[str]:
        return [self.command, self.ref, *extra]


REMOTES = [
    Remote(
        command="pr",
        ref="https://github.com/octo/repo/pull/7",
        client_path="coderev.github.GitHubClient",
        real_client=GitHubClient,
        parse_name="parse_pr_url",
        fetch_name="get_pull_request",
        post_name="post_review",
        fetching="Fetching PR #7 from octo/repo",
        title_line="PR: Add y",
        posting="Posting review to GitHub",
        files=[{"filename": "a.py", "patch": "@@ -1 +1,2 @@\n x = 1\n+y = 2"}],
    ),
    Remote(
        command="mr",
        ref="https://gitlab.com/group/proj/-/merge_requests/7",
        client_path="coderev.gitlab.GitLabClient",
        real_client=GitLabClient,
        parse_name="parse_mr_url",
        fetch_name="get_merge_request",
        post_name="post_note",
        fetching="Fetching MR !7 from group/proj",
        title_line="MR: Add y",
        posting="Posting review to GitLab",
        files=[{"new_path": "a.py", "diff": "@@ -1 +1,2 @@\n x = 1\n+y = 2"}],
    ),
    Remote(
        command="bpr",
        ref="https://bitbucket.org/team/repo/pull-requests/7",
        client_path="coderev.bitbucket.BitbucketClient",
        real_client=BitbucketClient,
        parse_name="parse_pr_url",
        fetch_name="get_pull_request",
        post_name="post_comment",
        fetching="Fetching PR #7 from team/repo",
        title_line="PR: Add y",
        posting="Posting review to Bitbucket",
        files=[{"new_path": "a.py", "diff": "@@ -1 +1,2 @@\n x = 1\n+y = 2"}],
    ),
]


@pytest.fixture(params=REMOTES, ids=lambda r: r.command)
def remote(request):
    """Patch the command's VCS client; yield (Remote, client instance)."""
    spec: Remote = request.param
    with patch(spec.client_path) as client_cls:
        # Keep real URL parsing so the command walks its normal path.
        setattr(client_cls, spec.parse_name, getattr(spec.real_client, spec.parse_name))
        client = client_cls.return_value.__enter__.return_value
        getattr(client, spec.fetch_name).return_value = SimpleNamespace(
            title="Add y",
            description="Adds y",
            additions=1,
            deletions=0,
            files=spec.files,
            project_id=42,
        )
        yield spec, client


def _status_lines(spec: Remote) -> list[str]:
    return [spec.fetching, spec.title_line, "1 additions, 0 deletions", "Analyzing changes"]


def test_remote_json_stdout_is_pure_json(runner, remote, reviewer):
    spec, _ = remote
    result = runner.invoke(main, spec.args("--format", "json"))

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)  # whole stdout, no slicing past status lines
    assert report["summary"] == "Looks fine"
    assert report["score"] == 88
    for line in _status_lines(spec):
        assert line in result.stderr
        assert line not in result.stdout


def test_remote_json_with_post_comments_keeps_stdout_pure(runner, remote, reviewer):
    spec, client = remote
    # GitHub only posts when there are issues; give it one so every provider posts.
    reviewer._call_api.return_value = dict(
        API_RESPONSE,
        issues=[{"message": "Name y better", "severity": "low", "category": "style", "line": 2}],
    )
    result = runner.invoke(main, spec.args("--format", "json", "--post-comments"))

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert len(report["issues"]) == 1
    getattr(client, spec.post_name).assert_called_once()
    assert spec.posting in result.stderr
    assert "Review posted successfully" in result.stderr
    assert "posted" not in result.stdout


def test_remote_markdown_stdout_starts_with_report(runner, remote, reviewer):
    spec, _ = remote
    result = runner.invoke(main, spec.args("--format", "markdown"))

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Code Review Report")
    assert spec.fetching in result.stderr


def test_remote_no_reviewable_files_message_goes_to_stderr(runner, remote, reviewer):
    spec, client = remote
    getattr(client, spec.fetch_name).return_value.files = [{"filename": "logo.png"}]
    result = runner.invoke(main, spec.args("--format", "json"))

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "No reviewable file changes found" in result.stderr
    reviewer._call_api.assert_not_called()


def test_remote_config_error_goes_to_stderr(runner, remote, mock_config):
    spec, _ = remote
    mock_config.load.return_value.validate.return_value = ["API key not configured"]
    result = runner.invoke(main, spec.args("--format", "json"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Config error: API key not configured" in result.stderr


def test_remote_rate_limit_goes_to_stderr(runner, remote, reviewer):
    spec, _ = remote
    reviewer._call_api.side_effect = RateLimitError("slow down", provider="anthropic")
    result = runner.invoke(main, spec.args("--format", "json"))

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Rate Limit Exceeded" in result.stderr


def test_remote_error_goes_to_stderr(runner, remote):
    spec, client = remote
    getattr(client, spec.fetch_name).side_effect = RuntimeError("upstream exploded")
    result = runner.invoke(main, spec.args("--format", "json"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "upstream exploded" in result.stderr


def test_remote_rich_keeps_status_on_stdout(runner, remote, reviewer):
    spec, _ = remote
    result = runner.invoke(main, spec.args())

    assert result.exit_code == 0, result.output
    for line in _status_lines(spec):
        assert line in result.stdout
    assert "Verdict: APPROVE" in result.stdout
    assert result.stderr == ""


# --- coderev diff -------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["json", "sarif"])
def test_diff_machine_format_stdout_is_pure_json(runner, reviewer, fmt):
    with patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF):
        result = runner.invoke(main, ["diff", "--format", fmt])

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert result.stderr == ""


def test_diff_no_changes_message_goes_to_stderr(runner, reviewer):
    with patch("coderev.cli.get_git_diff", return_value="  \n"):
        result = runner.invoke(main, ["diff", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "No changes to review" in result.stderr


def test_diff_config_error_goes_to_stderr(runner, mock_config):
    mock_config.load.return_value.validate.return_value = ["API key not configured"]
    result = runner.invoke(main, ["diff", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Config error: API key not configured" in result.stderr


def test_diff_rate_limit_goes_to_stderr(runner, reviewer):
    reviewer.review_diff.side_effect = RateLimitError("slow down", provider="anthropic")
    with patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF):
        result = runner.invoke(main, ["diff", "--format", "json"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Rate Limit Exceeded" in result.stderr


def test_diff_error_goes_to_stderr(runner, reviewer):
    with patch("coderev.cli.get_git_diff", side_effect=RuntimeError("not a git repository")):
        result = runner.invoke(main, ["diff", "--format", "markdown"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not a git repository" in result.stderr


def test_diff_rich_keeps_status_on_stdout(runner, reviewer):
    with patch("coderev.cli.get_git_diff", return_value=""):
        result = runner.invoke(main, ["diff"])

    assert result.exit_code == 0, result.output
    assert "No changes to review" in result.stdout
    assert result.stderr == ""
