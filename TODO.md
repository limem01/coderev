# CodeRev Development Roadmap

## Phase 1: Core Improvements (Week 1-2)
- [x] Add async support for parallel file reviews
- [x] Implement caching for repeated reviews
- [x] Add support for OpenAI models (GPT-4)
- [x] Create `.coderev` ignore file support
- [x] Add line-by-line inline suggestions

## Phase 2: Integrations (Week 2-3)
- [x] GitLab MR support
- [x] Bitbucket PR support
- [x] VS Code extension
- [x] Pre-commit hook package
- [x] GitHub Action (published to marketplace)

## Phase 3: Advanced Features (Week 3-4)
- [x] Custom rule definitions (YAML)
- [x] Team configuration sharing
- [x] Review history and tracking
- [x] Diff viewer with annotations
- [x] Cost estimation before review

## Phase 4: Polish (Week 4-5)
- [x] Interactive TUI mode
- [x] Auto-fix capabilities
- [x] Batch review with summary report
- [x] Integration tests with real API
- [x] PyPI publication

## Bugs to Fix
- [x] Handle binary files gracefully
- [x] Better error messages for rate limits
- [x] Unicode handling in diffs
- [x] Normalize path separators when applying .coderevignore (Windows compatibility)

## Documentation
- [x] Add GIF demos to README
- [x] Write detailed API docs
- [x] Add more code examples
- [x] Create comparison with other tools
