from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Any
import uuid

from .audit import AuditLog
from .brain import MarkdownBrain
from .policy import PolicyEngine


class Orchestrator:
    def __init__(self, brain: MarkdownBrain, audit: AuditLog, policy: PolicyEngine):
        self.brain, self.audit, self.policy = brain, audit, policy

    def plan(
        self, message: str, action: str | None, params: dict[str, Any], dry_run: bool,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        evidence = self.brain.search(message, limit=5)
        selected_action = action or "brain.search"
        decision = self.policy.decide(selected_action, params, dry_run=dry_run)
        plan = {"turn_id": turn_id, "task_id": task_id, "action": selected_action, "dry_run": dry_run, "retrieval": evidence, "permission": asdict(decision), "expected_change": "None" if dry_run else "Delegated only after policy approval"}
        self.audit.append("task.planned", {
            "turn_id": turn_id, "task_id": task_id, "action": selected_action,
            "dry_run": dry_run, "message_length": len(message),
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "permission": asdict(decision),
        })
        self.brain.write("tasks", message[:100] or "Untitled task", f"Action: `{selected_action}`\n\nDry run: `{dry_run}`\n\nRetrieved evidence:\n" + "\n".join(f"- [[{item['id']}]] {item['title']}" for item in evidence), {"task_id": task_id})
        return plan

    def record_outcome(self, task_id: str, action: str, success: bool, evidence: str, reproduction: str = "") -> dict[str, str]:
        """Store outcome evidence and a reproducible lesson without storing audio.

        A failed host/Docker result is first stored as a dedicated local
        Markdown evidence document.  The lesson links it and carries the
        SHA-256 so the UI and a later retrieval can distinguish the original
        captured result from any later natural-language explanation.
        """
        kind = "runbooks" if success else "lessons"
        title = f"{'Erfolgsrezept' if success else 'Fehleranalyse'}: {action}"
        evidence_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        evidence_document = self.brain.write(
            "evidence", f"Unveränderte Evidenz: {action}", evidence,
            {"task_id": task_id, "action": action, "success": success, "sha256": evidence_hash},
        )
        body = (
            f"Task: `{task_id}`\n\nAction: `{action}`\n\n"
            f"Unveränderte Evidenz: [[{evidence_document['id']}]]\n\n"
            f"SHA-256 der Evidenz: `{evidence_hash}`"
        )
        if not success:
            body += f"\n\nReproduktion/Testentwurf:\n{reproduction.strip() or 'Noch nicht angegeben.'}"
        else:
            body += "\n\nOptimierungsanalyse:\nBeim nächsten Lauf Laufzeit, Ergebnisqualität und unnötige Schritte mit diesem Evidenzstand vergleichen."
        document = self.brain.write(kind, title, body, {
            "task_id": task_id, "success": success, "action": action,
            "evidence_document": evidence_document["id"], "evidence_sha256": evidence_hash,
        })
        self.audit.append("task.completed" if success else "task.failed", {
            "task_id": task_id, "action": action, "brain_document": document["id"],
            "evidence_document": evidence_document["id"], "evidence_sha256": evidence_hash,
        })
        return document
