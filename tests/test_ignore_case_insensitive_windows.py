"""Windows-specific behavior tests for .coderevignore.

These tests are skipped on non-Windows platforms.
"""

import os

import pytest

from coderev.ignore import CodeRevIgnore


@pytest.mark.skipif(os.name != "nt", reason="Windows-only filesystem semantics")
def test_ignore_matching_is_case_insensitive_on_windows():
    ignore = CodeRevIgnore(patterns=["Node_Modules/", "*.LoG"])

    assert ignore.should_ignore("node_modules/pkg/index.js") is True
    assert ignore.should_ignore("NODE_MODULES/pkg/index.js") is True
    assert ignore.should_ignore("logs/APP.LOG") is True
