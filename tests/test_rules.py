"""Tests for custom rule definitions."""

import tempfile
from pathlib import Path

import pytest
import yaml

from coderev.rules import (
    Rule,
    RuleSet,
    RuleValidationError,
    load_rules,
    load_rules_from_file,
    find_rules_file,
    get_builtin_rule,
    list_builtin_rules,
    BUILTIN_RULES,
    DEFAULT_RULES_FILENAME,
)


class TestRule:
    """Tests for the Rule class."""
    
    def test_rule_creation_minimal(self):
        """Test creating a rule with minimal required fields."""
        rule = Rule(
            id="test-rule",
            name="Test Rule",
            description="A test rule",
        )
        assert rule.id == "test-rule"
        assert rule.name == "Test Rule"
        assert rule.description == "A test rule"
        assert rule.severity == "medium"
        assert rule.category == "style"
        assert rule.enabled is True
    
    def test_rule_creation_full(self):
        """Test creating a rule with all fields."""
        rule = Rule(
            id="full-rule",
            name="Full Rule",
            description="A rule with all fields",
            severity="critical",
            category="security",
            pattern=r"\beval\(",
            patterns=[r"\bexec\("],
            languages=["python"],
            enabled=True,
            example_bad="eval(user_input)",
            example_good="ast.literal_eval(user_input)",
        )
        assert rule.id == "full-rule"
        assert rule.severity == "critical"
        assert rule.category == "security"
        assert rule.pattern == r"\beval\("
        assert rule.patterns == [r"\bexec\("]
        assert rule.languages == ["python"]
        assert rule.example_bad == "eval(user_input)"
        assert rule.example_good == "ast.literal_eval(user_input)"
    
    def test_rule_validation_missing_id(self):
        """Test that validation fails when ID is missing."""
        with pytest.raises(RuleValidationError, match="must have an 'id'"):
            Rule(id="", name="Test", description="Test")
    
    def test_rule_validation_missing_name(self):
        """Test that validation fails when name is missing."""
        with pytest.raises(RuleValidationError, match="must have a 'name'"):
            Rule(id="test", name="", description="Test")
    
    def test_rule_validation_missing_description(self):
        """Test that validation fails when description is missing."""
        with pytest.raises(RuleValidationError, match="must have a 'description'"):
            Rule(id="test", name="Test", description="")
    
    def test_rule_validation_invalid_severity(self):
        """Test that validation fails for invalid severity."""
        with pytest.raises(RuleValidationError, match="invalid severity"):
            Rule(id="test", name="Test", description="Test", severity="invalid")
    
    def test_rule_validation_invalid_category(self):
        """Test that validation fails for invalid category."""
        with pytest.raises(RuleValidationError, match="invalid category"):
            Rule(id="test", name="Test", description="Test", category="invalid")
    
    def test_rule_validation_invalid_regex(self):
        """Test that validation fails for invalid regex pattern."""
        # Pattern starting with ^ triggers regex validation, and [unterminated is invalid
        with pytest.raises(RuleValidationError, match="invalid regex"):
            Rule(id="test", name="Test", description="Test", pattern="^[unterminated")
    
    def test_get_all_patterns(self):
        """Test getting all patterns from a rule."""
        rule = Rule(
            id="test",
            name="Test",
            description="Test",
            pattern="pattern1",
            patterns=["pattern2", "pattern3"],
        )
        assert rule.get_all_patterns() == ["pattern1", "pattern2", "pattern3"]
    
    def test_get_all_patterns_empty(self):
        """Test getting patterns when none are set."""
        rule = Rule(id="test", name="Test", description="Test")
        assert rule.get_all_patterns() == []
    
    def test_applies_to_language_no_restriction(self):
        """Test that rule with no language restriction applies to all."""
        rule = Rule(id="test", name="Test", description="Test")
        assert rule.applies_to_language("python") is True
        assert rule.applies_to_language("javascript") is True
        assert rule.applies_to_language(None) is True
    
    def test_applies_to_language_with_restriction(self):
        """Test that rule with language restriction only applies to those."""
        rule = Rule(
            id="test",
            name="Test",
            description="Test",
            languages=["python", "ruby"],
        )
        assert rule.applies_to_language("python") is True
        assert rule.applies_to_language("Python") is True  # Case insensitive
        assert rule.applies_to_language("ruby") is True
        assert rule.applies_to_language("javascript") is False
    
    def test_from_dict(self):
        """Test creating a rule from a dictionary."""
        data = {
            "id": "dict-rule",
            "name": "Dict Rule",
            "description": "Rule from dict",
            "severity": "high",
            "category": "bug",
            "pattern": "test_pattern",
            "languages": ["python"],
        }
        rule = Rule.from_dict(data)
        assert rule.id == "dict-rule"
        assert rule.name == "Dict Rule"
        assert rule.severity == "high"
        assert rule.category == "bug"
        assert rule.pattern == "test_pattern"
        assert rule.languages == ["python"]
    
    def test_to_dict(self):
        """Test converting a rule to a dictionary."""
        rule = Rule(
            id="test",
            name="Test",
            description="Test desc",
            severity="high",
            category="bug",
            pattern="pattern",
            languages=["python"],
        )
        data = rule.to_dict()
        assert data["id"] == "test"
        assert data["name"] == "Test"
        assert data["description"] == "Test desc"
        assert data["severity"] == "high"
        assert data["category"] == "bug"
        assert data["pattern"] == "pattern"
        assert data["languages"] == ["python"]
    
    def test_to_prompt_text(self):
        """Test generating prompt text from a rule."""
        rule = Rule(
            id="test",
            name="No Print",
            description="Avoid print statements",
            severity="medium",
            category="style",
            pattern="print(",  # Literal pattern with parenthesis
        )
        text = rule.to_prompt_text()
        assert "No Print" in text
        assert "MEDIUM" in text
        assert "style" in text
        assert "Avoid print statements" in text
        assert "print(" in text


