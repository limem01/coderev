"""Tests for unicode handling in code review."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from coderev.reviewer import CodeReviewer, is_binary_file
from coderev.cache import ReviewCache
from coderev.prompts import normalize_unicode, build_diff_prompt


class TestUnicodeBinaryDetection:
    """Tests for proper detection of text files with unicode content."""
    
    def test_utf8_chinese_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with Chinese characters are not binary."""
        file = tmp_path / "chinese.py"
        file.write_text('# 你好世界\nprint("Hello")', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_japanese_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with Japanese characters are not binary."""
        file = tmp_path / "japanese.rb"
        file.write_text('# こんにちは世界\nputs "Hello"', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_korean_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with Korean characters are not binary."""
        file = tmp_path / "korean.js"
        file.write_text('// 안녕하세요\nconsole.log("Hello");', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_arabic_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with Arabic characters are not binary."""
        file = tmp_path / "arabic.txt"
        file.write_text('مرحبا بالعالم\nHello World', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_russian_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with Cyrillic characters are not binary."""
        file = tmp_path / "russian.py"
        file.write_text('# Привет мир\nprint("Hello")', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_emoji_text_not_binary(self, tmp_path):
        """Test that UTF-8 files with emojis are not binary."""
        file = tmp_path / "emoji.md"
        file.write_text('# 🚀 Rocket Launch\n\n✨ Features:\n- 🎉 Party time!', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_mixed_scripts_not_binary(self, tmp_path):
        """Test that UTF-8 files with mixed scripts are not binary."""
        file = tmp_path / "mixed.txt"
        content = """
        English: Hello World
        Chinese: 你好世界
        Japanese: こんにちは世界
        Korean: 안녕하세요
        Arabic: مرحبا
        Russian: Привет
        Emoji: 🎉🚀✨
        Greek: Γειά σου κόσμε
        Hebrew: שלום עולם
        """
        file.write_text(content, encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_mathematical_symbols_not_binary(self, tmp_path):
        """Test that UTF-8 files with math symbols are not binary."""
        file = tmp_path / "math.py"
        file.write_text('# α² + β² = γ²\n# ∑ ∫ ∂ ∇ ∞', encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_utf8_accented_characters_not_binary(self, tmp_path):
        """Test that UTF-8 files with accented characters are not binary."""
        file = tmp_path / "french.py"
        file.write_text("# Café résumé naïve\nprint('Ça va bien')", encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_latin1_file_not_binary(self, tmp_path):
        """Test that Latin-1 encoded files are not binary."""
        file = tmp_path / "latin1.txt"
        # Write with latin-1 encoding
        file.write_bytes("Café résumé naïve".encode('latin-1'))
        assert is_binary_file(file) is False
    
    def test_actual_binary_still_detected(self, tmp_path):
        """Test that actual binary files are still detected."""
        file = tmp_path / "binary.dat"
        file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")
        assert is_binary_file(file) is True
    
    def test_png_header_still_binary(self, tmp_path):
        """Test that files with PNG headers are still binary."""
        file = tmp_path / "image.dat"
        file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert is_binary_file(file) is True


class TestUnicodeNormalization:
    """Tests for unicode normalization in prompts."""
    
    def test_normalize_nfc_composition(self):
        """Test that NFD strings are normalized to NFC."""
        # 'é' as e + combining acute accent (NFD)
        nfd_string = "caf\u0065\u0301"
        # 'é' as single codepoint (NFC)
        nfc_string = "caf\u00e9"
        
        assert normalize_unicode(nfd_string) == nfc_string
    
    def test_normalize_fancy_quotes_single(self):
        """Test that fancy single quotes are replaced with ASCII."""
        text = "It\u2019s a test"  # right single quotation mark
        result = normalize_unicode(text)
        assert result == "It's a test"
    
    def test_normalize_fancy_quotes_double(self):
        """Test that fancy double quotes are replaced with ASCII."""
        text = "\u201cHello\u201d"  # left and right double quotation marks
        result = normalize_unicode(text)
        assert result == '"Hello"'
    
    def test_normalize_angle_quotes(self):
        """Test that angle quotes are replaced with ASCII."""
        text = "\u00abquoted\u00bb"  # guillemets
        result = normalize_unicode(text)
        assert result == '"quoted"'
    
    def test_normalize_preserves_regular_unicode(self):
        """Test that regular unicode (like Chinese) is preserved."""
        text = "你好世界"
        result = normalize_unicode(text)
        assert result == "你好世界"
    
    def test_normalize_preserves_emojis(self):
        """Test that emojis are preserved."""
        text = "🚀 rocket 🎉"
        result = normalize_unicode(text)
        assert result == "🚀 rocket 🎉"


class TestUnicodeDiffPrompt:
    """Tests for unicode handling in diff prompts."""
    
    def test_diff_with_unicode_content(self):
        """Test that diffs with unicode content are handled."""
        diff = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
-# Old comment
+# 你好世界 - Chinese greeting
 print("Hello")
"""
        prompt = build_diff_prompt(diff)
        assert "你好世界" in prompt
        assert "```diff" in prompt
    
    def test_diff_with_emoji(self):
        """Test that diffs with emojis are handled."""
        diff = """diff --git a/README.md b/README.md
+# 🚀 New Feature
+This adds ✨ sparkle ✨ to everything!
"""
        prompt = build_diff_prompt(diff)
        assert "🚀" in prompt
        assert "✨" in prompt
    
    def test_diff_with_fancy_quotes_normalized(self):
        """Test that fancy quotes in diffs are normalized."""
        diff = """diff --git a/test.py b/test.py
+print(\u201cHello World\u201d)
"""
        prompt = build_diff_prompt(diff)
        # Fancy quotes should be converted to ASCII
        assert '"Hello World"' in prompt


class TestUnicodeCacheKeys:
    """Tests for unicode cache key consistency."""
    
    def test_cache_key_same_for_nfc_and_nfd(self, tmp_path):
        """Test that NFC and NFD forms produce the same cache key."""
        cache = ReviewCache(cache_dir=tmp_path, enabled=True)
        
        # 'café' in NFC (composed)
        nfc_content = "caf\u00e9"
        # 'café' in NFD (decomposed)
        nfd_content = "caf\u0065\u0301"
        
        key1 = cache._generate_cache_key(nfc_content, "model", [], "python")
        key2 = cache._generate_cache_key(nfd_content, "model", [], "python")
        
        assert key1 == key2
    
    def test_cache_key_different_for_different_unicode(self, tmp_path):
        """Test that different unicode content produces different keys."""
        cache = ReviewCache(cache_dir=tmp_path, enabled=True)
        
        key1 = cache._generate_cache_key("你好", "model", [], "python")
        key2 = cache._generate_cache_key("こんにちは", "model", [], "python")
        
        assert key1 != key2
    
    def test_cache_stores_unicode_content(self, tmp_path):
        """Test that cache can store and retrieve unicode content."""
        cache = ReviewCache(cache_dir=tmp_path, enabled=True)
        
        content = "# 你好世界\nprint('Hello')"
        result = {"summary": "看起来不错", "issues": [], "score": 85}
        
        cache.set(content, "model", result, [], "python")
        cached = cache.get(content, "model", [], "python")
        
        assert cached is not None
        assert cached["summary"] == "看起来不错"


class TestUnicodeFileReview:
    """Tests for reviewing files with unicode content."""
    
    @patch("coderev.reviewer.get_provider")
    def test_review_file_with_unicode(self, mock_get_provider, tmp_path):
        """Test that files with unicode content can be reviewed."""
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider
        
        mock_response = MagicMock()
        mock_response.content = '{"summary": "Good", "issues": [], "score": 80, "positive": []}'
        mock_provider.call.return_value = mock_response
        mock_provider.parse_json_response.return_value = {
            "summary": "Good", "issues": [], "score": 80, "positive": []
        }
        
        # Create file with unicode content
        file = tmp_path / "unicode.py"
        file.write_text('# 你好世界\nprint("Hello World 🚀")', encoding="utf-8")
        
        reviewer = CodeReviewer(api_key="test-key", cache_enabled=False)
        result = reviewer.review_file(file)
        
        assert result.score == 80
        assert mock_provider.call.called
    
    @patch("coderev.reviewer.get_provider")
    def test_review_diff_with_unicode(self, mock_get_provider):
        """Test that diffs with unicode can be reviewed."""
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider
        
        mock_response = MagicMock()
        mock_response.content = '{"summary": "Good", "issues": [], "score": 80, "positive": []}'
        mock_provider.call.return_value = mock_response
        mock_provider.parse_json_response.return_value = {
            "summary": "Good", "issues": [], "score": 80, "positive": []
        }
        
        diff = """diff --git a/test.py b/test.py
+# 日本語コメント (Japanese comment)
+print("こんにちは世界")  # Hello World in Japanese
"""
        
        reviewer = CodeReviewer(api_key="test-key", cache_enabled=False)
        result = reviewer.review_diff(diff)
        
        assert result.score == 80
        assert mock_provider.call.called
