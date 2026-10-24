"""Custom rules must reach the prompt in parallel (async) reviews too.

`coderev review` uses AsyncCodeReviewer whenever more than one file is
reviewed, so if the async path drops custom rules, a user's `.coderev-rules.yaml`
is silently ignored for every multi-file review while single-file reviews
honor it.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.async_reviewer import AsyncCodeReviewer, review_files_parallel
from coderev.rules import Rule, RuleSet

RULES_YAML = """\
rules:
  - id: no-eval-calls
    name: No eval calls
    description: Never call eval on untrusted input
    severity: high
    category: security
    languages: [python]
  - id: js-only-rule
    name: JS only
    description: Prefer strict equality operators
    languages: [javascript]
"""

PY_RULE = RuleSet(rules=[
    Rule(id="py-rule", name="Py rule", description="PYTHON-ONLY-MARKER", languages=["python"]),
])
OTHER_RULE = RuleSet(rules=[
    Rule(id="other-rule", name="Other rule", description="OVERRIDE-MARKER"),
])


def _mock_provider():
    provider = MagicMock()
    provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
    provider.parse_json_response.return_value = {
        "summary": "ok", "issues": [], "score": 90, "positive": [],
    }
    return provider


def _prompts(provider) -> list[str]:
    # call_async(SYSTEM_PROMPT, prompt)
    return [c.args[1] for c in provider.call_async.call_args_list]


@pytest.fixture
def provider():
    p = _mock_provider()
    with patch("coderev.async_reviewer.get_provider", return_value=p):
        yield p


class TestRulesLoading:
    def test_explicit_rules_used(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        assert reviewer.rules is PY_RULE

    def test_rules_path_loaded(self, provider, tmp_path):
        path = tmp_path / "rules.yaml"
        path.write_text(RULES_YAML, encoding="utf-8")
        reviewer = AsyncCodeReviewer(api_key="k", rules_path=path)
        assert {r.id for r in reviewer.rules.rules} == {"no-eval-calls", "js-only-rule"}

    def test_auto_discovers_rules_file(self, provider, tmp_path, monkeypatch):
        (tmp_path / ".coderev-rules.yaml").write_text(RULES_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        reviewer = AsyncCodeReviewer(api_key="k")
        assert "no-eval-calls" in {r.id for r in reviewer.rules.rules}

    def test_auto_load_disabled_gives_empty_ruleset(self, provider, tmp_path, monkeypatch):
        (tmp_path / ".coderev-rules.yaml").write_text(RULES_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        reviewer = AsyncCodeReviewer(api_key="k", auto_load_rules=False)
        assert reviewer.rules.rules == []

    def test_empty_ruleset_is_not_replaced_by_auto_discovery(self, provider, tmp_path, monkeypatch):
        # An explicitly passed (even empty) RuleSet wins over discovery.
        (tmp_path / ".coderev-rules.yaml").write_text(RULES_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        empty = RuleSet()
        reviewer = AsyncCodeReviewer(api_key="k", rules=empty)
        assert reviewer.rules is empty


class TestRulesInPrompt:
    @pytest.mark.asyncio
    async def test_review_code_injects_language_rules(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        await reviewer.review_code_async("x = 1", language="python")
        assert "PYTHON-ONLY-MARKER" in _prompts(provider)[0]

    @pytest.mark.asyncio
    async def test_review_code_filters_rules_by_language(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        await reviewer.review_code_async("let x = 1", language="javascript")
        assert "PYTHON-ONLY-MARKER" not in _prompts(provider)[0]

    @pytest.mark.asyncio
    async def test_per_call_rules_override_instance_rules(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        await reviewer.review_code_async("x = 1", language="python", rules=OTHER_RULE)
        prompt = _prompts(provider)[0]
        assert "OVERRIDE-MARKER" in prompt
        assert "PYTHON-ONLY-MARKER" not in prompt

    @pytest.mark.asyncio
    async def test_review_diff_injects_rules(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        await reviewer.review_diff_async("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n")
        assert "PYTHON-ONLY-MARKER" in _prompts(provider)[0]

    @pytest.mark.asyncio
    async def test_review_files_async_injects_rules_per_file_language(self, provider, tmp_path):
        py = tmp_path / "a.py"
        js = tmp_path / "b.js"
        py.write_text("x = 1\n", encoding="utf-8")
        js.write_text("let x = 1\n", encoding="utf-8")
        reviewer = AsyncCodeReviewer(api_key="k", rules=PY_RULE)
        await reviewer.review_files_async([py, js])
        prompts = _prompts(provider)
        py_prompt = next(p for p in prompts if str(py) in p)
        js_prompt = next(p for p in prompts if str(js) in p)
        assert "PYTHON-ONLY-MARKER" in py_prompt
        assert "PYTHON-ONLY-MARKER" not in js_prompt

    @pytest.mark.asyncio
    async def test_review_files_parallel_forwards_rules(self, provider, tmp_path):
        py = tmp_path / "a.py"
        py.write_text("x = 1\n", encoding="utf-8")
        await review_files_parallel([py], api_key="k", rules=PY_RULE)
        assert "PYTHON-ONLY-MARKER" in _prompts(provider)[0]

    @pytest.mark.asyncio
    async def test_no_rules_leaves_prompt_without_rules_section(self, provider):
        reviewer = AsyncCodeReviewer(api_key="k", auto_load_rules=False)
        await reviewer.review_code_async("x = 1", language="python")
        assert "PYTHON-ONLY-MARKER" not in _prompts(provider)[0]


def test_cli_parallel_review_applies_discovered_rules(provider, tmp_path, monkeypatch):
    """End to end: a multi-file `coderev review` (parallel by default) must
    send the project's `.coderev-rules.yaml` rules to the model."""
    from coderev.cli import main

    (tmp_path / ".coderev-rules.yaml").write_text(RULES_YAML, encoding="utf-8")
    (tmp_path / "a.py").write_text("eval(input())\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEREV_API_KEY", "k")

    result = CliRunner().invoke(main, ["review", "a.py", "b.py", "--format", "json"])

    assert result.exit_code == 0, result.output
    prompts = _prompts(provider)
    assert len(prompts) == 2
    for prompt in prompts:
        assert "Never call eval on untrusted input" in prompt
        # Language filtering still applies: the JS rule stays out of .py prompts.
        assert "Prefer strict equality operators" not in prompt