class TestRuleSet:
    """Tests for the RuleSet class."""
    
    def test_empty_ruleset(self):
        """Test creating an empty rule set."""
        ruleset = RuleSet()
        assert len(ruleset.rules) == 0
        assert ruleset.get_enabled_rules() == []
    
    def test_ruleset_with_rules(self):
        """Test creating a rule set with rules."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1"),
            Rule(id="rule2", name="Rule 2", description="Desc 2"),
        ]
        ruleset = RuleSet(rules=rules)
        assert len(ruleset.rules) == 2
    
    def test_get_enabled_rules(self):
        """Test filtering to get only enabled rules."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1", enabled=True),
            Rule(id="rule2", name="Rule 2", description="Desc 2", enabled=False),
            Rule(id="rule3", name="Rule 3", description="Desc 3", enabled=True),
        ]
        ruleset = RuleSet(rules=rules)
        enabled = ruleset.get_enabled_rules()
        assert len(enabled) == 2
        assert all(r.enabled for r in enabled)
    
    def test_get_rules_for_language(self):
        """Test filtering rules by language."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1", languages=["python"]),
            Rule(id="rule2", name="Rule 2", description="Desc 2", languages=["javascript"]),
            Rule(id="rule3", name="Rule 3", description="Desc 3"),  # All languages
        ]
        ruleset = RuleSet(rules=rules)
        
        python_rules = ruleset.get_rules_for_language("python")
        assert len(python_rules) == 2
        assert any(r.id == "rule1" for r in python_rules)
        assert any(r.id == "rule3" for r in python_rules)
    
    def test_get_rule_by_id(self):
        """Test getting a rule by its ID."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1"),
            Rule(id="rule2", name="Rule 2", description="Desc 2"),
        ]
        ruleset = RuleSet(rules=rules)
        
        rule = ruleset.get_rule_by_id("rule1")
        assert rule is not None
        assert rule.name == "Rule 1"
        
        assert ruleset.get_rule_by_id("nonexistent") is None
    
    def test_enable_disable_rule(self):
        """Test enabling and disabling rules."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1", enabled=False),
        ]
        ruleset = RuleSet(rules=rules)
        
        assert ruleset.enable_rule("rule1") is True
        assert ruleset.rules[0].enabled is True
        
        assert ruleset.disable_rule("rule1") is True
        assert ruleset.rules[0].enabled is False
        
        assert ruleset.enable_rule("nonexistent") is False
    
    def test_from_dict(self):
        """Test creating a rule set from a dictionary."""
        data = {
            "name": "My Rules",
            "description": "My custom rules",
            "rules": [
                {"id": "rule1", "name": "Rule 1", "description": "Desc 1"},
                {"id": "rule2", "name": "Rule 2", "description": "Desc 2"},
            ],
        }
        ruleset = RuleSet.from_dict(data)
        assert ruleset.name == "My Rules"
        assert ruleset.description == "My custom rules"
        assert len(ruleset.rules) == 2
    
    def test_to_dict(self):
        """Test converting a rule set to a dictionary."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1"),
        ]
        ruleset = RuleSet(rules=rules, name="Test Set")
        data = ruleset.to_dict()
        assert data["name"] == "Test Set"
        assert len(data["rules"]) == 1
    
    def test_merge_with(self):
        """Test merging two rule sets."""
        ruleset1 = RuleSet(rules=[
            Rule(id="rule1", name="Rule 1 Original", description="Original"),
            Rule(id="rule2", name="Rule 2", description="Desc 2"),
        ])
        ruleset2 = RuleSet(rules=[
            Rule(id="rule1", name="Rule 1 Override", description="Override"),
            Rule(id="rule3", name="Rule 3", description="Desc 3"),
        ])
        
        merged = ruleset1.merge_with(ruleset2)
        assert len(merged.rules) == 3
        
        # rule1 should be overridden
        rule1 = merged.get_rule_by_id("rule1")
        assert rule1 is not None
        assert rule1.name == "Rule 1 Override"
    
    def test_to_prompt_text(self):
        """Test generating prompt text from a rule set."""
        rules = [
            Rule(id="rule1", name="Rule 1", description="Desc 1", severity="high"),
            Rule(id="rule2", name="Rule 2", description="Desc 2", severity="low"),
        ]
        ruleset = RuleSet(rules=rules)
        text = ruleset.to_prompt_text()
        assert "Custom Rules" in text
        assert "Rule 1" in text
        assert "Rule 2" in text
    
    def test_to_prompt_text_empty(self):
        """Test that empty rule set returns empty prompt text."""
        ruleset = RuleSet()
        assert ruleset.to_prompt_text() == ""
    
    def test_to_prompt_text_language_filtered(self):
        """Test prompt text is filtered by language."""
        rules = [
            Rule(id="py-rule", name="Python Rule", description="Desc", languages=["python"]),
            Rule(id="js-rule", name="JS Rule", description="Desc", languages=["javascript"]),
        ]
        ruleset = RuleSet(rules=rules)
        
        py_text = ruleset.to_prompt_text(language="python")
        assert "Python Rule" in py_text
        assert "JS Rule" not in py_text


