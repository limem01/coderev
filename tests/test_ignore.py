"""Tests for .coderevignore handling."""

import pytest
from pathlib import Path

from coderev.ignore import CodeRevIgnore, DEFAULT_IGNORE_PATTERNS


class TestCodeRevIgnore:
    """Tests for CodeRevIgnore class."""
    
    def test_default_patterns_exist(self):
        assert len(DEFAULT_IGNORE_PATTERNS) > 0
        assert "node_modules/" in DEFAULT_IGNORE_PATTERNS
        assert "__pycache__/" in DEFAULT_IGNORE_PATTERNS
    
    def test_ignore_node_modules(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("node_modules/package/index.js") is True
        assert ignore.should_ignore("src/node_modules/test.js") is True
    
    def test_ignore_pycache(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("__pycache__/module.pyc") is True
        assert ignore.should_ignore("src/__pycache__/test.pyc") is True
    
    def test_ignore_pyc_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("module.pyc") is True
        assert ignore.should_ignore("src/utils/helper.pyc") is True
    
    def test_ignore_min_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("bundle.min.js") is True
        assert ignore.should_ignore("styles.min.css") is True
    
    def test_allow_normal_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("src/main.py") is False
        assert ignore.should_ignore("app/index.js") is False
        assert ignore.should_ignore("README.md") is False
    
    def test_custom_patterns(self):
        ignore = CodeRevIgnore(patterns=["*.test.py", "fixtures/"])
        assert ignore.should_ignore("test_main.test.py") is True
        assert ignore.should_ignore("fixtures/data.json") is True
        assert ignore.should_ignore("src/main.py") is False
    
    def test_add_pattern(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("custom.xyz") is False
        
        ignore.add_pattern("*.xyz")
        assert ignore.should_ignore("custom.xyz") is True
    
    def test_disable_defaults(self):
        ignore = CodeRevIgnore(patterns=["*.custom"])
        ignore.disable_defaults()
        
        # Default patterns should not apply
        assert ignore.should_ignore("node_modules/test.js") is False
        # Custom pattern still works
        assert ignore.should_ignore("file.custom") is True
    
    def test_filter_paths(self):
        ignore = CodeRevIgnore()
        paths = [
            Path("src/main.py"),
            Path("node_modules/pkg/index.js"),
            Path("src/utils.py"),
            Path("__pycache__/main.pyc"),
        ]
        
        filtered = list(ignore.filter_paths(paths))
        assert len(filtered) == 2
        assert Path("src/main.py") in filtered
        assert Path("src/utils.py") in filtered
    
    def test_load_from_file(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("""
# This is a comment
*.log
temp/
secret.txt
""")
        
        ignore = CodeRevIgnore.load(tmp_path)
        assert ignore.should_ignore("app.log") is True
        assert ignore.should_ignore("temp/file.txt") is True
        assert ignore.should_ignore("secret.txt") is True
        assert ignore.should_ignore("main.py") is False
    
    def test_empty_ignore_file(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("")
        
        ignore = CodeRevIgnore.load(tmp_path)
        # Should still have default patterns
        assert ignore.should_ignore("node_modules/x.js") is True
