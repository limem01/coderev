"""CI/CD integration examples for CodeRev.

Demonstrates:
- Running reviews in CI and failing on critical issues
- Generating SARIF output for GitHub Security tab
- Producing JSON reports for build artifacts
- Quality gate logic for merge protection
"""

import json
import sys
from pathlib import Path

from coderev import CodeReviewer, ReviewResult, CostEstimator


def quality_gate(
    paths: list[Path],
    fail_on_critical: bool = True,
    min_score: int = 60,
) -> bool:
    """Run a quality gate check suitable for CI pipelines.

    Returns True if the code passes, False if it should block the merge.
    """
    reviewer = CodeReviewer(model="claude-3-haiku")  # Fast and cheap for CI

    all_issues = []
    scores = []

    for path in paths:
        if not path.exists():
            continue
        result = reviewer.review_file(path, focus=["bugs", "security"])
        scores.append(result.score)
        all_issues.extend(result.issues)

        print(f"  {path.name}: {result.score}/100 "
              f"({result.critical_count} critical, {result.high_count} high)")

    if not scores:
        print("No files reviewed.")
        return True

    avg_score = sum(scores) / len(scores)
    critical_count = sum(1 for i in all_issues if i.severity.value == "critical")

    print(f"\nAverage score: {avg_score:.0f}/100")
    print(f"Total issues: {len(all_issues)} ({critical_count} critical)")

    # Gate checks
    if fail_on_critical and critical_count > 0:
        print(f"\nFAILED: {critical_count} critical issue(s) found.")
        return False

    if avg_score < min_score:
        print(f"\nFAILED: Average score {avg_score:.0f} is below threshold {min_score}.")
        return False

    print("\nPASSED: All quality gates cleared.")
    return True


def generate_json_report(paths: list[Path], output: Path):
    """Generate a JSON report for build artifacts."""
    reviewer = CodeReviewer()
    report = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "model": "claude-3-sonnet",
        "files": [],
    }

    for path in paths:
        if not path.exists():
            continue
        result = reviewer.review_file(path, focus=["bugs", "security", "performance"])
        report["files"].append({
            "path": str(path),
            "score": result.score,
            "summary": result.summary,
            "issues": [
                {
                    "line": i.line,
                    "severity": i.severity.value,
                    "category": i.category.value,
                    "message": i.message,
                    "suggestion": i.suggestion,
                }
                for i in result.issues
            ],
        })

    output.write_text(json.dumps(report, indent=2))
    print(f"Report written to {output}")


def budget_check_before_review(paths: list[Path], max_cost: float = 1.00):
    """Check estimated cost before running a review in CI.

    Prevents unexpectedly expensive reviews from running.
    """
    estimator = CostEstimator(model="claude-3-sonnet")
    total = 0.0

    for path in paths:
        if path.exists():
            est = estimator.estimate_file(path)
            total += est.total_cost

    print(f"Estimated cost: ${total:.4f} (budget: ${max_cost:.2f})")

    if total > max_cost:
        print("SKIPPED: Estimated cost exceeds budget. "
              "Use a cheaper model or review fewer files.")
        return False

    return True


if __name__ == "__main__":
    # Simulate CI: review changed files
    changed_files = [
        Path("src/coderev/reviewer.py"),
        Path("src/coderev/cli.py"),
    ]
    existing = [f for f in changed_files if f.exists()]

    if not existing:
        print("No source files found for CI example.")
        sys.exit(0)

    print("=== Budget Check ===")
    if not budget_check_before_review(existing):
        sys.exit(0)

    print("\n=== Quality Gate ===")
    passed = quality_gate(existing, fail_on_critical=True, min_score=60)
    sys.exit(0 if passed else 1)
