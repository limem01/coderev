"""Async parallel review examples using CodeRev.

Demonstrates:
- Reviewing multiple files concurrently
- Controlling concurrency limits
- Collecting and aggregating results
- Using the convenience function review_files_parallel
"""

import asyncio
from pathlib import Path

from coderev import AsyncCodeReviewer, review_files_parallel


async def parallel_review():
    """Review an entire directory of files in parallel."""
    reviewer = AsyncCodeReviewer(
        max_concurrent=5,  # Up to 5 API calls at once
    )

    # Collect Python files from a directory
    src_dir = Path("src/coderev")
    files = sorted(src_dir.glob("*.py"))

    if not files:
        print("No files found in src/coderev/")
        return

    print(f"Reviewing {len(files)} files with max 5 concurrent requests...\n")

    results = await reviewer.review_files_async(
        files,
        focus=["bugs", "security"],
    )

    # Print a summary table
    print(f"{'File':<30} {'Score':>5}  {'Issues':>6}  {'Critical':>8}")
    print("-" * 55)

    for file_path, result in sorted(results.items(), key=lambda x: x[1].score):
        print(
            f"{file_path.name:<30} {result.score:>5}  "
            f"{len(result.issues):>6}  {result.critical_count:>8}"
        )

    # Aggregate stats
    scores = [r.score for r in results.values() if r.score >= 0]
    if scores:
        avg = sum(scores) / len(scores)
        print(f"\nAverage score: {avg:.1f}/100")
        print(f"Lowest: {min(scores)} | Highest: {max(scores)}")


async def convenience_function():
    """Use the top-level helper for quick parallel reviews."""
    files = list(Path("src/coderev").glob("*.py"))[:3]

    if not files:
        print("No files found")
        return

    results = await review_files_parallel(
        files,
        focus=["performance"],
        max_concurrent=3,
    )

    for path, result in results.items():
        print(f"{path.name}: {result.score}/100 ({len(result.issues)} issues)")


if __name__ == "__main__":
    print("=== Parallel File Review ===")
    asyncio.run(parallel_review())

    print("\n=== Convenience Function ===")
    asyncio.run(convenience_function())
