#!/usr/bin/env python3
"""Shared VM configuration — single source of truth for owner/repo/seed settings.

Every script imports from here instead of hardcoding values.
Reads from vm.json at repo root, with env var overrides.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VM_CONFIG_PATH = ROOT / "vm.json"


def load_vm_config() -> dict:
    """Load vm.json and apply environment variable overrides."""
    with open(VM_CONFIG_PATH) as f:
        config = json.load(f)

    # Env vars override vm.json
    config["owner"] = os.environ.get("OWNER", config.get("owner", ""))
    config["repo"] = os.environ.get("REPO", config.get("repo", ""))
    config["seed_owner"] = os.environ.get("SEED_OWNER", config.get("seed_owner", "kody-w"))
    config["seed_repo"] = os.environ.get("SEED_REPO", config.get("seed_repo", "rappterbook"))
    config["seed_branch"] = os.environ.get("SEED_BRANCH", config.get("seed_branch", "main"))

    return config


def detect_owner_repo() -> tuple:
    """Detect owner/repo from vm.json, env vars, or git remote."""
    config = load_vm_config()
    owner = config["owner"]
    repo = config["repo"]

    if not owner or not repo:
        # Try git remote
        try:
            import subprocess
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, cwd=ROOT
            )
            url = result.stdout.strip()
            # Parse github.com/owner/repo from HTTPS or SSH
            if "github.com" in url:
                parts = url.rstrip(".git").split("github.com")[-1].strip("/:")
                segments = parts.split("/")
                if len(segments) >= 2:
                    owner = owner or segments[0]
                    repo = repo or segments[1]
        except Exception:
            pass

    return owner, repo


def seed_base_url() -> str:
    """Return the raw.githubusercontent.com base URL for the seed repo."""
    config = load_vm_config()
    return (
        f"https://raw.githubusercontent.com/"
        f"{config['seed_owner']}/{config['seed_repo']}/{config['seed_branch']}"
    )


# Module-level constants for quick import
_config = load_vm_config()
OWNER, REPO = detect_owner_repo()
SEED_OWNER = _config["seed_owner"]
SEED_REPO = _config["seed_repo"]
SEED_BRANCH = _config["seed_branch"]
SEED_URL = seed_base_url()
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
