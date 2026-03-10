"""Basic code review examples using CodeRev.

Demonstrates:
- Reviewing a code string
- Reviewing a file from disk
- Using different focus areas
- Switching between providers (Claude/GPT)
- Handling review results
"""

from pathlib import Path

from coderev import CodeReviewer, ReviewResult, Issue


def review_code_string():
    """Review a Python code snippet for security issues."""
    reviewer = CodeReviewer()

    vulnerable_code = '''
import sqlite3

def get_user(user_id):
    """Fetch a user by ID."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchone()

def login(username, password):
    """Authenticate a user."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM users WHERE name = '{username}' AND pass = '{password}'"
    )
    user = cursor.fetchone()
    if user:
        print(f"Welcome {username}! Your token is: sk-abc123hardcoded")
    return user
'''

    result = reviewer.review_code(
        vulnerable_code,
        language="python",
        focus=["security", "bugs"],
    )

    print(f"Score: {result.score}/100")
    print(f"Summary: {result.summary}")
    print(f"Issues found: {len(result.issues)}")
    print()

    for issue in result.issues:
        print(f"  [{issue.severity.value.upper()}] Line {issue.line}: {issue.message}")
        if issue.suggestion:
            print(f"    Fix: {issue.suggestion}")
        print()


def review_file():
    """Review a file from disk with multiple focus areas."""
    reviewer = CodeReviewer(model="claude-3-sonnet")

    target = Path("src/coderev/cli.py")
    if not target.exists():
        print(f"File {target} not found, skipping file review example")
        return

    result = reviewer.review_file(
        target,
        focus=["performance", "architecture", "bugs"],
    )

    print(f"File: {target}")
    print(f"Score: {result.score}/100")
    print(f"Critical: {result.critical_count} | High: {result.high_count} "
          f"| Medium: {result.medium_count} | Low: {result.low_count}")


def review_with_openai():
    """Use OpenAI GPT-4o instead of Claude."""
    # Provider is auto-detected from the model name
    reviewer = CodeReviewer(model="gpt-4o")

    result = reviewer.review_code(
        "def add(a, b): return a + b",
        language="python",
        focus=["style"],
    )
    print(f"GPT-4o score: {result.score}/100")


def filter_issues_by_severity(result: ReviewResult) -> dict[str, list[Issue]]:
    """Group issues by severity for reporting."""
    grouped: dict[str, list[Issue]] = {}
    for issue in result.issues:
        key = issue.severity.value
        grouped.setdefault(key, []).append(issue)
    return grouped


def json_output(result: ReviewResult):
    """Convert review results to JSON for downstream processing."""
    import json

    data = {
        "score": result.score,
        "summary": result.summary,
        "issues": [
            {
                "line": issue.line,
                "severity": issue.severity.value,
                "category": issue.category.value,
                "message": issue.message,
                "suggestion": issue.suggestion,
            }
            for issue in result.issues
        ],
    }
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    print("=== Code String Review ===")
    review_code_string()

    print("\n=== File Review ===")
    review_file()
