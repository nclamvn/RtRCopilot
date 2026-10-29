"""Bounded offline research port. It never accepts URLs or opens a socket."""
import hashlib
import json
from pathlib import Path

from .store import WorkspaceError


class OfflineResearch:
    def __init__(self, enabled):
        self.sources = []
        if enabled:
            path = Path(__file__).resolve().parent / "assets" / "research_fixtures.json"
            if path.is_file():
                self.sources = json.loads(path.read_text())

    def _available(self):
        if not self.sources:
            raise WorkspaceError("research_fixture_unavailable", 503)

    def search(self, query):
        self._available()
        words = set(query.casefold().split())
        if not words or len(query) > 500:
            raise WorkspaceError("invalid_research_query")
        matches = [s for s in self.sources if any(w in (s["title"] + " " + s["content"]).casefold() for w in words)]
        return {"fixture": True, "results": [{k: s[k] for k in ("id", "title", "url", "as_of", "provenance")} | {"snippet": s["content"][:240]} for s in matches[:8]]}

    def read(self, source_id):
        self._available()
        for source in self.sources:
            if source["id"] == source_id:
                return {"fixture": True, "source": dict(source, sha256=hashlib.sha256(source["content"].encode()).hexdigest())}
        raise WorkspaceError("research_source_not_found", 404)

    def import_source(self, store, owner, workspace_id, source_id, run_id=None):
        store.items(owner, workspace_id, "files")
        source = self.read(source_id)["source"]
        provenance = {k: source[k] for k in ("url", "as_of", "sha256", "provenance", "id", "title")}
        for item in store.items(owner, workspace_id, "files"):
            if item["provenance"] == provenance:
                return item
        return store.upload_bytes(owner, workspace_id, source["id"] + ".md", source["content"].encode(), provenance=provenance, run_id=run_id)
