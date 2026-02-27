# CodeRev

An intelligent CLI tool that uses AI to review your code, analyze pull requests, and suggest improvements.

## Features

- **Code Analysis**: Review individual files or entire directories
- **Git Diff Review**: Analyze staged changes before committing
- **GitHub PR Integration**: Review pull requests directly from the command line
- **Multi-Language Support**: Works with Python, JavaScript, TypeScript, Go, Rust, and more
- **Configurable Focus**: Choose between security, performance, style, or bug detection
- **Rich Output**: Beautiful terminal output with syntax highlighting

## Installation

```bash
pip install coderev
```

Or install from source:

```bash
git clone https://github.com/yourusername/coderev.git
cd coderev
pip install -e .
```

## Quick Start

```bash
# Review a single file
coderev review app.py

# Review a directory
coderev review src/ --recursive

# Review staged git changes
coderev diff

# Review a GitHub PR
coderev pr https://github.com/owner/repo/pull/123

# Focus on security issues
coderev review app.py --focus security

# Output as JSON
coderev review app.py --format json
```

## Configuration

Create a `.coderev.toml` in your project root or home directory:

```toml
[coderev]
api_key = "your-api-key"  # Or use CODEREV_API_KEY env var
model = "claude-3-sonnet"
focus = ["bugs", "security", "performance"]
ignore_patterns = ["*.test.py", "migrations/*"]
max_file_size = 100000  # bytes
language_hints = true

[github]
token = "ghp_xxx"  # Or use GITHUB_TOKEN env var
```

## Usage

### Review Files

```bash
# Basic review
coderev review main.py

# Review with specific focus areas
coderev review main.py --focus security --focus performance

# Review multiple files
coderev review src/api.py src/models.py src/utils.py

# Recursive directory review
coderev review ./src --recursive --exclude "*.test.py"
```

### Review Git Changes

```bash
# Review staged changes
coderev diff

# Review changes between branches
coderev diff main..feature-branch

# Review last N commits
coderev diff HEAD~3
```

### GitHub PR Review

```bash
# Review a PR by URL
coderev pr https://github.com/owner/repo/pull/42

# Review a PR by number (requires GitHub remote)
coderev pr 42

# Post review comments directly to PR
coderev pr 42 --post-comments
```

### Output Formats

```bash
# Rich terminal output (default)
coderev review app.py

# JSON output for CI/CD pipelines
coderev review app.py --format json

# Markdown output
coderev review app.py --format markdown

# SARIF output for GitHub Security
coderev review app.py --format sarif
```

## Focus Areas

| Focus | Description |
|-------|-------------|
| `bugs` | Logic errors, null references, off-by-one errors |
| `security` | SQL injection, XSS, hardcoded secrets, unsafe deserialization |
| `performance` | N+1 queries, unnecessary loops, memory leaks |
| `style` | Code style, naming conventions, documentation |
| `architecture` | Design patterns, SOLID principles, coupling |
| `testing` | Test coverage suggestions, edge cases |

## CI/CD Integration

### GitHub Action (Marketplace)

The easiest way to use CodeRev in your CI/CD pipeline is via our official GitHub Action:

```yaml
name: AI Code Review
on: [pull_request]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run CodeRev
        uses: khalil/coderev@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          model: 'claude-3-sonnet-20240229'
          focus: 'bugs,security,performance'
          fail_on: 'critical'
          post_review: 'true'
```

#### Action Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `anthropic_api_key` | Anthropic API key for Claude models | No* | - |
| `openai_api_key` | OpenAI API key for GPT models | No* | - |
| `github_token` | GitHub token for posting reviews | Yes | `${{ github.token }}` |
| `model` | Model to use | No | `claude-3-sonnet-20240229` |
| `focus` | Focus areas (comma-separated) | No | `bugs,security,performance` |
| `fail_on` | Fail on severity level | No | - |
| `post_review` | Post review to PR | No | `true` |
| `max_files` | Max files to review | No | `20` |
| `ignore_patterns` | Patterns to ignore | No | `*.test.*,*.spec.*` |

*Either `anthropic_api_key` or `openai_api_key` is required.

#### Action Outputs

| Output | Description |
|--------|-------------|
| `score` | Code quality score (0-100) |
| `issues_count` | Total issues found |
| `critical_count` | Critical issues |
| `high_count` | High severity issues |
| `medium_count` | Medium severity issues |
| `low_count` | Low severity issues |
| `review_url` | URL to posted review |

#### Advanced Example

```yaml
name: AI Code Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  coderev:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Run CodeRev
        id: review
        uses: khalil/coderev@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          focus: 'bugs,security,performance,architecture'
          fail_on: 'high'
          max_files: '30'
          ignore_patterns: '*.test.*,*.spec.*,*.min.js,package-lock.json'
      
      - name: Quality Gate
        if: always()
        run: |
          if [ "${{ steps.review.outputs.score }}" -lt 70 ]; then
            echo "::error::Code quality score is below 70"
            exit 1
          fi
```

### Manual GitHub Actions Setup

If you prefer more control, you can install CodeRev directly:

```yaml
name: Code Review
on: [pull_request]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install coderev
      - run: coderev diff origin/main...HEAD --format sarif > results.sarif
        env:
          CODEREV_API_KEY: ${{ secrets.CODEREV_API_KEY }}
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: coderev
        name: AI Code Review
        entry: coderev diff --staged --fail-on high
        language: system
        pass_filenames: false
```

## API

CodeRev can also be used as a Python library:

```python
from coderev import CodeReviewer

reviewer = CodeReviewer(api_key="your-key")

# Review code string
result = reviewer.review_code("""
def get_user(id):
    query = f"SELECT * FROM users WHERE id = {id}"
    return db.execute(query)
""", language="python", focus=["security"])

for issue in result.issues:
    print(f"[{issue.severity}] Line {issue.line}: {issue.message}")
```

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/yourusername/coderev.git
cd coderev
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .

# Run type checking
mypy src/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details.
