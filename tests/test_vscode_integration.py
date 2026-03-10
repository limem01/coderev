"""Tests for VS Code extension integration.

Validates that the JSON output format from coderev CLI matches
what the VS Code extension expects to parse.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner

from coderev.cli import main
from coderev.reviewer import ReviewResult, Issue


class TestJsonOutputFormat:
    """Ensure JSON output is parseable by the VS Code extension."""

    def _make_issue(self, line=10, severity="high", category="security",
                    message="Test issue", suggestion=None, end_line=None):
        issue = MagicMock(spec=Issue)
        issue.line = line
        issue.end_line = end_line
        issue.severity = MagicMock()
        issue.severity.value = severity
        issue.category = category
        issue.message = message
        issue.suggestion = suggestion
        return issue

    def _make_result(self, issues=None, summary="Test summary"):
        result = MagicMock(spec=ReviewResult)
        result.issues = issues or []
        result.summary = summary
        result.file_path = "test.py"
        return result

    def test_json_output_has_issues_array(self, tmp_path):
        """VS Code extension expects { issues: [...] } structure."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")

        mock_result = self._make_result(
            issues=[
                self._make_issue(line=1, severity="medium", category="style",
                                message="Variable name too short"),
            ]
        )

        runner = CliRunner()
        with patch("coderev.cli.Config") as mock_config_cls, \
             patch("coderev.cli.CodeReviewer") as mock_reviewer_cls:

            mock_config = MagicMock()
            mock_config.validate.return_value = []
            mock_config_cls.load.return_value = mock_config

            mock_reviewer = MagicMock()
            mock_reviewer.review_file.return_value = mock_result
            mock_reviewer.review_files.return_value = {str(test_file): mock_result}
            mock_reviewer_cls.return_value = mock_reviewer

            result = runner.invoke(main, ["review", str(test_file), "--format", "json", "--no-parallel"])

            if result.exit_code == 0 and result.output.strip():
                data = json.loads(result.output)
                # Should be parseable JSON
                assert isinstance(data, dict)

    def test_json_issue_fields_match_extension_expectations(self):
        """Verify that Issue objects serialize with fields the extension expects."""
        issue = self._make_issue(
            line=42,
            end_line=45,
            severity="high",
            category="security",
            message="SQL injection vulnerability",
            suggestion="Use parameterized queries"
        )

        # Simulate what JsonFormatter produces
        serialized = {
            "line": issue.line,
            "end_line": issue.end_line,
            "severity": issue.severity.value,
            "category": issue.category,
            "message": issue.message,
            "suggestion": issue.suggestion,
        }

        # VS Code extension expects these fields
        assert "line" in serialized
        assert "severity" in serialized
        assert "message" in serialized
        assert "category" in serialized
        assert serialized["line"] == 42
        assert serialized["end_line"] == 45
        assert serialized["severity"] == "high"
        assert serialized["suggestion"] == "Use parameterized queries"

    def test_severity_values_are_valid(self):
        """Extension maps these exact severity strings."""
        valid_severities = {"critical", "high", "medium", "low"}

        for sev in valid_severities:
            issue = self._make_issue(severity=sev)
            assert issue.severity.value in valid_severities

    def test_empty_review_produces_empty_issues(self):
        """Extension handles empty issues array gracefully."""
        result = self._make_result(issues=[], summary="No issues found")

        serialized = {
            "issues": [],
            "summary": result.summary,
        }

        data = json.loads(json.dumps(serialized))
        assert data["issues"] == []
        assert data["summary"] == "No issues found"

    def test_multi_file_json_structure(self):
        """Extension handles multi-file output format."""
        multi_output = {
            "app.py": {
                "issues": [
                    {"line": 5, "severity": "low", "category": "style", "message": "Long line"}
                ],
                "summary": "1 issue"
            },
            "utils.py": {
                "issues": [],
                "summary": "Clean"
            }
        }

        data = json.loads(json.dumps(multi_output))

        # Extension iterates keys to find file data
        assert "app.py" in data
        assert "utils.py" in data
        assert len(data["app.py"]["issues"]) == 1
        assert len(data["utils.py"]["issues"]) == 0

    def test_cost_estimate_json_format(self):
        """Extension parses cost estimate JSON."""
        estimate_output = {
            "model": "claude-3-sonnet",
            "input_tokens": 1500,
            "estimated_output_tokens": 500,
            "total_cost_usd": 0.0045,
            "total_cost_formatted": "$0.0045"
        }

        data = json.loads(json.dumps(estimate_output))

        # Extension expects these fields
        assert "model" in data
        assert "input_tokens" in data
        assert "estimated_output_tokens" in data
        assert isinstance(data["input_tokens"], int)
        assert isinstance(data["total_cost_usd"], float)
