"""Prompt templates for code review."""

from __future__ import annotations

import unicodedata


def normalize_unicode(text: str) -> str:
    """Normalize unicode text to NFC form.
    
    This ensures consistent handling of unicode characters in diffs,
    where the same character might be represented differently
    (e.g., composed vs decomposed forms).
    
    Also replaces common problematic unicode characters with their
    ASCII equivalents where appropriate for code review contexts.
    """
    # Normalize to NFC (Canonical Decomposition, followed by Canonical Composition)
    normalized = unicodedata.normalize('NFC', text)
    
    # Replace various unicode quote characters with ASCII equivalents
    # This helps with diffs that may have different quote styles
    quote_replacements = {
        '\u2018': "'",  # left single quotation mark
        '\u2019': "'",  # right single quotation mark
        '\u201c': '"',  # left double quotation mark
        '\u201d': '"',  # right double quotation mark
        '\u2032': "'",  # prime
        '\u2033': '"',  # double prime
        '\u00ab': '"',  # left-pointing double angle quotation mark
        '\u00bb': '"',  # right-pointing double angle quotation mark
    }
    
    for unicode_char, ascii_char in quote_replacements.items():
        normalized = normalized.replace(unicode_char, ascii_char)
    
    return normalized


SYSTEM_PROMPT = """You are an expert code reviewer with deep knowledge of software engineering best practices, security vulnerabilities, performance optimization, and clean code principles.

Your task is to review code and provide actionable, specific feedback. Focus on issues that matter - don't nitpick minor style issues unless explicitly asked.

For each issue found, provide:
1. The line number(s) affected
2. Severity: critical, high, medium, or low
3. Category: bug, security, performance, style, or architecture
4. A clear explanation of the issue
5. A specific suggestion for how to fix it

Be concise but thorough. Prioritize issues by impact."""


def build_review_prompt(
    code: str,
    language: str | None = None,
    focus: list[str] | None = None,
    context: str | None = None,
) -> str:
    """Build the review prompt for a code snippet."""
    parts = []
    
    parts.append("Review the following code and identify issues:\n")
    
    if language:
        parts.append(f"Language: {language}\n")
    
    if focus:
        parts.append(f"Focus areas: {', '.join(focus)}\n")
    
    if context:
        parts.append(f"Context: {context}\n")
    
    parts.append(f"\n```{language or ''}\n{code}\n```\n")
    
    parts.append("""
Respond with a JSON object containing:
{
  "summary": "Brief overall assessment",
  "issues": [
    {
      "line": <line_number or null>,
      "end_line": <end_line_number or null>,
      "severity": "critical|high|medium|low",
      "category": "bug|security|performance|style|architecture",
      "message": "Description of the issue",
      "suggestion": "How to fix it",
      "code_suggestion": "Optional corrected code snippet"
    }
  ],
  "score": <0-100 overall code quality score>,
  "positive": ["List of things done well"]
}

Only output valid JSON, no other text.""")
    
    return "".join(parts)


def build_diff_prompt(
    diff: str,
    focus: list[str] | None = None,
) -> str:
    """Build the review prompt for a git diff.
    
    Unicode content in the diff is normalized for consistent handling.
    """
    parts = []
    
    parts.append("Review the following git diff and identify issues with the changes:\n")
    
    if focus:
        parts.append(f"Focus areas: {', '.join(focus)}\n")
    
    # Normalize unicode in diff content
    normalized_diff = normalize_unicode(diff)
    parts.append(f"\n```diff\n{normalized_diff}\n```\n")
    
    parts.append("""
Focus only on the changed lines (+ lines). Consider the context but only flag issues in new/modified code.

Respond with a JSON object containing:
{
  "summary": "Brief assessment of the changes",
  "issues": [
    {
      "file": "filename",
      "line": <line_number in the new file>,
      "severity": "critical|high|medium|low",
      "category": "bug|security|performance|style|architecture",
      "message": "Description of the issue",
      "suggestion": "How to fix it"
    }
  ],
  "score": <0-100 overall change quality score>,
  "positive": ["List of good practices in the changes"]
}

Only output valid JSON, no other text.""")
    
    return "".join(parts)


def build_pr_prompt(
    pr_title: str,
    pr_description: str | None,
    files_changed: list[dict],
    focus: list[str] | None = None,
) -> str:
    """Build the review prompt for a pull request."""
    parts = []
    
    parts.append(f"Review this pull request:\n\nTitle: {pr_title}\n")
    
    if pr_description:
        parts.append(f"Description: {pr_description}\n")
    
    if focus:
        parts.append(f"Focus areas: {', '.join(focus)}\n")
    
    parts.append("\nFiles changed:\n")
    
    for file_info in files_changed:
        parts.append(f"\n--- {file_info['filename']} ---\n")
        parts.append(f"```{file_info.get('language', '')}\n{file_info['patch']}\n```\n")
    
    parts.append("""
Review the entire PR holistically. Consider:
- Do the changes align with the stated PR description?
- Are there any bugs, security issues, or performance problems?
- Is the code well-structured and maintainable?

Respond with a JSON object containing:
{
  "summary": "Overall PR assessment",
  "verdict": "approve|request_changes|comment",
  "issues": [
    {
      "file": "filename",
      "line": <line_number>,
      "severity": "critical|high|medium|low",
      "category": "bug|security|performance|style|architecture",
      "message": "Description of the issue",
      "suggestion": "How to fix it"
    }
  ],
  "score": <0-100 overall PR quality score>,
  "positive": ["List of things done well in this PR"]
}

Only output valid JSON, no other text.""")
    
    return "".join(parts)
