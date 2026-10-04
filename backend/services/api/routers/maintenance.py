from __future__ import annotations

import asyncio
from pathlib import Path
import re
import tempfile
from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse
from typing import Any
from fastapi import Header, Request


class MaintenanceRoutes:
    async def protect_storage(self, request: Request, call_next):
        bypass = request.url.path.startswith("/v1/backups") or request.url.path in {
            "/health",
            "/v1/auth/approval-session",
            "/v1/emergency-stop",
            "/v1/emergency/stop",
        }
        if bypass:
            return await call_next(request)
        root = self.brain.root.parent
        if (root / ".restore-incomplete").exists():
            return JSONResponse(
                {
                    "detail": "Wiederherstellung unvollständig; Recovery-Backup verwenden."
                },
                status_code=503,
            )
        try:
            lease = await asyncio.to_thread(self.StorageLease, root, timeout=1)
        except self.StorageBusy:
            return JSONResponse(
                {"detail": "Backup/Wiederherstellung läuft; erneut versuchen."},
                status_code=503,
            )
        try:
            if (root / ".restore-incomplete").exists():
                return JSONResponse(
                    {
                        "detail": "Wiederherstellung unvollständig; Recovery-Backup verwenden."
                    },
                    status_code=503,
                )
            return await call_next(request)
        finally:
            lease.close()

    def export_backup(
        self,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ):
        from backend.backup_restore import create_backup, verify_restore, BackupDrillError

        self._memory_confirmation(request, x_mica_approval_intent)
        root = self._backup_root()
        try:
            with (
                self.StorageLease(root, exclusive=True, timeout=30),
                tempfile.TemporaryDirectory(prefix="mica-export-") as temp,
            ):
                archive, _ = create_backup(root, Path(temp))
                verify_restore(archive)
                if archive.stat().st_size > 64 * 1024 * 1024:
                    raise HTTPException(
                        413, "Backup ist zu groß für die Desktop-Oberfläche."
                    )
                return Response(
                    archive.read_bytes(),
                    media_type="application/gzip",
                    headers={
                        "Content-Disposition": f'attachment; filename="{archive.name}"'
                    },
                )
        except (BackupDrillError, self.StorageBusy) as error:
            raise HTTPException(409, str(error)) from error

    def backup_status(self) -> dict[str, Any]:
        marker = self.brain.root.parent / ".restore-incomplete"
        return {
            "maintenance": marker.exists(),
            "recovery_id": marker.read_text(encoding="ascii")
            if marker.exists()
            else None,
        }

    def recovery_backup(
        self,
        recovery_id: str,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ):
        self._memory_confirmation(request, x_mica_approval_intent)
        if not re.fullmatch("[a-f0-9]{32}", recovery_id):
            raise HTTPException(422, "Ungültige Recovery-ID")
        archive = self.brain.root.parent / "recovery" / f"{recovery_id}.tar.gz"
        if not archive.is_file() or archive.is_symlink():
            raise HTTPException(404, "Recovery-Backup nicht vorhanden")
        return Response(archive.read_bytes(), media_type="application/gzip")

    async def restore_backup(
        self,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ):
        from backend.backup_restore import restore_live, BackupDrillError

        self._memory_confirmation(request, x_mica_approval_intent)
        root = self._backup_root()
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 64 * 1024 * 1024:
                raise HTTPException(
                    413, "Backup ist zu groß für die Desktop-Oberfläche."
                )
        with tempfile.TemporaryDirectory(prefix="mica-upload-") as temp:
            archive = Path(temp) / "backup.tar.gz"
            archive.write_bytes(content)
            try:
                return await asyncio.to_thread(restore_live, archive, root)
            except (BackupDrillError, self.StorageBusy, ValueError) as error:
                raise HTTPException(409, str(error)) from error

    def _backup_root(self) -> Path:
        root = self.brain.root.parent.resolve()
        expected = [
            (self.brain.root, root / "brain"),
            (self.brain.index_path, root / "index" / "brain.sqlite3"),
            (self.audit.path, root / "audit" / "events.jsonl"),
            (self.schedule_store.path, root / "scheduler.sqlite3"),
            (self.phase4_store.path, root / "scheduler.sqlite3"),
            (self.profile_store.path, root / "profile.json"),
            (self.learning_domains.path, root / "learning" / "domains.json"),
            (self.policy.db_path, root / "approvals.sqlite3"),
        ]
        if any((actual.resolve() != target for actual, target in expected)):
            raise HTTPException(
                409,
                "Backup-Oberfläche benötigt das dokumentierte gemeinsame Datenverzeichnis.",
            )
        return root


ROUTES = [
    ("/v1/backups/export", "get", "export_backup"),
    ("/v1/backups/status", "get", "backup_status"),
    ("/v1/backups/recovery/{recovery_id}", "get", "recovery_backup"),
    ("/v1/backups/restore", "post", "restore_backup"),
]
