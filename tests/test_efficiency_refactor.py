"""Behavior, recovery and bounded work for the efficiency refactor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from backend.services.common.audit import AuditIntegrityError, AuditLog
from backend.services.common.brain import MarkdownBrain
from backend.services.common.phase4 import Phase4Store
from desktop.memory import memory_manager


@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_HINDSIGHT_ENABLED", "0")
    return MarkdownBrain(tmp_path / "brain", tmp_path / "brain.sqlite3")


def test_unchanged_sources_reuse_index_after_restart(brain):
    doc = brain.write("notes", "Source", "The original deployment checklist.")
    restarted = MarkdownBrain(brain.root, brain.index_path)
    with (
        patch.object(
            restarted,
            "_chunks",
            side_effect=AssertionError("unchanged source rechunked"),
        ),
        patch.object(
            restarted,
            "_vector",
            side_effect=AssertionError("unneeded vector calculation"),
        ),
        patch.object(restarted, "documents", wraps=restarted.documents) as read,
    ):
        hits = restarted.search("deployment", limit=1)
    assert hits[0]["id"] == doc["id"] and hits[0]["confidence"] == "high"
    assert read.call_count == 1


def test_write_indexes_only_new_document_and_delete_removes_derived_rows(brain):
    original = brain.write("notes", "Original", "Original source")
    with patch.object(brain, "_chunks", wraps=brain._chunks) as chunks:
        added = brain.write("notes", "Second", "Second source")
    assert chunks.call_count == 1
    Path(original["path"]).unlink()  # external deletion, outside this instance
    brain.reindex(force=False)
    with sqlite3.connect(brain.index_path) as connection:
        for table in ("document_sources", "document_vectors", "document_chunks"):
            assert {
                row[0] for row in connection.execute(f"SELECT document_id FROM {table}")
            } == {added["id"]}


def test_external_same_size_edit_with_preserved_mtime_is_not_hidden(brain):
    doc = brain.write("notes", "Words", "alpha")
    path = Path(doc["path"])
    before = path.stat()
    path.write_text(
        path.read_text(encoding="utf-8").replace("alpha", "omega"),
        encoding="utf-8",
        newline="\n",
    )
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    hits = brain.search("omega", limit=1)
    assert hits[0]["confidence"] == "high" and "omega" in hits[0]["snippet"]
    assert not any(hit["confidence"] == "high" for hit in brain.search("alpha"))


def test_equal_rank_hits_keep_newest_source_first_after_incremental_writes(brain):
    first = brain.write("notes", "Source", "identical deployment checklist")
    second = brain.write("notes", "Source", "identical deployment checklist")
    assert [hit["id"] for hit in brain.search("deployment", limit=2)] == [
        second["id"],
        first["id"],
    ]
    brain.update_document(first["id"], "identical deployment checklist")
    assert [hit["id"] for hit in brain.search("deployment", limit=2)] == [
        second["id"],
        first["id"],
    ]


def test_failed_atomic_source_update_keeps_original_bytes_and_no_temporary_files(brain):
    doc = brain.write("notes", "Source", "original evidence\r\nsecond line")
    path = Path(doc["path"])
    before = path.read_bytes()
    with patch(
        "backend.services.common.brain.os.replace",
        side_effect=OSError("simulated write failure"),
    ):
        with pytest.raises(OSError):
            brain.update_document(doc["id"], "replacement")
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_domain_filter_applies_before_fts_limit_and_metadata_changes_are_live(brain):
    # Many better-ranked hits from another domain must not crowd out an exact hit.
    for index in range(35):
        metadata = {
            "id": f"{index:032x}",
            "kind": "notes",
            "title": "checklist",
            "domain_id": "other",
        }
        (brain.root / f"{index}.md").write_text(
            "---\n" + json.dumps(metadata) + "\n---\n\nchecklist", encoding="utf-8"
        )
    selected = brain.write(
        "notes",
        "Selected",
        "checklist " + "background " * 80,
        {"domain_id": "selected"},
    )
    hits = brain.search("checklist", limit=1, domain_id="selected")
    assert hits[0]["id"] == selected["id"] and hits[0]["confidence"] == "high"
    with patch.object(
        brain, "_chunks", side_effect=AssertionError("metadata rechunked")
    ):
        brain.update_metadata(selected["id"], {"domain_id": "moved"})
        assert brain.search("checklist", domain_id="selected") == []
        assert (
            brain.search("checklist", limit=1, domain_id="moved")[0]["id"]
            == selected["id"]
        )


def test_index_migration_and_explicit_rebuild_recover_lost_rows(brain):
    with sqlite3.connect(brain.index_path) as connection:
        connection.execute("CREATE TABLE documents (id TEXT)")
    doc = brain.write("notes", "Restored", "rebuildable source")
    with sqlite3.connect(brain.index_path) as connection:
        connection.execute("DELETE FROM document_vectors")
    assert brain.reindex() == 1  # explicit requests still force a complete rebuild
    with sqlite3.connect(brain.index_path) as connection:
        assert (
            connection.execute("SELECT document_id FROM document_vectors").fetchone()[0]
            == doc["id"]
        )
        connection.execute("DROP TABLE document_sources")
    assert brain.search("rebuildable", limit=1)[0]["id"] == doc["id"]


def test_failed_incremental_update_rolls_back_both_indexes(brain):
    doc = brain.write("notes", "Original", "alpha")
    path = Path(doc["path"])
    path.write_text(
        path.read_text(encoding="utf-8").replace("alpha", "omega"), encoding="utf-8"
    )
    with patch.object(
        brain, "_vector", side_effect=RuntimeError("simulated interrupted indexing")
    ):
        with pytest.raises(RuntimeError):
            brain.reindex(force=False)
    with sqlite3.connect(brain.index_path) as connection:
        assert (
            connection.execute("SELECT body FROM document_chunks").fetchone()[0]
            == "alpha"
        )
        assert (
            connection.execute("SELECT body FROM document_vectors").fetchone()[0]
            == "alpha"
        )
    assert "omega" in brain.search("omega", limit=1)[0]["snippet"]


def test_parallel_instances_do_not_lose_documents(brain):
    def write(index):
        other = MarkdownBrain(brain.root, brain.index_path)
        return other.write("notes", f"Source {index}", f"deployment marker{index}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        docs = list(executor.map(write, range(8)))
    assert len(brain.search("deployment", limit=30)) == 8
    with sqlite3.connect(brain.index_path) as connection:
        assert {
            row[0]
            for row in connection.execute("SELECT document_id FROM document_vectors")
        } == {doc["id"] for doc in docs}


def test_vector_top_documents_preserve_exhaustive_ranking(brain):
    for index in range(8):
        brain.write(
            "notes", str(index), (f"container diagnosis runtime project{index} " * 100)
        )
    query = "diagnoses"  # vector recall, without an exact FTS token
    vector = brain._vector(query)
    with sqlite3.connect(brain.index_path) as connection:
        candidates = [
            (brain._cosine(vector, json.loads(encoded)), chunk, doc, body, start, end)
            for chunk, doc, encoded, body, start, end in connection.execute(
                "SELECT * FROM document_vectors"
            )
        ]
    expected = []
    for score, chunk, doc, body, start, end in sorted(candidates, reverse=True):
        if score > 0 and doc not in {item[0] for item in expected}:
            expected.append((doc, chunk, start, end))
    hits = brain.search(query, limit=4, kind="notes")
    assert [
        (hit["id"], hit["chunk_id"], hit["start_offset"], hit["end_offset"])
        for hit in hits
    ] == expected[:4]


def test_audit_still_verifies_records_outside_returned_tail(tmp_path):
    audit = AuditLog(tmp_path / "events.jsonl")
    for index in range(30):
        audit.append("probe", {"number": index})
    assert [event["payload"]["number"] for event in audit.read(2)] == [28, 29]
    lines = audit.path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["number"] = 999
    lines[0] = json.dumps(event)
    audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = audit.path.read_bytes()
    assert audit.read(2) == [] and not audit.verify()
    with pytest.raises(AuditIntegrityError):
        audit.append("probe", {})
    assert audit.path.read_bytes() == before


def test_plan_list_batches_details_and_preserves_single_record_shape(tmp_path):
    store = Phase4Store(tmp_path / "plans.sqlite3")
    plans = [
        store.create_plan(f"Plan {index}", [{"action": "files.list", "params": {}}])
        for index in range(6)
    ]
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO agent_plan_corrections VALUES(?,?,?,?,?,?,?)",
            ("correction", plans[0]["id"], 1, "[]", "reason", "proposed", "2026-10-04"),
        )
    expected = [store.get_plan(plan["id"]) for plan in reversed(plans)]
    with patch.object(store, "_connect", wraps=store._connect) as connect:
        actual = store.list_plans("draft")
    assert actual == expected and connect.call_count == 1
    assert store.list_plans("completed") == []
    with pytest.raises(ValueError):
        store.list_plans("invalid")


def test_twin_list_batches_facts_and_preserves_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_PHASE4_ENABLED", "1")
    monkeypatch.setenv("MICA_DIGITAL_TWIN_ENABLED", "1")
    store = Phase4Store(tmp_path / "twin.sqlite3")
    store.update_twin_settings({"enabled": True})
    facts = [
        store.observe_twin(
            f"preference{index}",
            "high",
            "preference",
            "confirmed_profile",
            f"source{index}",
            0.9,
        )
        for index in range(5)
    ]
    store.patch_twin_fact(facts[0]["id"], {"revoked": True})
    with patch.object(store, "_connect", wraps=store._connect) as connect:
        actual = store.twin_facts()
    assert connect.call_count == 1
    assert {item["id"] for item in actual} == {item["id"] for item in facts}
    for item in actual:
        assert item == store.get_twin_fact(item["id"])
        assert all(
            isinstance(item[key], bool) for key in ("active", "confirmed", "revoked")
        )


@pytest.mark.parametrize("limit", [20, 80, 190, 450, 1000])
def test_trim_keeps_same_oldest_first_semantics_with_unicode_and_escaping(
    limit, monkeypatch
):
    data = {
        "notes": {
            'Ä\\"': {"value": "ä\n" * 30, "updated": "1"},
            "Z": {"value": "β" * 50, "updated": "3"},
        },
        "projects": {"文": {"value": "\\" * 60, "updated": "2"}},
        "untouched": [1, 2],
    }
    expected = copy.deepcopy(data)
    for category, key, entry in sorted(
        memory_manager._all_entries(expected),
        key=lambda item: item[2].get("updated", "0000-00-00"),
    ):
        if len(json.dumps(expected, ensure_ascii=False)) <= limit:
            break
        del expected[category][key]
    monkeypatch.setattr(memory_manager, "MEMORY_MAX_CHARS", limit)
    monkeypatch.setattr(memory_manager, "_trim_notifier", None)
    assert memory_manager._trim_to_limit(copy.deepcopy(data)) == expected


def test_hidden_decorative_widgets_stop_timers_and_resume_when_shown(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from desktop.ui_widgets import HudCanvas, LiveWaveform

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    hud, wave = HudCanvas(""), LiveWaveform()
    layout.addWidget(hud)
    layout.addWidget(wave)
    try:
        assert not hud._tmr.isActive() and not wave._timer.isActive()
        window.show()
        app.processEvents()
        assert hud._tmr.isActive() and wave._timer.isActive()
        window.hide()
        app.processEvents()
        assert not hud._tmr.isActive() and not wave._timer.isActive()
        window.show()
        app.processEvents()
        assert hud._tmr.isActive() and wave._timer.isActive()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
