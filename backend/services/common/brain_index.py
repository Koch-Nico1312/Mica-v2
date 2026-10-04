"""Transactional, incremental derived indexes for authoritative Markdown."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable


SCHEMA_VERSION = 2
TABLES = {"document_chunks", "document_vectors", "document_sources"}


def _ensure_schema(connection: sqlite3.Connection, force: bool) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if not force and version == SCHEMA_VERSION and TABLES <= tables:
        return
    # This database is a disposable index, never the authoritative source.
    for table in (*sorted(TABLES), "documents"):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute(
        "CREATE VIRTUAL TABLE document_chunks USING fts5("
        "chunk_id UNINDEXED, document_id UNINDEXED, kind UNINDEXED, title, body, "
        "path UNINDEXED, start_offset UNINDEXED, end_offset UNINDEXED)"
    )
    connection.execute(
        "CREATE TABLE document_vectors (chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, "
        "vector TEXT NOT NULL, body TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE INDEX idx_vectors_document ON document_vectors(document_id)"
    )
    connection.execute(
        "CREATE TABLE document_sources (document_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
        "domain_id TEXT NOT NULL, source_order INTEGER NOT NULL)"
    )
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def sync_index(
    path: Path,
    documents: Callable[[], list[dict[str, Any]]],
    chunker: Callable,
    vectorizer: Callable,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Read once under the index lock and recompute only changed documents.

    Content fingerprints detect external edits even when timestamps/size are
    preserved. One transaction keeps FTS, vectors and source metadata aligned.
    A fresh instance/process reuses the persisted fingerprints, without a cache
    that can hide edits, deletion or changed research-domain assignments.
    """
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema(connection, force)
        docs = documents()
        current = {str(doc.get("id", "")): doc for doc in docs}
        if len(current) != len(docs):
            raise ValueError("Markdown documents must have unique IDs")
        indexed = {
            row[0]: (row[1], row[2], row[3])
            for row in connection.execute(
                "SELECT document_id, fingerprint, domain_id, source_order FROM document_sources"
            )
        }
        for document_id in indexed.keys() - current.keys():
            _remove_document(connection, document_id)
            connection.execute(
                "DELETE FROM document_sources WHERE document_id=?", (document_id,)
            )
        for source_order, (document_id, doc) in enumerate(current.items()):
            kind, title, body, source, language = (
                str(doc.get(key, default))
                for key, default in (
                    ("kind", ""),
                    ("title", ""),
                    ("body", ""),
                    ("path", ""),
                    ("language", "python"),
                )
            )
            fingerprint = hashlib.sha256(
                json.dumps(
                    [kind, title, body, source, language], ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest()
            domain_id = str(doc.get("domain_id", ""))
            previous = indexed.get(document_id)
            if not previous or previous[0] != fingerprint:
                _remove_document(connection, document_id)
                chunks = [
                    (
                        f"{document_id}:{index}",
                        document_id,
                        kind,
                        title,
                        content,
                        source,
                        start,
                        end,
                    )
                    for index, (start, end, content) in enumerate(
                        chunker(body, kind, language)
                    )
                ]
                connection.executemany(
                    "INSERT INTO document_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    chunks,
                )
                connection.executemany(
                    "INSERT INTO document_vectors VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        (
                            chunk_id,
                            document_id,
                            json.dumps(
                                vectorizer(f"{title}\n{content}"), separators=(",", ":")
                            ),
                            content,
                            start,
                            end,
                        )
                        for chunk_id, _id, _kind, _title, content, _source, start, end in chunks
                    ),
                )
            if previous != (fingerprint, domain_id, source_order):
                connection.execute(
                    "INSERT INTO document_sources VALUES (?, ?, ?, ?) ON CONFLICT(document_id) DO UPDATE SET "
                    "fingerprint=excluded.fingerprint, domain_id=excluded.domain_id, source_order=excluded.source_order",
                    (document_id, fingerprint, domain_id, source_order),
                )
        connection.commit()
        return docs
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _remove_document(connection: sqlite3.Connection, document_id: str) -> None:
    connection.execute(
        "DELETE FROM document_chunks WHERE document_id=?", (document_id,)
    )
    connection.execute(
        "DELETE FROM document_vectors WHERE document_id=?", (document_id,)
    )
