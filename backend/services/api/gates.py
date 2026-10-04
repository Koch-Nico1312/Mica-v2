from __future__ import annotations
import os
from fastapi import HTTPException


class RuntimeGates:
    """Shared feature guards for routes in several domains."""

    def _require_phase3(self) -> None:
        if not self.phase3_enabled():
            raise HTTPException(
                409, "Phase 3 pilot is disabled; set MICA_PHASE3_ENABLED=1"
            )

    def _require_phase4(self, feature: str | None = None) -> None:
        if not self.phase4_enabled():
            raise HTTPException(
                409, "Phase 4 pilot is disabled; set MICA_PHASE4_ENABLED=1"
            )
        if feature and (not self.phase4_feature_enabled(feature)):
            raise HTTPException(409, f"Phase 4 feature is disabled; set {feature}=1")

    def phase45_enabled(self) -> bool:
        return os.getenv("MICA_PHASE45_ENABLED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _require_phase45(self, feature: str | None = None) -> None:
        if not self.phase45_enabled():
            raise HTTPException(
                409, "Phase 4.5 pilot is disabled; set MICA_PHASE45_ENABLED=1"
            )
        if feature and (
            not os.getenv(feature, "0").strip().lower() in {"1", "true", "yes", "on"}
        ):
            raise HTTPException(409, f"Phase 4.5 feature is disabled; set {feature}=1")
