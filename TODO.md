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
- [x] Avoid double API calls when using --fail-on in sequential review mode
- [x] Add regression tests for Windows-style patterns in .coderevignore (backslashes, directory segment matching, leading ./ and /)
- [x] Make .coderevignore matching case-insensitive on Windows (filesystem semantics)

## Documentation
- [x] Add GIF demos to README
- [x] Write detailed API docs
- [x] Add more code examples
- [x] Create comparison with other tools

## New Tasks
- [x] Support negation patterns in .coderevignore (e.g. `!important.log` to unignore)
- [x] Optional `.gitignore` integration (load existing repo exclusions; `.coderevignore` still overrides)
- [x] Support `**` globstar patterns in `.coderevignore` (e.g. `docs/**/*.md`, `**/build/`) with proper zero-or-more-directory semantics
- [x] Anchor `.coderevignore` patterns with a leading `/` (or `./`) to the repo root (gitignore semantics): `/build/` matches top-level `build/` but not nested `src/build/`; unanchored patterns still match at any depth
- [x] Anchor `.coderevignore` patterns containing an internal `/` to the repo root and stop a lone `*` from crossing directory separators (gitignore semantics): `src/*.py` matches `src/a.py` but not `src/sub/a.py`; `doc/frotz` no longer matches `a/doc/frotz`
- [x] Support `[...]` character classes in anchored/globstar `.coderevignore` patterns (ranges `[a-z]`, negation `[!0-9]`) so they match a single non-separator char like gitignore, fixing the inconsistency where only the unanchored `fnmatch` path handled brackets
- [x] Support gitignore escape semantics in `.coderevignore`: `\#` is a literal leading `#` (not a comment), `\!` is a literal leading `!` (not a negation), and unescaped trailing whitespace is stripped
- [x] Precompile `.coderevignore` patterns once and cache them (avoid re-parsing/normalizing/recompiling every pattern for every path); invalidate the cache on `add_pattern`/`disable_defaults`
- [x] Stop `*`/`?` in unanchored `.coderevignore` patterns from crossing directory separators (gitignore FNM_PATHNAME semantics): `a?.py` no longer matches `a/.py`. Matching each path segment keeps no-slash patterns matching at any depth and lets them match a directory component (`foo` matches `a/foo/b.txt`), fixing the inconsistency where only anchored/globstar patterns enforced this
- [x] Add cost-estimation pricing for current-generation models (Claude 3.7 Sonnet; Claude 4 Opus / Opus 4.1 / Sonnet 4 / Haiku 4.5; GPT-4.1 family; o3-mini/o4-mini) with dated IDs and short aliases, and route o3/o4 through tiktoken token counting
- [x] Fix `get_model_pricing` so dated/suffixed model IDs (e.g. `gpt-4o-2024-08-06`, `gpt-4o-mini-2024-07-18`, `claude-sonnet-4-20250514`) resolve to the most specific base model via longest-prefix + token-boundary matching, instead of the first family sharing a provider prefix (previously mispriced `gpt-4o-mini` as `gpt-4`, ~200x too high on input)
- [x] Warn when cost estimation falls back to `DEFAULT_PRICING` for an unknown model: add `is_known_model()`, carry a `pricing_is_estimated` flag on `CostEstimate`, and surface it (rich warning line + JSON field) so users don't mistake a default-rate guess for an accurate figure
