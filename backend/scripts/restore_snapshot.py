"""
LAKO — Restore storage from the private GitHub data repo (container start).
No-op unless GITHUB_TOKEN + GITHUB_DATA_REPO are set. Exits non-zero on a
public repo or corrupt snapshot so a bad config fails loudly, not silently
with an empty knowledge base.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services import github_persist


def main() -> None:
    if not github_persist.enabled():
        print("[LAKO] GitHub persistence not configured — storage is ephemeral.")
        return
    print("[LAKO] Restore:", github_persist.restore())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit(f"[LAKO] Restore failed: {exc}")
