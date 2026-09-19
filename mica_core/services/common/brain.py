from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from hashlib import blake2b
from math import sqrt
from pathlib import Path
from typing import Any


class MarkdownBrain:
    """Markdown is authoritative; SQLite holds rebuildable FTS and vector indexes.

    The vector is a deterministic local hashed token/trigram embedding. It has
    no model download, network call, or data egress and helps recall nearby
    spellings where FTS finds no exact term.
    """

    VECTOR_DIMENSIONS = 192
    CHUNK_SIZE = 1400
    CHUNK_OVERLAP = 180

    def __init__(self, root: str | Path | None = None, index_path: str | Path | None = None):
        self.root = Path(root or os.getenv("BRAIN_DIR", "/data/brain"))
        self.index_path = Path(index_path or os.getenv("INDEX_PATH", "/data/index/brain.sqlite3"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, title: str, body: str, metadata: dict[str, Any] | None = None) -> dict[str, str]:
        kind = re.sub(r"[^a-z0-9_-]", "-", kind.lower()).strip("-") or "notes"
        document_id = uuid.uuid4().hex
        created = datetime.now(UTC).isoformat()
        doc_dir = self.root / kind
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = doc_dir / f"{created[:10]}-{document_id[:10]}.md"
        frontmatter = {"id": document_id, "kind": kind, "title": title.strip()[:160], "created_at": created, **(metadata or {})}
        # Keep supplied evidence bytes intact in the Markdown source.  Callers
        # that want presentation trimming do that themselves; a captured
        # Docker/host-agent error must not be silently rewritten on disk.
        path.write_text("---\n" + json.dumps(frontmatter, ensure_ascii=False) + "\n---\n\n" + str(body), encoding="utf-8")
        self.reindex()
        return {"id": document_id, "path": str(path), "created_at": created}

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.startswith("---\n"):
                return None
            _marker, meta_raw, body = raw.split("---\n", 2)
            meta = json.loads(meta_raw)
            if not isinstance(meta, dict):
                return None
            return {**meta, "body": body.strip(), "path": str(path)}
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def documents(self) -> list[dict[str, Any]]:
        docs = [self._read(path) for path in self.root.rglob("*.md")]
        return sorted((doc for doc in docs if doc), key=lambda doc: doc.get("created_at", ""), reverse=True)

    @classmethod
    def _chunks(cls, text: str, kind: str = "", language: str = "python") -> list[tuple[int, int, str]]:
        """Chunk with Chonkie in containers and a compatible local fallback."""
        if not text:
            return [(0, 0, "")]
        try:
            from chonkie import CodeChunker, TokenChunker

            if kind == "code":
                chunks = CodeChunker(tokenizer="character", chunk_size=cls.CHUNK_SIZE, language=language)(text)
            else:
                chunks = TokenChunker(
                    tokenizer="character", chunk_size=cls.CHUNK_SIZE,
                    chunk_overlap=cls.CHUNK_OVERLAP,
                )(text)
            return [(int(chunk.start_index), int(chunk.end_index), str(chunk.text)) for chunk in chunks]
        except ImportError:
            step = cls.CHUNK_SIZE - cls.CHUNK_OVERLAP
            return [
                (start, min(len(text), start + cls.CHUNK_SIZE), text[start:start + cls.CHUNK_SIZE])
                for start in range(0, len(text), step)
            ]

    @classmethod
    def _vector(cls, text: str) -> list[float]:
        """Build a compact deterministic local feature vector without an API."""
        features = re.findall(r"[\w-]+", text.lower())
        normalized = " ".join(features)
        weighted = [(feature, 2.0) for feature in features]
        weighted.extend((normalized[index:index + 3], 0.35) for index in range(max(0, len(normalized) - 2)))
        vector = [0.0] * cls.VECTOR_DIMENSIONS
        for feature, weight in weighted:
            digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % cls.VECTOR_DIMENSIONS
            vector[slot] += (1.0 if digest[4] & 1 else -1.0) * weight
        length = sqrt(sum(value * value for value in vector))
        return [value / length for value in vector] if length else vector

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right)) if len(left) == len(right) else 0.0

    def reindex(self) -> int:
        docs = self.documents()
        chunks: list[tuple[str, str, str, str, str, str, int, int]] = []
        for doc in docs:
            document_id = str(doc.get("id", ""))
            body = str(doc.get("body", ""))
            for index, (start, end, content) in enumerate(self._chunks(body, str(doc.get("kind", "")), str(doc.get("language", "python")))):
                chunks.append((
                    f"{document_id}:{index}", document_id, str(doc.get("kind", "")),
                    str(doc.get("title", "")), content, str(doc.get("path", "")), start, end,
                ))
        conn = sqlite3.connect(self.index_path)
        try:
            # The SQLite index is intentionally disposable. Recreating these
            # tables also performs schema migration from the old whole-doc index.
            conn.execute("DROP TABLE IF EXISTS documents")
            conn.execute("DROP TABLE IF EXISTS document_chunks")
            conn.execute("DROP TABLE IF EXISTS document_vectors")
            conn.execute("CREATE VIRTUAL TABLE document_chunks USING fts5(chunk_id UNINDEXED, document_id UNINDEXED, kind UNINDEXED, title, body, path UNINDEXED, start_offset UNINDEXED, end_offset UNINDEXED)")
            conn.execute("CREATE TABLE document_vectors (chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, vector TEXT NOT NULL, body TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL)")
            conn.executemany("INSERT INTO document_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", chunks)
            conn.executemany("INSERT INTO document_vectors VALUES (?, ?, ?, ?, ?, ?)", [
                (chunk_id, document_id, json.dumps(self._vector(f"{title}\n{body}"), separators=(",", ":")), body, start, end)
                for chunk_id, document_id, _kind, title, body, _path, start, end in chunks
            ])
            conn.commit()
        finally:
            conn.close()
        return len(docs)

    @staticmethod
    def _matches_filters(
        doc: dict[str, Any], domain_id: str | None = None, kind: str | None = None,
    ) -> bool:
        return (
            (not domain_id or str(doc.get("domain_id", "")) == domain_id)
            and (not kind or str(doc.get("kind", "")) == kind)
        )

    def search(
        self, query: str, limit: int = 8, *, domain_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        self.reindex()
        bounded_limit = max(1, min(limit, 30))
        results: list[dict[str, Any]] = []
        try:
            terms = re.findall(r"[\w-]+", query)
            fts_query = " OR ".join(terms) or query
            conn = sqlite3.connect(self.index_path)
            try:
                rows = conn.execute("SELECT chunk_id, document_id, kind, title, snippet(document_chunks, 4, '<b>', '</b>', '…', 18), path, start_offset, end_offset FROM document_chunks WHERE document_chunks MATCH ? ORDER BY rank LIMIT ?", (fts_query, bounded_limit * 3)).fetchall()
            finally:
                conn.close()
            seen_docs: set[str] = set()
            documents = {str(doc.get("id", "")): doc for doc in self.documents()}
            for row in rows:
                if not self._matches_filters(documents.get(str(row[1]), {}), domain_id, kind):
                    continue
                if row[1] in seen_docs or len(results) >= bounded_limit:
                    continue
                results.append({"chunk_id": row[0], "id": row[1], "kind": row[2], "title": row[3], "snippet": row[4], "path": row[5], "start_offset": int(row[6]), "end_offset": int(row[7]), "confidence": "high"})
                seen_docs.add(row[1])
        except sqlite3.OperationalError:
            needle = query.lower()
            results = [{"id": str(doc.get("id", "")), "kind": str(doc.get("kind", "")), "title": str(doc.get("title", "")), "snippet": str(doc.get("body", ""))[:220], "path": str(doc.get("path", "")), "confidence": "high"} for doc in self.documents() if self._matches_filters(doc, domain_id, kind) and needle in (str(doc.get("title", "")) + " " + str(doc.get("body", ""))).lower()][:bounded_limit]

        # Keep exact full-text hits first and augment them with local vector
        # recall. Result content always comes from the Markdown source.
        docs = {str(doc.get("id", "")): doc for doc in self.documents()}
        try:
            conn = sqlite3.connect(self.index_path)
            try:
                vector_rows = conn.execute("SELECT chunk_id, document_id, vector, body, start_offset, end_offset FROM document_vectors").fetchall()
            finally:
                conn.close()
            candidates: list[tuple[float, str, str, str, int, int]] = []
            query_vector = self._vector(query)
            for chunk_id, document_id, encoded, body, start, end in vector_rows:
                try:
                    score = self._cosine(query_vector, json.loads(encoded))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if score > 0:
                    candidates.append((score, str(chunk_id), str(document_id), str(body), int(start), int(end)))
            seen = {result["id"] for result in results}
            for _score, chunk_id, document_id, body, start, end in sorted(candidates, reverse=True):
                if len(results) >= bounded_limit or document_id in seen or document_id not in docs:
                    continue
                doc = docs[document_id]
                if not self._matches_filters(doc, domain_id, kind):
                    continue
                results.append({"chunk_id": chunk_id, "id": document_id, "kind": str(doc.get("kind", "")), "title": str(doc.get("title", "")), "snippet": body[:220], "path": str(doc.get("path", "")), "start_offset": start, "end_offset": end, "confidence": "medium"})
                seen.add(document_id)
        except sqlite3.OperationalError:
            pass
        return results[:bounded_limit]

    def update_metadata(self, document_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update frontmatter without changing the authoritative Markdown body."""
        for path in self.root.rglob("*.md"):
            doc = self._read(path)
            if not doc or str(doc.get("id", "")) != document_id:
                continue
            raw = path.read_text(encoding="utf-8")
            _marker, meta_raw, body = raw.split("---\n", 2)
            metadata = json.loads(meta_raw)
            metadata.update(updates)
            path.write_text(
                "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + body,
                encoding="utf-8",
            )
            self.reindex()
            return self._read(path)
        return None

    def graph(self) -> dict[str, list[dict[str, str]]]:
        docs = self.documents()
        nodes = [{"id": str(doc.get("id", "")), "label": str(doc.get("title", "")), "kind": str(doc.get("kind", ""))} for doc in docs]
        ids = {node["id"] for node in nodes}
        links: list[dict[str, str]] = []
        for doc in docs:
            for target in re.findall(r"\[\[([0-9a-f]{32})\]\]", str(doc.get("body", ""))):
                if target in ids:
                    links.append({"source": str(doc.get("id", "")), "target": target})
        return {"nodes": nodes, "links": links}
