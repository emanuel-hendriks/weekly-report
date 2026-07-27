"""Tests for weekly_recap/cli.py — CLI entry point dispatch."""

import sys
from unittest.mock import patch, MagicMock

import pytest

from weekly_recap.cli import main, print_usage


class TestHelp:
    """Test --help and -h flags show usage and exit 0."""

    def test_help_flag_exits_zero(self, capsys):
        with patch.object(sys, "argv", ["weekly-recap", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "preflight" in captured.out
        assert "generate" in captured.out

    def test_h_flag_exits_zero(self, capsys):
        with patch.object(sys, "argv", ["weekly-recap", "-h"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "preflight" in captured.out
        assert "generate" in captured.out

    def test_no_arguments_shows_help_exits_zero(self, capsys):
        with patch.object(sys, "argv", ["weekly-recap"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "preflight" in captured.out
        assert "generate" in captured.out


class TestPreflightSubcommand:
    """Test that 'preflight' subcommand invokes weekly_recap.preflight.main."""

    @patch("weekly_recap.preflight.main", return_value=0)
    def test_preflight_invokes_preflight_main(self, mock_preflight_main):
        with patch.object(sys, "argv", ["weekly-recap", "preflight"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        mock_preflight_main.assert_called_once()

    @patch("weekly_recap.preflight.main", return_value=1)
    def test_preflight_propagates_exit_code(self, mock_preflight_main):
        with patch.object(sys, "argv", ["weekly-recap", "preflight"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        mock_preflight_main.assert_called_once()


class TestGenerateSubcommand:
    """Test that 'generate' subcommand invokes weekly_recap.run_recap.main."""

    @patch("weekly_recap.run_recap.main")
    def test_generate_invokes_run_recap_main(self, mock_run_recap_main):
        with patch.object(sys, "argv", ["weekly-recap", "generate"]):
            main()

        mock_run_recap_main.assert_called_once()

    @patch("weekly_recap.run_recap.main")
    def test_generate_passes_date_args_via_sys_argv(self, mock_run_recap_main):
        captured_argv = []

        def capture_argv():
            captured_argv.extend(sys.argv)

        mock_run_recap_main.side_effect = capture_argv

        with patch.object(sys, "argv", ["weekly-recap", "generate", "2026-05-09", "2026-05-15"]):
            main()

        mock_run_recap_main.assert_called_once()
        # sys.argv should have been set for run_recap before it was called
        assert captured_argv == ["weekly-recap-generate", "2026-05-09", "2026-05-15"]


class TestUnknownSubcommand:
    """Test that unknown subcommands exit with code 1."""

    def test_unknown_subcommand_exits_one(self, capsys):
        with patch.object(sys, "argv", ["weekly-recap", "foo"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Unknown subcommand: foo" in captured.err
        assert "Usage" in captured.out

    def test_another_unknown_subcommand_exits_one(self, capsys):
        with patch.object(sys, "argv", ["weekly-recap", "bar"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Unknown subcommand: bar" in captured.err


class TestPrintUsage:
    """Test the print_usage helper function."""

    def test_print_usage_contains_commands(self, capsys):
        print_usage()
        captured = capsys.readouterr()
        assert "Usage: weekly-recap" in captured.out
        assert "preflight" in captured.out
        assert "generate" in captured.out
