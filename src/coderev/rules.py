"""Custom rule definitions for CodeRev.

This module allows users to define custom review rules in YAML format.
Rules are injected into the review prompt to guide the AI reviewer.

Example .coderev-rules.yaml:
    
    rules:
      - id: no-print-statements
        name: No print statements
        description: Use logging module instead of print()
        severity: medium
        category: style
        pattern: print(
        languages: [python]
        
      - id: require-docstrings
        name: Require docstrings
        description: All public functions must have docstrings
        severity: low
        category: style
        languages: [python]
        
      - id: no-hardcoded-secrets
        name: No hardcoded secrets
        description: API keys, passwords, and secrets must not be hardcoded
        severity: critical
        category: security
        patterns:
          - api_key = 
          - password =
          - secret =
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RULES_FILENAME = ".coderev-rules.yaml"

# Valid values for rule fields
VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
VALID_CATEGORIES = frozenset({"bug", "security", "performance", "style", "architecture"})


class RuleValidationError(Exception):
    """Raised when a rule definition is invalid."""
    pass


@dataclass
class Rule:
    """Represents a single custom review rule.
    
    Attributes:
        id: Unique identifier for the rule.
        name: Human-readable name.
        description: Detailed description of what the rule checks.
        severity: Issue severity (critical, high, medium, low).
        category: Issue category (bug, security, performance, style, architecture).
        pattern: Optional regex or literal pattern to match.
        patterns: Optional list of patterns (alternative to single pattern).
        languages: Optional list of languages this rule applies to.
        enabled: Whether the rule is active.
        example_bad: Optional example of code that violates the rule.
        example_good: Optional example of correct code.
    """
    
    id: str
    name: str
    description: str
    severity: str = "medium"
    category: str = "style"
    pattern: str | None = None
    patterns: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    enabled: bool = True
    example_bad: str | None = None
    example_good: str | None = None
    
    def __post_init__(self) -> None:
        """Validate rule fields after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate rule configuration.
        
        Raises:
            RuleValidationError: If the rule configuration is invalid.
        """
        if not self.id:
            raise RuleValidationError("Rule must have an 'id'")
        
        if not self.name:
            raise RuleValidationError(f"Rule '{self.id}' must have a 'name'")
        
        if not self.description:
            raise RuleValidationError(f"Rule '{self.id}' must have a 'description'")
        
        if self.severity not in VALID_SEVERITIES:
            raise RuleValidationError(
                f"Rule '{self.id}' has invalid severity '{self.severity}'. "
                f"Valid values: {sorted(VALID_SEVERITIES)}"
            )
        
        if self.category not in VALID_CATEGORIES:
            raise RuleValidationError(
                f"Rule '{self.id}' has invalid category '{self.category}'. "
                f"Valid values: {sorted(VALID_CATEGORIES)}"
            )
        
        # Patterns can be either literal strings or regex.
        # We only validate as regex if it looks intentionally regex-like.
        # A pattern is treated as regex if it contains regex syntax like:
        # - Starts with ^ or ends with $
        # - Contains \b, \d, \w, \s (word boundaries, digits, etc.)
        # - Contains quantifiers with proper context like .*, .+, .*?
        # Simple strings with () are treated as literals (e.g., "print(")
        all_patterns = self.get_all_patterns()
        regex_indicators = (r"\\b", r"\\d", r"\\w", r"\\s", r"\\S", r"\\D", r"\\W")
        for pat in all_patterns:
            looks_like_regex = (
                pat.startswith("^") or 
                pat.endswith("$") or
                any(ind in pat for ind in regex_indicators) or
                re.search(r"\.\*|\.\+|\.\?|\[.+\]", pat)  # .*, .+, .?, or [...]
            )
            if looks_like_regex:
                try:
                    re.compile(pat)
                except re.error as e:
                    raise RuleValidationError(
                        f"Rule '{self.id}' has invalid regex pattern '{pat}': {e}"
                    )
    
    def get_all_patterns(self) -> list[str]:
        """Get all patterns (combining single pattern and patterns list)."""
        result = []
        if self.pattern:
            result.append(self.pattern)
        result.extend(self.patterns)
        return result
    
    def applies_to_language(self, language: str | None) -> bool:
        """Check if this rule applies to the given language.
        
        If no languages are specified, the rule applies to all languages.
        """
        if not self.languages:
            return True
        if not language:
            return True  # Apply to unknown languages if not restricted
        return language.lower() in [lang.lower() for lang in self.languages]
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        """Create a Rule from a dictionary.
        
        Args:
            data: Dictionary containing rule configuration.
            
        Returns:
            Rule instance.
            
        Raises:
            RuleValidationError: If required fields are missing or invalid.
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            severity=data.get("severity", "medium"),
            category=data.get("category", "style"),
            pattern=data.get("pattern"),
            patterns=data.get("patterns", []),
            languages=data.get("languages", []),
            enabled=data.get("enabled", True),
            example_bad=data.get("example_bad"),
            example_good=data.get("example_good"),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert rule to dictionary."""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "enabled": self.enabled,
        }
        if self.pattern:
            result["pattern"] = self.pattern
        if self.patterns:
            result["patterns"] = self.patterns
        if self.languages:
            result["languages"] = self.languages
        if self.example_bad:
            result["example_bad"] = self.example_bad
        if self.example_good:
            result["example_good"] = self.example_good
        return result
    
    def to_prompt_text(self) -> str:
        """Convert rule to text suitable for injection into the review prompt."""
        lines = [f"- **{self.name}** [{self.severity.upper()}] [{self.category}]"]
        lines.append(f"  {self.description}")
        
        patterns = self.get_all_patterns()
        if patterns:
            if len(patterns) == 1:
                lines.append(f"  Look for: `{patterns[0]}`")
            else:
                lines.append(f"  Look for patterns: {', '.join(f'`{p}`' for p in patterns)}")
        
        if self.example_bad:
            lines.append(f"  Bad: `{self.example_bad}`")
        if self.example_good:
            lines.append(f"  Good: `{self.example_good}`")
        
        return "\n".join(lines)


@dataclass
class RuleSet:
    """Collection of custom review rules.
    
    Attributes:
        rules: List of Rule objects.
        name: Optional name for the rule set.
        description: Optional description.
        extends: Optional list of rule set files to extend.
    """
    
    rules: list[Rule] = field(default_factory=list)
    name: str | None = None
    description: str | None = None
    extends: list[str] = field(default_factory=list)
    
    def get_enabled_rules(self) -> list[Rule]:
        """Get only enabled rules."""
        return [r for r in self.rules if r.enabled]
    
    def get_rules_for_language(self, language: str | None) -> list[Rule]:
        """Get enabled rules that apply to the given language."""
        return [r for r in self.get_enabled_rules() if r.applies_to_language(language)]
    
    def get_rule_by_id(self, rule_id: str) -> Rule | None:
        """Get a rule by its ID."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None
    
    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule by ID. Returns True if found."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            rule.enabled = True
            return True
        return False
    
    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule by ID. Returns True if found."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            rule.enabled = False
            return True
        return False
    
    def to_prompt_text(self, language: str | None = None) -> str:
        """Generate prompt text for all applicable rules.
        
        Args:
            language: Optional language to filter rules.
            
        Returns:
            Formatted text suitable for injection into the review prompt.
        """
        applicable_rules = self.get_rules_for_language(language)
        
        if not applicable_rules:
            return ""
        
        lines = ["\n## Custom Rules\n"]
        lines.append("Apply these additional rules when reviewing:\n")
        
        for rule in applicable_rules:
            lines.append(rule.to_prompt_text())
            lines.append("")  # Blank line between rules
        
        return "\n".join(lines)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleSet:
        """Create a RuleSet from a dictionary.
        
        Args:
            data: Dictionary containing rules configuration.
            
        Returns:
            RuleSet instance.
        """
        rules_data = data.get("rules", [])
        rules = [Rule.from_dict(r) for r in rules_data]
        
        return cls(
            rules=rules,
            name=data.get("name"),
            description=data.get("description"),
            extends=data.get("extends", []),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert rule set to dictionary."""
        result: dict[str, Any] = {
            "rules": [r.to_dict() for r in self.rules]
        }
        if self.name:
            result["name"] = self.name
        if self.description:
            result["description"] = self.description
        if self.extends:
            result["extends"] = self.extends
        return result
    
    def merge_with(self, other: RuleSet) -> RuleSet:
        """Merge another rule set into this one.
        
        Rules from 'other' override rules with the same ID.
        
        Args:
            other: Rule set to merge.
            
        Returns:
            New merged RuleSet.
        """
        rules_by_id = {r.id: r for r in self.rules}
        
        for rule in other.rules:
            rules_by_id[rule.id] = rule
        
        return RuleSet(
            rules=list(rules_by_id.values()),
            name=other.name or self.name,
            description=other.description or self.description,
        )


def load_rules_from_file(path: Path | str) -> RuleSet:
    """Load rules from a YAML file.
    
    Args:
        path: Path to the rules file.
        
    Returns:
        RuleSet containing the loaded rules.
        
    Raises:
        FileNotFoundError: If the file doesn't exist.
        yaml.YAMLError: If the file is not valid YAML.
        RuleValidationError: If any rule is invalid.
    """
    path = Path(path)
    
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")
    
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    if data is None:
        return RuleSet()
    
    base_ruleset = RuleSet.from_dict(data)
    
    # Handle extends (inheritance)
    if base_ruleset.extends:
        merged = RuleSet()
        for extend_path in base_ruleset.extends:
            extend_full_path = path.parent / extend_path
            if extend_full_path.exists():
                extended = load_rules_from_file(extend_full_path)
                merged = merged.merge_with(extended)
        base_ruleset = merged.merge_with(base_ruleset)
    
    return base_ruleset


def find_rules_file(start_dir: Path | None = None) -> Path | None:
    """Find a rules file by searching up the directory tree.
    
    Args:
        start_dir: Starting directory (defaults to current directory).
        
    Returns:
        Path to rules file if found, None otherwise.
    """
    if start_dir is None:
        start_dir = Path.cwd()
    
    current = start_dir.resolve()
    
    # Search up the directory tree
    while current != current.parent:
        rules_path = current / DEFAULT_RULES_FILENAME
        if rules_path.exists():
            return rules_path
        current = current.parent
    
    # Also check home directory
    home_rules = Path.home() / DEFAULT_RULES_FILENAME
    if home_rules.exists():
        return home_rules
    
    return None


def load_rules(
    rules_path: Path | str | None = None,
    start_dir: Path | None = None,
) -> RuleSet:
    """Load rules from a file or find the default rules file.
    
    Args:
        rules_path: Explicit path to rules file (optional).
        start_dir: Starting directory for auto-discovery (optional).
        
    Returns:
        RuleSet (empty if no rules file found).
    """
    if rules_path:
        return load_rules_from_file(rules_path)
    
    found_path = find_rules_file(start_dir)
    if found_path:
        return load_rules_from_file(found_path)
    
    return RuleSet()


# Built-in rule templates that users can reference
BUILTIN_RULES: dict[str, Rule] = {
    "no-print-debug": Rule(
        id="no-print-debug",
        name="No Print Debugging",
        description="Avoid print() statements for debugging; use a proper logging framework",
        severity="low",
        category="style",
        pattern=r"\bprint\s*\(",
        languages=["python"],
    ),
    "no-hardcoded-secrets": Rule(
        id="no-hardcoded-secrets",
        name="No Hardcoded Secrets",
        description="API keys, passwords, tokens, and secrets must not be hardcoded in source code",
        severity="critical",
        category="security",
        patterns=[
            r"(?i)(api_key|apikey|api-key)\s*=\s*['\"]",
            r"(?i)(password|passwd|pwd)\s*=\s*['\"]",
            r"(?i)(secret|token)\s*=\s*['\"]",
            r"(?i)(auth_token|access_token|bearer)\s*=\s*['\"]",
        ],
    ),
    "no-todo-comments": Rule(
        id="no-todo-comments",
        name="No TODO Comments",
        description="TODO comments should be tracked in an issue tracker, not left in code",
        severity="low",
        category="style",
        patterns=[r"#\s*TODO", r"//\s*TODO", r"/\*\s*TODO"],
    ),
    "require-type-hints": Rule(
        id="require-type-hints",
        name="Require Type Hints",
        description="Function parameters and return types should have type hints",
        severity="low",
        category="style",
        languages=["python"],
    ),
    "no-eval": Rule(
        id="no-eval",
        name="No eval()",
        description="eval() is dangerous and can lead to code injection vulnerabilities",
        severity="critical",
        category="security",
        patterns=[r"\beval\s*\(", r"\bexec\s*\("],
        languages=["python"],
    ),
    "no-sql-injection": Rule(
        id="no-sql-injection",
        name="No SQL Injection",
        description="Use parameterized queries instead of string formatting for SQL",
        severity="critical",
        category="security",
        patterns=[
            r'f".*SELECT.*{',
            r'f".*INSERT.*{',
            r'f".*UPDATE.*{',
            r'f".*DELETE.*{',
            r'".*SELECT.*"\s*%',
            r'".*SELECT.*"\.format\(',
        ],
    ),
}


def get_builtin_rule(rule_id: str) -> Rule | None:
    """Get a built-in rule by ID."""
    return BUILTIN_RULES.get(rule_id)


def list_builtin_rules() -> list[str]:
    """List all available built-in rule IDs."""
    return list(BUILTIN_RULES.keys())
