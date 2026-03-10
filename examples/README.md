# CodeRev Examples

Practical examples demonstrating how to use CodeRev as a Python library and CLI tool.

## Prerequisites

```bash
pip install coderev[all]
```

Set your API key:

```bash
export CODEREV_API_KEY="your-anthropic-api-key"
# OR for OpenAI:
export OPENAI_API_KEY="your-openai-api-key"
```

## Examples

| File | Description |
|------|-------------|
| [basic_review.py](basic_review.py) | Review code strings and files with the core API |
| [async_parallel.py](async_parallel.py) | Review multiple files concurrently with async |
| [custom_rules.py](custom_rules.py) | Define and apply custom review rules |
| [cost_estimation.py](cost_estimation.py) | Estimate API costs before running reviews |
| [review_history.py](review_history.py) | Track reviews and analyze quality trends |
| [ci_integration.py](ci_integration.py) | Use CodeRev in CI/CD pipelines programmatically |
| [sample_rules.yaml](sample_rules.yaml) | Example custom rules YAML file |

## Running Examples

Most examples work standalone:

```bash
python examples/basic_review.py
python examples/cost_estimation.py
```

Examples that call the API require a valid API key and will incur usage costs.
