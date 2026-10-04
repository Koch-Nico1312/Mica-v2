from __future__ import annotations

import os
from fastapi import HTTPException
from typing import Any
from fastapi import Header, Request
from backend.services.api.schemas import BrainDocumentUpdate, ChatRequest, MemoryItemCreate


class MemoryRoutes:
    def search_brain(
        self,
        q: str,
        limit: int = 8,
        domain_id: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        if domain_id and (not self.learning_domains.get(domain_id)):
            raise HTTPException(422, "Unknown learning domain")
        results = self.brain.search(q, limit, domain_id=domain_id, kind=kind)
        return {"results": self.rerank_retrieval(q, results)}

    def brain_graph(self) -> dict[str, Any]:
        return self.brain.graph()

    def brain_explorer(self, limit: int = 200) -> dict[str, Any]:
        """Cross-linked, read-only projection for the local Brain UI."""
        bounded = max(1, min(limit, 500))
        documents = self.brain.documents()[:bounded]
        summaries = [
            {
                "id": str(doc.get("id", "")),
                "kind": str(doc.get("kind", "")),
                "title": str(doc.get("title", "")),
                "created_at": str(doc.get("created_at", "")),
                "source": str(doc.get("path", "")),
                "excerpt": str(doc.get("body", ""))[:360],
                "task_id": str(doc.get("task_id", "")),
            }
            for doc in documents
        ]
        audit_events = self.audit.read(bounded)
        graph = self.brain.graph()
        brain_ids = {node["id"] for node in graph["nodes"]}
        for event in audit_events:
            audit_id = f"audit:{str(event.get('hash', ''))[:16]}"
            graph["nodes"].append(
                {
                    "id": audit_id,
                    "label": str(event.get("type", "audit")),
                    "kind": "audit",
                }
            )
            payload = (
                event.get("payload", {})
                if isinstance(event.get("payload"), dict)
                else {}
            )
            references = [
                payload.get("brain_document"),
                *(
                    payload.get("brain_references", [])
                    if isinstance(payload.get("brain_references"), list)
                    else []
                ),
            ]
            unique_references = dict.fromkeys(
                (item for item in references if isinstance(item, str) and item)
            )
            for reference in unique_references:
                if reference in brain_ids:
                    graph["links"].append({"source": audit_id, "target": reference})
        return {
            "graph": graph,
            "documents": summaries,
            "lessons": [item for item in summaries if item["kind"] == "lessons"],
            "executions": [
                item for item in summaries if item["kind"] in {"tasks", "runbooks"}
            ],
            "timeline": sorted(
                summaries, key=lambda item: item["created_at"], reverse=True
            ),
            "audit": audit_events,
            "audit_valid": self.audit.verify(),
        }

    def brain_document(self, document_id: str) -> dict[str, Any]:
        if len(document_id) != 32 or any(
            (character not in "0123456789abcdef" for character in document_id)
        ):
            raise HTTPException(422, "Invalid document id")
        document = next(
            (doc for doc in self.brain.documents() if doc.get("id") == document_id),
            None,
        )
        if not document:
            raise HTTPException(404, "Brain document not found")
        return {"document": document}

    def hindsight_status(self) -> dict[str, Any]:
        return self.HindsightMemory(self.brain).status()

    def hindsight_reflect(self, request: ChatRequest) -> dict[str, Any]:
        if self.policy.is_emergency_stopped():
            raise HTTPException(409, "Not-Aus ist aktiv")
        return self.HindsightMemory(self.brain).reflect(request.message)

    def memory_items(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": doc["id"],
                    "title": doc.get("title", ""),
                    "body": doc.get("body", ""),
                    "kind": doc.get("kind", ""),
                    "source": doc.get(
                        "source_url", doc.get("source", doc.get("kind", "Markdown"))
                    ),
                    "sources": doc.get("source_urls", []),
                    "created_at": doc.get("created_at", ""),
                    "updated_at": doc.get("updated_at", ""),
                    "hindsight_exclude": bool(doc.get("hindsight_exclude")),
                    "explicitly_remembered": doc.get("explicitly_remembered") is True,
                    "inferred": doc.get("inferred") is True,
                    "confirmed": doc.get("confirmed") is True,
                }
                for doc in self.brain.documents()
            ]
        }

    def remember_item(
        self,
        update: MemoryItemCreate,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        document = self.brain.write(
            "memory",
            update.title,
            update.body,
            {"source": "desktop_user", "explicitly_remembered": True},
        )
        self.audit.append("desktop.memory.remembered", {"id": document["id"]})
        return {"document": document}

    def hindsight_sync(
        self,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        if self.policy.is_emergency_stopped():
            raise HTTPException(409, "Not-Aus ist aktiv")
        return self.HindsightMemory(self.brain).sync(limit=1)

    def correct_brain_document(
        self,
        document_id: str,
        update: BrainDocumentUpdate,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        try:
            document = self.brain.update_document(
                document_id, update.body, update.memory_excerpt
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not document:
            raise HTTPException(404, "Brain document not found")
        self.audit.append("brain.document_corrected", {"id": document_id})
        return {
            "document": document,
            "hindsight": self.HindsightMemory(self.brain).status(),
        }

    def forget_brain_document(
        self,
        document_id: str,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        if not self.brain.delete_document(document_id):
            raise HTTPException(404, "Brain document not found")
        self.audit.append("brain.document_deleted", {"id": document_id})
        return {"deleted": True, "hindsight": self.HindsightMemory(self.brain).status()}

    def audit_events(self, limit: int = 100) -> dict[str, Any]:
        return {"events": self.audit.read(limit), "valid": self.audit.verify()}

    def migrate_memory(self) -> dict[str, int | str]:
        source = os.getenv("LEGACY_MEMORY_PATH", "").strip()
        if not source:
            raise HTTPException(
                status_code=409, detail="LEGACY_MEMORY_PATH is not configured"
            )
        try:
            result = self.migrate_legacy_memory(source, self.brain)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        self.audit.append("brain.legacy_memory_migrated", result)
        return result

    def _memory_confirmation(self, request: Request, intent: str | None) -> None:
        if intent != "confirm" or not self.approval_sessions.valid(
            request.cookies.get("mica_approval_session")
        ):
            raise HTTPException(
                401, "An authenticated local browser confirmation is required"
            )


ROUTES = [
    ("/v1/brain/search", "get", "search_brain"),
    ("/v1/brain/graph", "get", "brain_graph"),
    ("/v1/brain/explorer", "get", "brain_explorer"),
    ("/v1/brain/documents/{document_id}", "get", "brain_document"),
    ("/v1/memory/hindsight", "get", "hindsight_status"),
    ("/v1/memory/hindsight/reflect", "post", "hindsight_reflect"),
    ("/v1/memory/items", "get", "memory_items"),
    ("/v1/memory/items", "post", "remember_item"),
    ("/v1/memory/hindsight/sync", "post", "hindsight_sync"),
    ("/v1/brain/documents/{document_id}", "patch", "correct_brain_document"),
    ("/v1/brain/documents/{document_id}", "delete", "forget_brain_document"),
    ("/v1/audit", "get", "audit_events"),
    ("/v1/brain/migrate-legacy-memory", "post", "migrate_memory"),
]
