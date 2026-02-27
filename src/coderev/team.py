"""Team configuration sharing for CodeRev.

Enables teams to share configurations via:
- Local files (relative or absolute paths)
- URLs (HTTP/HTTPS to raw TOML configs)
- GitHub shorthand (gh:owner/repo/path.toml)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import toml

# Cache directory for remote configs
CACHE_DIR = Path.home() / ".cache" / "coderev" / "team-configs"

# GitHub raw URL template
GITHUB_RAW_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


class TeamConfigError(Exception):
    """Error related to team configuration."""
    pass


def parse_extends_url(extends: str) -> tuple[str, str]:
    """Parse the extends value into (type, location).
    
    Args:
        extends: The extends value from config.
        
    Returns:
        Tuple of (type, location) where type is 'local', 'url', or 'github'.
    """
    # GitHub shorthand: gh:owner/repo/path.toml or gh:owner/repo/path.toml@branch
    if extends.startswith("gh:"):
        return ("github", extends[3:])
    
    # HTTP/HTTPS URL
    if extends.startswith(("http://", "https://")):
        return ("url", extends)
    
    # Local path
    return ("local", extends)


def resolve_github_url(github_ref: str) -> str:
    """Resolve a GitHub shorthand to a raw URL.
    
    Args:
        github_ref: Format: owner/repo/path.toml or owner/repo/path.toml@branch
        
    Returns:
        Raw GitHub URL.
    """
    # Parse branch if specified
    branch = "main"
    if "@" in github_ref:
        github_ref, branch = github_ref.rsplit("@", 1)
    
    # Parse owner/repo/path
    parts = github_ref.split("/", 2)
    if len(parts) < 3:
        raise TeamConfigError(
            f"Invalid GitHub reference: {github_ref}. "
            "Format: owner/repo/path.toml or owner/repo/path.toml@branch"
        )
    
    owner, repo, path = parts
    
    return GITHUB_RAW_TEMPLATE.format(
        owner=owner,
        repo=repo,
        branch=branch,
        path=path,
    )


def fetch_remote_config(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch a remote TOML configuration.
    
    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.
        
    Returns:
        Parsed TOML configuration dict.
    """
    try:
        import urllib.request
        import ssl
        
        # Create a context that validates certificates
        context = ssl.create_default_context()
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CodeRev Team Config Fetcher"}
        )
        
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            content = response.read().decode("utf-8")
            
        return toml.loads(content)
    
    except Exception as e:
        raise TeamConfigError(f"Failed to fetch remote config from {url}: {e}")


def load_local_config(path: str, base_path: Path | None = None) -> dict[str, Any]:
    """Load a local TOML configuration.
    
    Args:
        path: Path to the config file (relative or absolute).
        base_path: Base path for resolving relative paths.
        
    Returns:
        Parsed TOML configuration dict.
    """
    config_path = Path(path)
    
    # Resolve relative paths
    if not config_path.is_absolute():
        if base_path:
            config_path = base_path / config_path
        else:
            config_path = Path.cwd() / config_path
    
    if not config_path.exists():
        raise TeamConfigError(f"Config file not found: {config_path}")
    
    try:
        with open(config_path) as f:
            return toml.load(f)
    except Exception as e:
        raise TeamConfigError(f"Failed to load config from {config_path}: {e}")


def get_cache_path(url: str) -> Path:
    """Get the cache path for a remote config URL.
    
    Args:
        url: Remote URL.
        
    Returns:
        Path to cached config file.
    """
    import hashlib
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "config.toml"
    
    return CACHE_DIR / f"{url_hash}_{filename}"


