"""Tests for package metadata and imports."""

import importlib.metadata


def test_package_version():
    """Test that package version is accessible."""
    version = importlib.metadata.version("coderev")
    assert version is not None
    # Version should be in X.Y.Z format
    parts = version.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])


def test_package_metadata():
    """Test that package metadata is correct."""
    metadata = importlib.metadata.metadata("coderev")
    
    assert metadata["Name"] == "coderev"
    assert "AI" in metadata["Summary"] or "code review" in metadata["Summary"].lower()
    # License can be in License field or classifiers
    license_info = metadata.get("License") or ""
    classifiers = metadata.get_all("Classifier") or []
    has_mit = "MIT" in license_info or any("MIT" in c for c in classifiers)
    assert has_mit, "MIT license should be specified"
    assert "Khalil Limem" in metadata["Author-email"]


def test_cli_entry_point():
    """Test that CLI entry points are registered."""
    eps = importlib.metadata.entry_points(group="console_scripts")
    coderev_eps = [ep for ep in eps if ep.name == "coderev"]
    
    assert len(coderev_eps) == 1
    assert coderev_eps[0].value == "coderev.cli:main"


def test_core_imports():
    """Test that core modules can be imported."""
    from coderev import cli
    from coderev import reviewer
    from coderev import providers
    from coderev import output
    from coderev import config
    
    assert cli is not None
    assert reviewer is not None
    assert providers is not None
    assert output is not None
    assert config is not None


def test_optional_imports():
    """Test that optional modules exist."""
    from coderev import github
    from coderev import gitlab
    from coderev import bitbucket
    from coderev import cache
    from coderev import async_reviewer
    
    assert github is not None
    assert gitlab is not None
    assert bitbucket is not None
    assert cache is not None
    assert async_reviewer is not None
