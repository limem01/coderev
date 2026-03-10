"""Cost estimation examples for CodeRev.

Demonstrates:
- Estimating cost before running a review
- Comparing costs across different models
- Counting tokens for files and directories
"""

from pathlib import Path

from coderev import CostEstimator, CostEstimate, count_tokens, get_model_pricing


def estimate_single_file():
    """Estimate the cost of reviewing a single file."""
    estimator = CostEstimator(model="claude-3-sonnet")

    target = Path("src/coderev/reviewer.py")
    if not target.exists():
        print(f"File {target} not found, using sample text")
        sample = "def hello(): pass\n" * 100
        tokens = count_tokens(sample)
        print(f"Sample tokens: {tokens}")
        return

    estimate = estimator.estimate_file(target)
    print(f"File: {target}")
    print(f"Input tokens:  ~{estimate.input_tokens:,}")
    print(f"Output tokens: ~{estimate.output_tokens:,}")
    print(f"Estimated cost: ${estimate.total_cost:.4f}")


def compare_model_costs():
    """Compare the cost of reviewing the same code across models."""
    models = [
        "claude-3-haiku",
        "claude-3-sonnet",
        "claude-3-opus",
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4",
    ]

    target = Path("src/coderev/reviewer.py")
    if not target.exists():
        print("File not found, skipping model comparison")
        return

    print(f"\nCost comparison for {target}:\n")
    print(f"{'Model':<28} {'Input $/M':>10} {'Output $/M':>11} {'Est. Cost':>10}")
    print("-" * 62)

    for model in models:
        pricing = get_model_pricing(model)
        estimator = CostEstimator(model=model)
        estimate = estimator.estimate_file(target)
        print(
            f"{model:<28} ${pricing[0]:>8.2f} ${pricing[1]:>9.2f} "
            f"${estimate.total_cost:>8.4f}"
        )


def estimate_directory():
    """Estimate cost for reviewing an entire directory."""
    estimator = CostEstimator(model="claude-3-sonnet")

    src_dir = Path("src/coderev")
    if not src_dir.exists():
        print("src/coderev not found")
        return

    files = list(src_dir.glob("*.py"))
    total_cost = 0.0
    total_tokens = 0

    print(f"\nDirectory estimate for {src_dir}/ ({len(files)} files):\n")

    for f in sorted(files):
        estimate = estimator.estimate_file(f)
        total_cost += estimate.total_cost
        total_tokens += estimate.input_tokens
        print(f"  {f.name:<25} ~{estimate.input_tokens:>6,} tokens  ${estimate.total_cost:.4f}")

    print(f"\n  {'TOTAL':<25} ~{total_tokens:>6,} tokens  ${total_cost:.4f}")
    print(f"\n  Tip: Use claude-3-haiku to reduce cost by ~10x")


if __name__ == "__main__":
    print("=== Single File Estimate ===")
    estimate_single_file()

    print("\n=== Model Cost Comparison ===")
    compare_model_costs()

    print("\n=== Directory Estimate ===")
    estimate_directory()
