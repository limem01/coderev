"""Tests for the TUI module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coderev.config import Config
from coderev.tui import TUIState, TUIApp, run_tui
from coderev.reviewer import ReviewResult, Issue, Severity, Category


class TestTUIState:
    """Tests for TUIState dataclass."""
    
    def test_default_state(self):
        """Test default state initialization."""
        state = TUIState()
        
        assert state.cwd == Path.cwd()
        assert state.selected_files == []
        assert state.current_view == "files"
        assert state.cursor_position == 0
        assert state.scroll_offset == 0
        assert state.review_results == {}
        assert state.focus == ["bugs", "security", "performance"]
        assert state.show_hidden is False
        assert state.recursive is False
    
    def test_custom_state(self):
        """Test custom state initialization."""
        custom_path = Path("/tmp")
        state = TUIState(
            cwd=custom_path,
            show_hidden=True,
            focus=["security"],
        )
        
        assert state.cwd == custom_path
        assert state.show_hidden is True
        assert state.focus == ["security"]


class TestTUIApp:
    """Tests for TUIApp class."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create some test files and directories
            (tmppath / "file1.py").write_text("print('hello')")
            (tmppath / "file2.js").write_text("console.log('hello');")
            (tmppath / "subdir").mkdir()
            (tmppath / "subdir" / "nested.py").write_text("x = 1")
            (tmppath / ".hidden").write_text("hidden file")
            
            yield tmppath
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock(spec=Config)
        config.model = "claude-3-sonnet"
        config.focus = ["bugs"]
        config.max_file_size = 100000
        config.language_hints = True
        config.validate.return_value = []
        config.get_provider.return_value = "anthropic"
        config.get_api_key_for_provider.return_value = "test-key"
        return config
    
    def test_app_initialization(self, temp_dir, mock_config):
        """Test TUI app initialization."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        assert app.state.cwd == temp_dir
        assert app.config == mock_config
        assert app._running is False
    
    def test_get_current_items_excludes_hidden(self, temp_dir, mock_config):
        """Test that hidden files are excluded by default."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        items = app._get_current_items()
        item_names = [p.name for p in items]
        
        assert ".hidden" not in item_names
        assert "file1.py" in item_names or any(p.name == "file1.py" for p in items)
    
    def test_get_current_items_shows_hidden(self, temp_dir, mock_config):
        """Test that hidden files are shown when enabled."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.show_hidden = True
        
        items = app._get_current_items()
        item_names = [p.name for p in items]
        
        assert ".hidden" in item_names
    
    def test_get_file_icon(self, temp_dir, mock_config):
        """Test file icon detection."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        assert app._get_file_icon(Path("test.py")) == "🐍"
        assert app._get_file_icon(Path("test.js")) == "📜"
        assert app._get_file_icon(Path("test.ts")) == "📘"
        assert app._get_file_icon(Path("test.go")) == "🐹"
        assert app._get_file_icon(Path("test.rs")) == "🦀"
        assert app._get_file_icon(Path("test.unknown")) == "📄"
    
    def test_move_down(self, temp_dir, mock_config):
        """Test cursor movement down."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.cursor_position = 0
        
        app._move_down()
        
        assert app.state.cursor_position == 1
    
    def test_move_down_stops_at_end(self, temp_dir, mock_config):
        """Test cursor doesn't go past the end."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        items = app._get_current_items()
        app.state.cursor_position = len(items) - 1
        
        app._move_down()
        
        assert app.state.cursor_position == len(items) - 1
    
    def test_move_up(self, temp_dir, mock_config):
        """Test cursor movement up."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.cursor_position = 2
        
        app._move_up()
        
        assert app.state.cursor_position == 1
    
    def test_move_up_stops_at_start(self, temp_dir, mock_config):
        """Test cursor doesn't go below 0."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.cursor_position = 0
        
        app._move_up()
        
        assert app.state.cursor_position == 0
    
    def test_toggle_select_file(self, temp_dir, mock_config):
        """Test toggling file selection."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        # Find a file (not directory)
        items = app._get_current_items()
        file_idx = None
        for i, item in enumerate(items):
            if item.is_file():
                file_idx = i
                break
        
        if file_idx is not None:
            app.state.cursor_position = file_idx
            
            # Select
            app._toggle_select()
            assert items[file_idx] in app.state.selected_files
            
            # Deselect
            app._toggle_select()
            assert items[file_idx] not in app.state.selected_files
    
    def test_select_all(self, temp_dir, mock_config):
        """Test selecting all files."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        app._select_all()
        
        items = app._get_current_items()
        file_count = sum(1 for item in items if item.is_file())
        
        assert len(app.state.selected_files) == file_count
    
    def test_deselect_all(self, temp_dir, mock_config):
        """Test deselecting all files."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app._select_all()
        
        app._deselect_all()
        
        assert len(app.state.selected_files) == 0
    
    def test_toggle_hidden(self, temp_dir, mock_config):
        """Test toggling hidden files visibility."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        assert app.state.show_hidden is False
        
        app._toggle_hidden()
        
        assert app.state.show_hidden is True
        
        app._toggle_hidden()
        
        assert app.state.show_hidden is False
    
    def test_back_from_results(self, temp_dir, mock_config):
        """Test going back from results view."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.current_view = "results"
        
        app._back()
        
        assert app.state.current_view == "files"
    
    def test_back_from_issue(self, temp_dir, mock_config):
        """Test going back from issue view."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.current_view = "issue"
        
        app._back()
        
        assert app.state.current_view == "results"
    
    def test_back_from_help(self, temp_dir, mock_config):
        """Test going back from help view."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.current_view = "help"
        
        app._back()
        
        assert app.state.current_view == "files"
    
    def test_show_help(self, temp_dir, mock_config):
        """Test showing help view."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        app._show_help()
        
        assert app.state.current_view == "help"
    
    def test_cycle_focus(self, temp_dir, mock_config):
        """Test cycling through focus presets."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        initial_focus = app.state.focus.copy()
        
        app._cycle_focus()
        
        # Focus should have changed
        assert app.state.focus != initial_focus or len(app.state.focus) == 1
    
    def test_quit(self, temp_dir, mock_config):
        """Test quit action."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app._running = True
        
        app._quit()
        
        assert app._running is False
    
    def test_go_to_top(self, temp_dir, mock_config):
        """Test going to top of list."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.cursor_position = 5
        app.state.scroll_offset = 3
        
        app._go_to_top()
        
        assert app.state.cursor_position == 0
        assert app.state.scroll_offset == 0
    
    def test_go_to_bottom(self, temp_dir, mock_config):
        """Test going to bottom of list."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.cursor_position = 0
        
        app._go_to_bottom()
        
        items = app._get_current_items()
        assert app.state.cursor_position == len(items) - 1
    
    def test_select_directory_changes_cwd(self, temp_dir, mock_config):
        """Test selecting a directory changes current working directory."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        # Find the subdir in items
        items = app._get_current_items()
        subdir_idx = None
        for i, item in enumerate(items):
            if item.is_dir() and item.name == "subdir":
                subdir_idx = i
                break
        
        if subdir_idx is not None:
            app.state.cursor_position = subdir_idx
            app._select()
            
            assert app.state.cwd.name == "subdir"
            assert app.state.cursor_position == 0
    
    def test_next_prev_issue(self, temp_dir, mock_config):
        """Test navigating between issues."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        app.state.current_view = "issue"
        app.state.current_file = "test.py"
        
        # Add mock results with multiple issues
        app.state.review_results["test.py"] = ReviewResult(
            summary="Test review",
            issues=[
                Issue(message="Issue 1", severity=Severity.HIGH, category=Category.BUG),
                Issue(message="Issue 2", severity=Severity.MEDIUM, category=Category.SECURITY),
                Issue(message="Issue 3", severity=Severity.LOW, category=Category.STYLE),
            ],
            score=70,
        )
        
        app.state.current_issue_idx = 0
        
        # Next
        app._next_issue()
        assert app.state.current_issue_idx == 1
        
        app._next_issue()
        assert app.state.current_issue_idx == 2
        
        # Should stop at end
        app._next_issue()
        assert app.state.current_issue_idx == 2
        
        # Prev
        app._prev_issue()
        assert app.state.current_issue_idx == 1
        
        app._prev_issue()
        assert app.state.current_issue_idx == 0
        
        # Should stop at start
        app._prev_issue()
        assert app.state.current_issue_idx == 0
    
    def test_export_results(self, temp_dir, mock_config):
        """Test exporting results to JSON."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        # Add some results
        app.state.review_results["test.py"] = ReviewResult(
            summary="Test review",
            issues=[
                Issue(
                    message="Test issue",
                    severity=Severity.HIGH,
                    category=Category.BUG,
                    line=10,
                    suggestion="Fix this",
                ),
            ],
            score=75,
        )
        
        app._export_results()
        
        output_path = temp_dir / "coderev-results.json"
        assert output_path.exists()
        
        import json
        content = json.loads(output_path.read_text())
        
        assert "test.py" in content
        assert content["test.py"]["score"] == 75
        assert len(content["test.py"]["issues"]) == 1
    
    def test_process_command_simple_mode(self, temp_dir, mock_config):
        """Test command processing in simple mode."""
        app = TUIApp(config=mock_config, start_path=temp_dir)
        
        # Test down command
        app.state.cursor_position = 0
        app._process_command("down")
        assert app.state.cursor_position == 1
        
        # Test up command
        app._process_command("up")
        assert app.state.cursor_position == 0
        
        # Test help command
        app._process_command("help")
        assert app.state.current_view == "help"
        
        # Test back command
        app._process_command("back")
        assert app.state.current_view == "files"


class TestRunTUI:
    """Tests for the run_tui function."""
    
    def test_run_tui_imports(self):
        """Test that run_tui can be imported."""
        from coderev.tui import run_tui
        assert callable(run_tui)
    
    @patch("coderev.tui.TUIApp")
    def test_run_tui_creates_app(self, mock_app_class):
        """Test that run_tui creates a TUIApp instance."""
        mock_app = MagicMock()
        mock_app_class.return_value = mock_app
        
        run_tui(simple_mode=True)
        
        mock_app_class.assert_called_once()
        mock_app.run_simple.assert_called_once()
