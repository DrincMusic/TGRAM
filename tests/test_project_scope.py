import re
from pathlib import Path

from rlmgraph.interactive_workspace import InteractiveProjectWorkspaceController
from rlmgraph.store import SQLiteGraphStore


def test_public_readme_local_links_exist():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+)\)", readme):
        if "://" not in target and not target.startswith("#"):
            assert (root / target.split("#")[0]).is_file(), target


def test_fresh_install_has_no_connected_projects_or_conversations(tmp_path):
    store = SQLiteGraphStore(tmp_path / "fresh.db")
    store.initialize()
    assert store.projects() == []
    assert store.chat_sessions() == []
    assert InteractiveProjectWorkspaceController(store).options()["projects"] == []
