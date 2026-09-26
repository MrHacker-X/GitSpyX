"""Unit tests for validation, slugs and formatting helpers."""

import pytest

from gitspyx.utils import (
    build_output_slug,
    format_count,
    format_delta,
    is_valid_github_login,
    parse_repo_slug,
    safe_str,
    slugify,
)


# --- GitHub identifier validation (#19, #20) ---------------------------------

@pytest.mark.parametrize("name", ["torvalds", "MrHacker-X", "a", "user123", "some-org"])
def test_valid_logins(name):
    assert is_valid_github_login(name)


@pytest.mark.parametrize("name", [
    "", "  ", "-leading", "trailing-", "double--hyphen", "a" * 40,
    "has space", "user/name", "user.name", "user!", None, 123,
])
def test_invalid_logins(name):
    assert not is_valid_github_login(name)


@pytest.mark.parametrize("raw,expected", [
    ("torvalds/linux", ("torvalds", "linux")),
    (" torvalds / linux ", ("torvalds", "linux")),
    ("MrHacker-X/GitSpyX", ("MrHacker-X", "GitSpyX")),
])
def test_parse_repo_slug_valid(raw, expected):
    assert parse_repo_slug(raw) == expected


@pytest.mark.parametrize("raw", [
    "repo", "owner/", "/repo", "owner/repo/extra", "owner//repo",
    "", "   ", "a/b/c/d", "owner/ repo with space", "-bad/repo", "owner/re po",
])
def test_parse_repo_slug_invalid(raw):
    with pytest.raises(ValueError):
        parse_repo_slug(raw)


# --- slugify / path safety (#21) ----------------------------------------------

def test_slug_no_path_separators():
    for evil in ["../../etc/passwd", "..\\..\\windows\\system32", "a/b", "a\\b", "/abs/path"]:
        result = slugify(evil)
        assert "/" not in result and "\\" not in result


def test_slug_traversal_is_inert():
    assert slugify("../..") == "etc" or "/" not in slugify("../..")


def test_slug_unicode():
    result = slugify("héllo wörld")
    assert result == "héllo wörld"  # unicode kept; still filename-safe


def test_slug_empty_and_punctuation_only():
    assert slugify("") == "gitspyx_output"
    assert slugify("///") == "gitspyx_output"
    assert slugify("!!!") == "gitspyx_output"
    assert slugify("...") == "gitspyx_output"


def test_slug_dots_punctuation_stripped():
    assert slugify("...name") == "name"


def test_slug_very_long_input():
    result = slugify("a" * 500)
    assert len(result) <= 60


def test_slug_windows_reserved():
    assert slugify("CON") == "_CON"
    assert slugify("nul") == "_nul"
    assert slugify("COM1") == "_COM1"
    assert slugify("LPT9") == "_LPT9"


def test_slug_normal_names_untouched():
    assert slugify("torvalds") == "torvalds"
    assert slugify("My Cool Repo.v2") == "My Cool Repo.v2"
    assert slugify("john doe") == "john doe"


def test_build_output_slug():
    assert build_output_slug("repo", "torvalds/linux") == "repo-torvalds_linux"
    assert build_output_slug("search", "john doe") == "search-john_doe"


# --- formatting ----------------------------------------------------------------

def test_format_count_variants():
    assert format_count(1234) == "1,234"
    assert format_count(None) == "0"
    assert format_count("bad") == "0"
    assert format_count(0) == "0"
    assert format_count(250000) == "250,000"


def test_format_delta():
    assert format_delta(0.0004).endswith("ms")
    assert format_delta(5) == "5.0s"
    assert "m" in format_delta(90)


def test_safe_str():
    assert safe_str(None) == "N/A"
    assert safe_str("") == "N/A"
    assert safe_str("  ") == "N/A"
    assert safe_str("hello") == "hello"
    assert safe_str(None, "—") == "—"
    assert safe_str(42) == "42"