class TestLoadRules:
    """Tests for rule loading functions."""
    
    def test_load_rules_from_file(self, tmp_path):
        """Test loading rules from a YAML file."""
        rules_content = """
rules:
  - id: test-rule
    name: Test Rule
    description: A test rule
    severity: high
    category: security
"""
        rules_file = tmp_path / ".coderev-rules.yaml"
        rules_file.write_text(rules_content)
        
        ruleset = load_rules_from_file(rules_file)
        assert len(ruleset.rules) == 1
        assert ruleset.rules[0].id == "test-rule"
        assert ruleset.rules[0].severity == "high"
    
    def test_load_rules_from_file_not_found(self, tmp_path):
        """Test that loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_rules_from_file(tmp_path / "nonexistent.yaml")
    
    def test_load_rules_from_empty_file(self, tmp_path):
        """Test loading from an empty YAML file."""
        rules_file = tmp_path / ".coderev-rules.yaml"
        rules_file.write_text("")
        
        ruleset = load_rules_from_file(rules_file)
        assert len(ruleset.rules) == 0
    
    def test_load_rules_with_extends(self, tmp_path):
        """Test loading rules with inheritance."""
        base_content = """
rules:
  - id: base-rule
    name: Base Rule
    description: A base rule
"""
        child_content = """
extends:
  - base-rules.yaml
rules:
  - id: child-rule
    name: Child Rule
    description: A child rule
"""
        base_file = tmp_path / "base-rules.yaml"
        base_file.write_text(base_content)
        
        child_file = tmp_path / ".coderev-rules.yaml"
        child_file.write_text(child_content)
        
        ruleset = load_rules_from_file(child_file)
        assert len(ruleset.rules) == 2
        assert any(r.id == "base-rule" for r in ruleset.rules)
        assert any(r.id == "child-rule" for r in ruleset.rules)
    
    def test_find_rules_file(self, tmp_path):
        """Test finding rules file in directory tree."""
        # Create nested directory structure
        subdir = tmp_path / "project" / "src"
        subdir.mkdir(parents=True)
        
        # Create rules file in project root
        rules_file = tmp_path / "project" / DEFAULT_RULES_FILENAME
        rules_file.write_text("rules: []")
        
        # Should find it from subdirectory
        found = find_rules_file(subdir)
        assert found is not None
        assert found == rules_file
    
    def test_find_rules_file_not_found(self, tmp_path):
        """Test that None is returned when no rules file exists."""
        found = find_rules_file(tmp_path)
        assert found is None
    
    def test_load_rules_auto_discover(self, tmp_path, monkeypatch):
        """Test auto-discovery of rules file."""
        rules_content = """
