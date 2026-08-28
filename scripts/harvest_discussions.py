#!/usr/bin/env python3
"""Harvest GitHub Discussions into committed static snapshots.

Static Data Covenant (kody-w/RAR CONSTITUTION.md Article XXIV): a visitor's
browser must never call api.github.com directly. This script is the CI-side
harvester — it makes the REST calls the frontend (src/js/discussions.js /
docs/index.html) used to make at page-load time, and commits the results as
static JSON in the exact shape the REST API returns, so the page can read a
snapshot from raw.githubusercontent.com instead.

Writes (relative to STATE_DIR):
  discussions/index.json            — array, shape of GET /repos/{o}/{r}/discussions
  discussions/{number}.json         — object, shape of GET .../discussions/{number}
  discussions/{number}_comments.json — array, shape of GET .../discussions/{number}/comments
  discussions/_meta.json            — harvest metadata (last_harvested, counts, disabled flag)

No auth required for public repos (uses GITHUB_TOKEN if present, for higher
rate limits only — never required).

Run via `make harvest-discussions` or the harvest-discussions.yml scheduled
workflow.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vm_config import OWNER, REPO, STATE_DIR

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REST_URL = f"https://api.github.com/repos/{OWNER}/{REPO}"
DISCUSSIONS_DIR = STATE_DIR / "discussions"


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"
    return headers


def _get(url: str):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_all_discussions():
    """Fetch all discussions with pagination. Returns None if Discussions is disabled."""
    all_discussions = []
    page = 1
    while True:
        url = f"{REST_URL}/discussions?per_page=100&page={page}"
        try:
            batch = _get(url)
        except urllib.error.HTTPError as e:
            if e.code == 410:
                print("Discussions are disabled for this repo — writing empty snapshot")
                return None
            print(f"API error {e.code} on page {page}", file=sys.stderr)
            break
        if not batch:
            break
        all_discussions.extend(batch)
        page += 1
        if len(batch) < 100:
            break
    return all_discussions


def fetch_comments(number: int):
    url = f"{REST_URL}/discussions/{number}/comments"
    try:
        return _get(url)
    except urllib.error.HTTPError as e:
        print(f"  comments fetch failed for #{number}: {e.code}", file=sys.stderr)
        return []


def main() -> int:
    print(f"Harvesting discussions for {OWNER}/{REPO}...")
    discussions = fetch_all_discussions()
    disabled = discussions is None
    discussions = discussions or []

    save_json(DISCUSSIONS_DIR / "index.json", discussions)
    print(f"  wrote discussions/index.json ({len(discussions)} discussions)")

    kept_numbers = set()
    for d in discussions:
        number = d.get("number")
        if number is None:
            continue
        kept_numbers.add(number)
        save_json(DISCUSSIONS_DIR / f"{number}.json", d)
        comments = fetch_comments(number)
        save_json(DISCUSSIONS_DIR / f"{number}_comments.json", comments)
        print(f"  wrote discussions/{number}.json + {number}_comments.json ({len(comments)} comments)")

    # Prune snapshot files for discussions that no longer exist (deleted/converted).
    if DISCUSSIONS_DIR.exists():
        for f in DISCUSSIONS_DIR.glob("*.json"):
            if f.name in ("index.json", "_meta.json"):
                continue
            stem = f.name.split("_")[0]
            if stem.endswith(".json"):
                stem = stem[: -len(".json")]
            if stem.isdigit() and int(stem) not in kept_numbers:
                print(f"  pruning stale {f.name}")
                f.unlink()

    save_json(DISCUSSIONS_DIR / "_meta.json", {
        "last_harvested": now_iso(),
        "discussion_count": len(discussions),
        "discussions_disabled": disabled,
        "owner": OWNER,
        "repo": REPO,
    })
    print("Harvest complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
