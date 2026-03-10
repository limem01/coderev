"""Custom rule examples for CodeRev.

Demonstrates:
- Loading rules from YAML files
- Creating rules programmatically
- Using builtin rules
- Combining rulesets
"""

from pathlib import Path

from coderev import (
    CodeReviewer,
    Rule,
    RuleSet,
    load_rules_from_file,
    list_builtin_rules,
    get_builtin_rule,
    BUILTIN_RULES,
)


def create_rules_programmatically():
    """Define custom rules in Python code."""
    rules = RuleSet(rules=[
        Rule(
            id="no-print",
            name="No print statements",
            description="Use the logging module instead of print() for production code",
            severity="medium",
            category="style",
            pattern="print(",
            languages=["python"],
        ),
        Rule(
            id="no-todo",
            name="No TODO comments",
            description="TODO comments should be tracked as issues, not left in code",
            severity="low",
            category="style",
            patterns=["TODO:", "FIXME:", "HACK:", "XXX:"],
        ),
        Rule(
            id="no-eval",
            name="No eval/exec",
            description="eval() and exec() are security risks; use safer alternatives",
            severity="critical",
            category="security",
            patterns=["eval(", "exec("],
            languages=["python"],
        ),
    ])

    print(f"Created {len(rules.rules)} custom rules:")
    for rule in rules.rules:
        print(f"  [{rule.severity}] {rule.id}: {rule.name}")

    return rules


def load_rules_from_yaml():
    """Load rules from a YAML file."""
    rules_file = Path(__file__).parent / "sample_rules.yaml"
    if not rules_file.exists():
        print(f"Rules file not found: {rules_file}")
        return None

    ruleset = load_rules_from_file(rules_file)
    print(f"\nLoaded {len(ruleset.rules)} rules from {rules_file.name}:")
    for rule in ruleset.rules:
        langs = ", ".join(rule.languages) if rule.languages else "all"
        print(f"  {rule.id} ({langs}): {rule.description}")

    return ruleset


def explore_builtin_rules():
    """List and inspect the builtin rules that ship with CodeRev."""
    builtin_names = list_builtin_rules()
    print(f"\nBuiltin rules ({len(builtin_names)}):")
    for name in builtin_names:
        rule = get_builtin_rule(name)
        print(f"  {rule.id}: {rule.name} [{rule.severity}]")


def review_with_custom_rules():
    """Run a review that includes custom rules."""
    rules = create_rules_programmatically()

    reviewer = CodeReviewer()

    code = '''
import os

def process_input(user_data):
    # TODO: add input validation
    result = eval(user_data)
    print(f"Result: {result}")
    return result
'''

    result = reviewer.review_code(
        code,
        language="python",
        focus=["security", "style"],
        rules=rules,
    )

    print(f"\nReview with custom rules - Score: {result.score}/100")
    for issue in result.issues:
        print(f"  [{issue.severity.value}] {issue.message}")


if __name__ == "__main__":
    print("=== Programmatic Rules ===")
    create_rules_programmatically()

    print("\n=== YAML Rules ===")
    load_rules_from_yaml()

    print("\n=== Builtin Rules ===")
    explore_builtin_rules()
