# CodeRev for VS Code

AI-powered code review directly in your editor. Uses the [CodeRev CLI](https://pypi.org/project/coderev/) to analyze your code with Claude, GPT-4, and other LLMs.

## Features

- **Review Current File** — Run AI code review on any open file
- **Review Selection** — Highlight code and review just that section
- **Review Git Diff** — Analyze unstaged or staged changes
- **Cost Estimation** — See estimated API cost before running a review
- **Inline Diagnostics** — Issues appear in the Problems panel and as editor annotations
- **Auto-Review on Save** — Optionally review files automatically when you save
- **Right-Click Menu** — Quick access from the editor and explorer context menus

## Prerequisites

Install the CodeRev CLI:

```bash
pip install coderev
```

Set your API key:

```bash
export CODEREV_API_KEY="your-anthropic-api-key"
# Or for OpenAI:
export OPENAI_API_KEY="your-openai-api-key"
```

## Usage

1. Open a file in VS Code
2. Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
3. Type `CodeRev` and select a command:
   - **CodeRev: Review Current File**
   - **CodeRev: Review Selection**
   - **CodeRev: Review Git Diff**
   - **CodeRev: Review Staged Changes**
   - **CodeRev: Estimate Review Cost**

Or right-click a file in the editor/explorer for quick access.

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `coderev.cliPath` | `coderev` | Path to the coderev CLI executable |
| `coderev.pythonPath` | `python` | Path to Python with coderev installed |
| `coderev.defaultFocus` | `[]` | Default focus areas: `bugs`, `security`, `performance`, `style`, `architecture` |
| `coderev.autoReviewOnSave` | `false` | Auto-review files on save |
| `coderev.showInlineAnnotations` | `true` | Show issues as inline editor annotations |
| `coderev.severityFilter` | `all` | Minimum severity to display: `all`, `low`, `medium`, `high`, `critical` |

## How It Works

The extension wraps the `coderev` CLI, running it with `--format json` and parsing the structured output. Results are displayed as:

1. **VS Code Diagnostics** — Issues appear in the Problems panel with proper severity levels
2. **Output Panel** — Detailed review with suggestions in the CodeRev output channel
3. **Notifications** — Summary of issues found

## Development

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```

## License

MIT — see the [main project license](../LICENSE).
