from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import InvestigationORM
from app.services.confidence_scoring import validated_confidence


def backfill_confidence(*, apply: bool = False) -> dict[str, Any]:
    """Recalcula confiança de todas as investigações persistidas.

    Em modo dry-run apenas informa as mudanças. Com ``apply=True`` atualiza as
    colunas status/confidence e o JSON analysis usando somente dados já salvos.
    """
    changed: list[dict[str, Any]] = []
    unchanged = 0

    with SessionLocal() as session:
        rows = session.scalars(
            select(InvestigationORM).order_by(InvestigationORM.created_at.asc())
        ).all()

        for row in rows:
            analysis = dict(row.analysis or {})
            status = str(analysis.get("status") or row.status or "inconclusive")
            new_confidence, basis = validated_confidence(
                status=status,
                analysis=analysis,
                evidence=list(row.evidence or []),
                assessments=list(row.assessments or []),
            )
            old_confidence = int(row.confidence or 0)
            old_status = str(row.status or "inconclusive")
            if old_confidence == new_confidence and old_status == status and analysis.get("validated_confidence_basis") == basis:
                unchanged += 1
                continue

            changed.append(
                {
                    "id": str(row.id),
                    "target": row.target,
                    "hostname": row.hostname,
                    "status_before": old_status,
                    "status_after": status,
                    "confidence_before": old_confidence,
                    "confidence_after": new_confidence,
                    "evidence_total": basis["evidence_total"],
                    "evidence_successful": basis["evidence_successful"],
                    "critic_verdict": basis["critic_verdict"],
                }
            )

            if apply:
                analysis["confidence"] = new_confidence
                analysis["validated_confidence_basis"] = basis
                row.analysis = analysis
                row.status = status
                row.confidence = new_confidence

        if apply:
            session.commit()

    return {
        "mode": "apply" if apply else "dry-run",
        "total": len(changed) + unchanged,
        "changed": len(changed),
        "unchanged": unchanged,
        "items": changed,
    }