rules:
  - id: discovered-rule
    name: Discovered Rule
    description: Auto-discovered
"""
        rules_file = tmp_path / DEFAULT_RULES_FILENAME
        rules_file.write_text(rules_content)
        
        monkeypatch.chdir(tmp_path)
        ruleset = load_rules()
        assert len(ruleset.rules) == 1
        assert ruleset.rules[0].id == "discovered-rule"
    
    def test_load_rules_explicit_path(self, tmp_path):
        """Test loading with explicit path."""
        rules_content = """
rules:
  - id: explicit-rule
    name: Explicit Rule
    description: Loaded explicitly
"""
        custom_file = tmp_path / "custom-rules.yaml"
        custom_file.write_text(rules_content)
        
        ruleset = load_rules(rules_path=custom_file)
        assert len(ruleset.rules) == 1
        assert ruleset.rules[0].id == "explicit-rule"


class TestBuiltinRules:
    """Tests for built-in rules."""
    
    def test_builtin_rules_exist(self):
        """Test that built-in rules are available."""
        assert len(BUILTIN_RULES) > 0
    
    def test_list_builtin_rules(self):
        """Test listing built-in rule IDs."""
        rule_ids = list_builtin_rules()
        assert len(rule_ids) > 0
        assert "no-hardcoded-secrets" in rule_ids
    
    def test_get_builtin_rule(self):
        """Test getting a built-in rule by ID."""
        rule = get_builtin_rule("no-hardcoded-secrets")
        assert rule is not None
        assert rule.severity == "critical"
        assert rule.category == "security"
    
    def test_get_builtin_rule_not_found(self):
        """Test that None is returned for unknown built-in rule."""
        assert get_builtin_rule("nonexistent") is None
    
    def test_builtin_rules_are_valid(self):
        """Test that all built-in rules pass validation."""
        for rule_id, rule in BUILTIN_RULES.items():
            # This should not raise
            rule.validate()
            assert rule.id == rule_id


class TestRuleIntegration:
    """Integration tests for rules with the reviewer."""
    
    def test_rules_to_prompt_format(self):
        """Test that rules format correctly for prompt injection."""
        rules = [
            Rule(
                id="no-print",
                name="No Print Statements",
                description="Use logging instead of print()",
                severity="medium",
                category="style",
                pattern=r"print\(",
                example_bad="print('debug')",
                example_good="logger.debug('debug')",
            ),
        ]
        ruleset = RuleSet(rules=rules)
        text = ruleset.to_prompt_text()
        
        # Check formatting
        assert "## Custom Rules" in text
        assert "No Print Statements" in text
        assert "[MEDIUM]" in text
        assert "[style]" in text
        assert "Use logging instead" in text
        assert "print\\(" in text
        assert "print('debug')" in text
        assert "logger.debug" in text


class TestRuleValidation:
    """Tests for rule validation edge cases."""
    
    def test_valid_severities(self):
        """Test all valid severity levels."""
        for severity in ["critical", "high", "medium", "low"]:
            rule = Rule(id="test", name="Test", description="Test", severity=severity)
            assert rule.severity == severity
    
    def test_valid_categories(self):
        """Test all valid category types."""
        for category in ["bug", "security", "performance", "style", "architecture"]:
            rule = Rule(id="test", name="Test", description="Test", category=category)
            assert rule.category == category
    
    def test_complex_regex_patterns(self):
        """Test complex regex patterns are validated."""
        # Valid complex patterns
        valid_patterns = [
            r"(?i)api_key\s*=",
            r"^\s*import\s+os\b",
            r"\beval\s*\([^)]*\)",
            r"password\s*=\s*['\"][^'\"]+['\"]",
        ]
        for pattern in valid_patterns:
            rule = Rule(id="test", name="Test", description="Test", pattern=pattern)
            assert rule.pattern == pattern
    
    def test_literal_pattern_not_regex(self):
        """Test that literal patterns (not regex-like) are accepted."""
        # Literal patterns without regex special chars should be accepted
        rule = Rule(id="test", name="Test", description="Test", pattern="print(")
        assert rule.pattern == "print("
