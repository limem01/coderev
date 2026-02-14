# Contributing to CodeRev

Thank you for your interest in contributing to CodeRev! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/coderev.git
   cd coderev
   ```

3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

4. Set up pre-commit hooks:
   ```bash
   pre-commit install
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=coderev --cov-report=html

# Run specific test file
pytest tests/test_reviewer.py

# Run specific test
pytest tests/test_reviewer.py::TestCodeReviewer::test_review_code
```

### Code Style

We use `ruff` for linting and formatting:

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

### Type Checking

```bash
mypy src/
```

## Submitting Changes

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and commit with clear messages:
   ```bash
   git commit -m "Add feature: description of what you added"
   ```

3. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

4. Create a Pull Request with:
   - Clear description of changes
   - Link to any related issues
   - Screenshots if relevant

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Include tests for new functionality
- Update documentation as needed
- Ensure all tests pass
- Follow the existing code style

## Reporting Issues

When reporting issues, please include:

- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant error messages or logs

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Help others learn

## Questions?

Open an issue or start a discussion. We're happy to help!
