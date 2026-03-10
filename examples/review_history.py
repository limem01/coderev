"""Review history and tracking examples for CodeRev.

Demonstrates:
- Saving review results to history
- Querying past reviews
- Analyzing quality trends over time
- Generating history statistics
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from coderev import ReviewHistory, ReviewEntry, HistoryStats, ReviewResult


def save_and_query():
    """Save a review result and query history."""
    history = ReviewHistory()

    # Create a mock review result for demonstration
    result = ReviewResult(
        score=72,
        summary="Found 3 issues: 1 SQL injection vulnerability, "
                "1 missing error handling, 1 style issue.",
        issues=[],
        suggestions=[],
        critical_count=1,
        high_count=0,
        medium_count=1,
        low_count=1,
    )

    # Save to history
    entry = ReviewEntry.from_review_result(
        result,
        file_path="src/api/routes.py",
        review_type="file",
        model="claude-3-sonnet",
    )
    history.add(entry)
    print(f"Saved review: {entry.file_path} -> {entry.score}/100")

    # Query recent reviews
    recent = history.get_recent(limit=10)
    print(f"\nRecent reviews ({len(recent)}):")
    for e in recent:
        print(f"  {e.timestamp[:10]} | {e.file_path or 'snippet'} | "
              f"{e.score}/100 | {e.issue_count} issues")


def analyze_trends():
    """Analyze code quality trends from review history."""
    history = ReviewHistory()

    # Get stats for the last 30 days
    stats = history.get_stats(days=30)
    if stats.total_reviews == 0:
        print("No reviews in the last 30 days.")
        return

    print(f"Last 30 days:")
    print(f"  Total reviews:    {stats.total_reviews}")
    print(f"  Average score:    {stats.avg_score:.1f}/100")
    print(f"  Total issues:     {stats.total_issues}")
    print(f"  Critical issues:  {stats.critical_issues}")

    # Compare with previous period
    prev_stats = history.get_stats(days=60)
    if prev_stats.total_reviews > stats.total_reviews:
        prev_avg = (
            (prev_stats.avg_score * prev_stats.total_reviews
             - stats.avg_score * stats.total_reviews)
            / (prev_stats.total_reviews - stats.total_reviews)
        )
        delta = stats.avg_score - prev_avg
        direction = "improved" if delta > 0 else "declined"
        print(f"\n  Trend: Score {direction} by {abs(delta):.1f} points vs prior 30 days")


def query_by_file():
    """Look up review history for a specific file."""
    history = ReviewHistory()

    target = "src/coderev/reviewer.py"
    entries = history.get_by_file(target, limit=5)

    if not entries:
        print(f"No review history for {target}")
        return

    print(f"History for {target}:")
    for e in entries:
        print(f"  {e.timestamp[:16]} | Score: {e.score} | "
              f"Issues: {e.issue_count} ({e.critical_count} critical)")


if __name__ == "__main__":
    print("=== Save and Query ===")
    save_and_query()

    print("\n=== Trend Analysis ===")
    analyze_trends()

    print("\n=== File History ===")
    query_by_file()