def cache_remote_config(url: str, config_data: dict[str, Any]) -> Path:
    """Cache a remote configuration locally.
    
    Args:
        url: Source URL.
        config_data: Configuration dict to cache.
        
    Returns:
        Path to cached file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path(url)
    
    with open(cache_path, "w") as f:
        toml.dump(config_data, f)
    
    return cache_path


def load_cached_config(url: str) -> dict[str, Any] | None:
    """Load a cached remote configuration if available.
    
    Args:
        url: Source URL to look up.
        
    Returns:
        Cached configuration dict, or None if not cached.
    """
    cache_path = get_cache_path(url)
    
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return toml.load(f)
        except Exception:
            return None
    
    return None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries.
    
    Override values take precedence. Lists are replaced, not merged.
    
    Args:
        base: Base configuration.
        override: Override configuration (takes precedence).
        
    Returns:
        Merged configuration.
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def resolve_extends(
    config_data: dict[str, Any],
    base_path: Path | None = None,
    use_cache: bool = True,
    visited: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve the 'extends' directive in a configuration.
    
    Supports recursive extends with cycle detection.
    
    Args:
        config_data: Configuration dict that may contain 'extends'.
        base_path: Base path for resolving relative local paths.
        use_cache: Use cached remote configs if available.
        visited: Set of already visited configs (for cycle detection).
        
    Returns:
        Resolved configuration with all extends merged.
    """
    if visited is None:
        visited = set()
    
    # Extract extends directive
    coderev_section = config_data.get("coderev", config_data)
    extends = coderev_section.pop("extends", None)
    
    if not extends:
        return config_data
    
    # Normalize extends to a list
    if isinstance(extends, str):
        extends = [extends]
    
    # Start with empty base
    merged_base: dict[str, Any] = {}
    
    for extend_ref in extends:
        # Check for cycles
        if extend_ref in visited:
            raise TeamConfigError(f"Circular extends detected: {extend_ref}")
        visited.add(extend_ref)
        
        # Parse the extends reference
        ref_type, location = parse_extends_url(extend_ref)
        
        # Load the extended config
        if ref_type == "github":
            url = resolve_github_url(location)
            
            # Try cache first if enabled
            parent_config = None
            if use_cache:
                parent_config = load_cached_config(url)
            
            if parent_config is None:
                parent_config = fetch_remote_config(url)
                cache_remote_config(url, parent_config)
        
        elif ref_type == "url":
            # Try cache first if enabled
            parent_config = None
            if use_cache:
                parent_config = load_cached_config(location)
            
            if parent_config is None:
                parent_config = fetch_remote_config(location)
                cache_remote_config(location, parent_config)
        
        else:  # local
            parent_config = load_local_config(location, base_path)
        
        # Recursively resolve extends in parent
        parent_config = resolve_extends(
            parent_config,
            base_path=Path(location).parent if ref_type == "local" else None,
            use_cache=use_cache,
            visited=visited.copy(),
        )
        
        # Merge into base
        merged_base = deep_merge(merged_base, parent_config)
    
    # Finally, merge current config on top
    return deep_merge(merged_base, config_data)


def sync_team_config(
    extends_ref: str,
    output_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Sync (download and cache) a team configuration.
    
    Args:
        extends_ref: The extends reference (url, gh:..., or local path).
        output_path: Optional path to write the synced config.
        force: Force re-download even if cached.
        
    Returns:
        Path to the synced/cached config file.
    """
    ref_type, location = parse_extends_url(extends_ref)
    
    if ref_type == "local":
        local_path = Path(location)
        if not local_path.is_absolute():
            local_path = Path.cwd() / local_path
        
        if output_path:
            import shutil
            shutil.copy(local_path, output_path)
            return output_path
        return local_path
    
    # Resolve URL
    if ref_type == "github":
        url = resolve_github_url(location)
    else:
        url = location
    
    # Check cache unless forcing
    cache_path = get_cache_path(url)
    if not force and cache_path.exists():
        if output_path:
            import shutil
            shutil.copy(cache_path, output_path)
            return output_path
        return cache_path
    
    # Fetch and cache
    config_data = fetch_remote_config(url)
    cached = cache_remote_config(url, config_data)
    
    if output_path:
        import shutil
        shutil.copy(cached, output_path)
        return output_path
    
    return cached


def list_cached_configs() -> list[dict[str, Any]]:
    """List all cached team configurations.
    
    Returns:
        List of dicts with cache info (path, size, modified time).
    """
    if not CACHE_DIR.exists():
        return []
    
    configs = []
    for path in CACHE_DIR.glob("*.toml"):
        stat = path.stat()
        configs.append({
            "path": str(path),
            "name": path.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    
    return sorted(configs, key=lambda x: x["modified"], reverse=True)


def clear_config_cache() -> int:
    """Clear all cached team configurations.
    
    Returns:
        Number of cache files removed.
    """
    if not CACHE_DIR.exists():
        return 0
    
    count = 0
    for path in CACHE_DIR.glob("*.toml"):
        path.unlink()
        count += 1
    
    return count


def create_team_config_template(
    output_path: Path,
    include_examples: bool = True,
) -> None:
    """Create a template team configuration file.
    
    Args:
        output_path: Where to write the template.
        include_examples: Include example settings and comments.
    """
    template = '''# Team CodeRev Configuration
# Share this file via GitHub, a URL, or locally.
# Team members can extend it in their .coderev.toml:
#   [coderev]
#   extends = "gh:myorg/configs/coderev-team.toml"

[coderev]
# Model to use for all team members
model = "claude-3-sonnet-20240229"

# Team's standard focus areas
focus = ["bugs", "security", "performance"]

# Common ignore patterns for the project
ignore_patterns = [
    "*.test.py",
    "*.spec.ts",
    "*_test.go",
    "migrations/*",
    "vendor/*",
    "node_modules/*",
    "*.min.js",
    "*.min.css",
]

# Maximum file size for review (bytes)
max_file_size = 100000

# Enable language detection
language_hints = true

# Optional: Custom review rules
# [coderev.rules]
# max_function_length = 50
# require_docstrings = true
# banned_patterns = ["TODO", "FIXME"]
'''
    
    output_path.write_text(template)
