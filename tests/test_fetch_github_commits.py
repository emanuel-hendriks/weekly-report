"""Unit tests for weekly_recap/fetchers/fetch_github_commits.py (httpx version)"""

import json
from unittest.mock import patch, MagicMock

import pytest

from weekly_recap.fetchers.fetch_github_commits import (
    validate_date,
    validate_inputs,
    write_output,
)


class TestValidateDate:
    def test_valid_date(self):
        assert validate_date("2026-05-13") is True

    def test_valid_date_leap_year(self):
        assert validate_date("2024-02-29") is True

    def test_invalid_format_slash(self):
        assert validate_date("2026/05/13") is False

    def test_invalid_format_no_dash(self):
        assert validate_date("20260513") is False

    def test_invalid_date_month_13(self):
        assert validate_date("2026-13-01") is False

    def test_invalid_date_day_32(self):
        assert validate_date("2026-01-32") is False

    def test_empty_string(self):
        assert validate_date("") is False

    def test_not_a_date(self):
        assert validate_date("not-a-date") is False


class TestValidateInputs:
    def test_valid_inputs(self):
        assert validate_inputs("user", ["org1"], "2026-01-01", "2026-01-07") is None

    def test_empty_handle(self):
        result = validate_inputs("", ["org1"], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "github_handle" in result

    def test_whitespace_handle(self):
        result = validate_inputs("   ", ["org1"], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "github_handle" in result

    def test_empty_orgs_list(self):
        result = validate_inputs("user", [], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "orgs" in result

    def test_none_orgs(self):
        result = validate_inputs("user", None, "2026-01-01", "2026-01-07")
        assert result is not None

    def test_org_with_empty_string(self):
        result = validate_inputs("user", ["org1", ""], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "orgs[1]" in result

    def test_invalid_start_date(self):
        result = validate_inputs("user", ["org1"], "not-a-date", "2026-01-07")
        assert result is not None
        assert "start_date" in result

    def test_invalid_end_date(self):
        result = validate_inputs("user", ["org1"], "2026-01-01", "2026-13-07")
        assert result is not None
        assert "end_date" in result

    def test_missing_start_date(self):
        result = validate_inputs("user", ["org1"], "", "2026-01-07")
        assert result is not None
        assert "start_date" in result

    def test_missing_end_date(self):
        result = validate_inputs("user", ["org1"], "2026-01-01", "")
        assert result is not None
        assert "end_date" in result


class TestWriteOutput:
    def test_writes_json(self, tmp_path, monkeypatch):
        output_file = tmp_path / "reports" / ".cache" / "git-commits.json"
        monkeypatch.setattr(
            "weekly_recap.fetchers.fetch_github_commits.OUTPUT_FILE", output_file
        )
        commits = [{"sha": "abc1234", "message": "test"}]
        write_output(commits)
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data == commits

    def test_creates_directories(self, tmp_path, monkeypatch):
        output_file = tmp_path / "deep" / "nested" / "dir" / "commits.json"
        monkeypatch.setattr(
            "weekly_recap.fetchers.fetch_github_commits.OUTPUT_FILE", output_file
        )
        write_output([])
        assert output_file.exists()
