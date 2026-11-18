"""Merge a shipped Codex or omp preset to stdout; setup.sh owns backup and replacement."""
from __future__ import annotations

import sys
from pathlib import Path


def codex_defaults(original: str, preset: str, keys: list[str]) -> str:
    try:
        import tomllib
    except ImportError:
        sys.exit("Codex preset requires Python 3.11+ (tomllib)")
    configured = tomllib.loads(original)
    profiles = configured.get("permissions", {})
    additions = []
    # The shipped preset has one root assignment per line. Keep its TOML value syntax.
    for line in preset.splitlines():
        for key, value in tomllib.loads(line).items():
            if key == "default_permissions" and not (isinstance(profiles, dict) and isinstance(profiles.get(value), dict)):
                continue
            if key not in configured and (not keys or key in keys):
                additions.append(line + "\n")
    return "".join(additions) + original


def omp_settings(original: str, preset: str) -> str:
    try:
        import yaml
    except ImportError:
        sys.exit("omp preset requires PyYAML")
    try:
        current = yaml.safe_load(original)
        patch = yaml.safe_load(preset)
    except yaml.YAMLError:
        sys.exit("invalid YAML; omp preset not applied")
    if current is None:
        current = {}
    if not isinstance(current, dict) or not isinstance(patch, dict):
        sys.exit("expected YAML settings mappings; omp preset not applied")
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key].update(value)
        else:
            current[key] = value
    return yaml.safe_dump(current, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    config, preset = map(Path, sys.argv[1:3])
    try:
        original = config.read_text(encoding="utf-8")
        defaults = preset.read_text(encoding="utf-8")
        merged = (codex_defaults(original, defaults, sys.argv[3:]) if config.suffix == ".toml"
                  else omp_settings(original, defaults))
        sys.stdout.write(merged)
    except (OSError, ValueError) as error:
        sys.exit(f"cannot merge {preset.name} into {config}: {error}")
