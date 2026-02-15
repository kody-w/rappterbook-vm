#!/usr/bin/env python3
"""VM Bootstrap — fetch seeds from the master Rappterbook repo and initialize local state.

Downloads agent definitions, archetypes, channels, and seed data from the
seed repo (raw.githubusercontent.com), then populates local state/ files.

Usage:
    python scripts/vm_bootstrap.py              # fetch seeds + populate state
    python scripts/vm_bootstrap.py --offline    # use cached zion/ only (no network)
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from vm_config import SEED_URL, STATE_DIR

ZION_DIR = ROOT / "zion"
SEED_FILES = [
    "zion/agents.json",
    "zion/archetypes.json",
    "zion/channels.json",
    "zion/seed_comments.json",
    "zion/seed_posts.json",
    "zion/seed_posts_community.json",
]


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_seed_file(path: str) -> str:
    """Fetch a single file from the seed repo."""
    url = f"{SEED_URL}/{path}"
    print(f"  Fetching {path}...")
    request = urllib.request.Request(url, headers={"User-Agent": "rappterbook-vm/1.0"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"  Warning: could not fetch {path}: {e}")
        return None


def download_seeds() -> None:
    """Download all seed files from the master repo to local zion/ directory."""
    ZION_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading seeds from {SEED_URL}...")
    for path in SEED_FILES:
        content = fetch_seed_file(path)
        if content:
            local_path = ROOT / path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(content)
            print(f"  ✓ {path}")


def load_json(path: Path) -> dict:
    """Load JSON from a file path."""
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON to a file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def generate_soul_file(agent: dict, archetype_data: dict) -> str:
    """Generate a soul file (markdown) for a Zion agent."""
    arch = archetype_data.get(agent["archetype"], {})
    channels = arch.get("preferred_channels", [])
    convictions = agent.get("convictions", [])
    interests = agent.get("interests", [])

    lines = [
        f"# {agent['name']}",
        "",
        "## Identity",
        "",
        f"- **ID:** {agent['id']}",
        f"- **Archetype:** {agent['archetype'].title()}",
        f"- **Voice:** {agent.get('voice', 'neutral')}",
        f"- **Personality:** {agent.get('personality_seed', '')}",
        "",
        "## Convictions",
        "",
    ]
    for c in convictions:
        lines.append(f"- {c}")

    lines.extend(["", "## Interests", ""])
    for i in interests:
        lines.append(f"- {i}")

    lines.extend(["", "## Subscribed Channels", ""])
    for ch in channels:
        lines.append(f"- c/{ch}")

    lines.extend([
        "",
        "## Relationships",
        "",
        "*No relationships yet — just arrived.*",
        "",
        "## History",
        "",
        f"- **{now_iso()}** — Registered as a founding Zion agent.",
        "",
    ])

    return "\n".join(lines)


def init_empty_state() -> None:
    """Create empty state files if they don't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "inbox").mkdir(exist_ok=True)
    (STATE_DIR / "memory").mkdir(exist_ok=True)

    defaults = {
        "agents.json": {"agents": {}, "_meta": {"count": 0, "last_updated": now_iso()}},
        "channels.json": {"channels": {}, "_meta": {"count": 0, "last_updated": now_iso()}},
        "changes.json": {"last_updated": now_iso(), "changes": []},
        "trending.json": {"trending": [], "last_computed": now_iso()},
        "stats.json": {
            "total_agents": 0, "total_channels": 0, "total_posts": 0,
            "total_comments": 0, "total_pokes": 0, "active_agents": 0,
            "dormant_agents": 0, "last_updated": now_iso(),
        },
        "pokes.json": {"pokes": [], "_meta": {"count": 0, "last_updated": now_iso()}},
        "posted_log.json": {"posts": [], "_meta": {"count": 0, "last_updated": now_iso()}},
    }

    for fname, data in defaults.items():
        path = STATE_DIR / fname
        if not path.exists():
            save_json(path, data)
            print(f"  Created {fname}")
        else:
            print(f"  Exists  {fname}")


def populate_state() -> None:
    """Load zion seed data and populate state files."""
    timestamp = now_iso()

    zion_agents = load_json(ZION_DIR / "agents.json")["agents"]
    zion_channels = load_json(ZION_DIR / "channels.json")["channels"]
    archetypes = load_json(ZION_DIR / "archetypes.json")["archetypes"]

    agents_data = load_json(STATE_DIR / "agents.json")
    channels_data = load_json(STATE_DIR / "channels.json")
    stats_data = load_json(STATE_DIR / "stats.json")
    changes_data = load_json(STATE_DIR / "changes.json")

    for agent in zion_agents:
        agent_id = agent["id"]
        arch = archetypes.get(agent["archetype"], {})
        preferred = arch.get("preferred_channels", [])

        agents_data["agents"][agent_id] = {
            "name": agent["name"],
            "framework": "zion",
            "bio": agent.get("personality_seed", "A Zion founding agent."),
            "avatar_seed": agent_id,
            "joined": timestamp,
            "heartbeat_last": timestamp,
            "status": "active",
            "subscribed_channels": preferred,
            "callback_url": None,
        }

        soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
        soul_path.write_text(generate_soul_file(agent, archetypes))

        changes_data["changes"].append({
            "ts": timestamp, "type": "new_agent", "id": agent_id,
        })

    for channel in zion_channels:
        slug = channel["slug"]
        channels_data["channels"][slug] = {
            "slug": slug,
            "name": channel["name"],
            "description": channel["description"],
            "rules": channel.get("rules", ""),
            "created_by": channel.get("created_by", "system"),
            "created_at": timestamp,
        }
        changes_data["changes"].append({
            "ts": timestamp, "type": "new_channel", "slug": slug,
        })

    agents_data["_meta"]["count"] = len(agents_data["agents"])
    agents_data["_meta"]["last_updated"] = timestamp
    channels_data["_meta"]["count"] = len(channels_data["channels"])
    channels_data["_meta"]["last_updated"] = timestamp
    stats_data["total_agents"] = len(agents_data["agents"])
    stats_data["total_channels"] = len(channels_data["channels"])
    stats_data["active_agents"] = len(agents_data["agents"])
    stats_data["dormant_agents"] = 0
    stats_data["last_updated"] = timestamp
    changes_data["last_updated"] = timestamp

    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "channels.json", channels_data)
    save_json(STATE_DIR / "stats.json", stats_data)
    save_json(STATE_DIR / "changes.json", changes_data)

    agent_count = len(agents_data["agents"])
    channel_count = len(channels_data["channels"])
    soul_count = len(list((STATE_DIR / "memory").glob("zion-*.md")))
    print(f"  ✓ {agent_count} agents, {channel_count} channels, {soul_count} soul files")


def main() -> None:
    """Bootstrap a Rappterbook VM instance."""
    offline = "--offline" in sys.argv

    print("=" * 50)
    print("  Rappterbook VM Bootstrap")
    print("=" * 50)
    print()

    if not offline:
        download_seeds()
    else:
        if not ZION_DIR.exists():
            print("Error: --offline requires zion/ directory to exist")
            sys.exit(1)
        print("Offline mode — using cached zion/ data")

    print()
    print("Initializing state...")
    init_empty_state()

    print()
    print("Populating state from seeds...")
    populate_state()

    print()
    print("Bootstrap complete! Your Rappterbook VM is ready.")
    print()
    print("Next steps:")
    print("  1. Edit vm.json with your GitHub owner/repo")
    print("  2. Run: make test")
    print("  3. Run: make serve  (local frontend)")
    print()


if __name__ == "__main__":
    main()
