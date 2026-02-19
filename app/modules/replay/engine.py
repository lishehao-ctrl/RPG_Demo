import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionLog, ReplayReport, Session as StorySession


class ReplayEngine:
    def build_report(self, session_id: uuid.UUID, db: Session) -> dict:
        sess = db.get(StorySession, session_id)
        if not sess:
            raise ValueError("session not found")

        logs = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == session_id)
            .order_by(ActionLog.created_at.asc(), ActionLog.id.asc())
        ).scalars().all()

        key_decisions: list[dict] = []
        fallback_summary: dict[str, int] = defaultdict(int)
        story_path: list[dict] = []
        state_timeline: list[dict] = []

        for idx, log in enumerate(logs, start=1):
            if getattr(log, "story_node_id", None) is not None or getattr(log, "story_choice_id", None) is not None:
                story_path.append(
                    {
                        "step": idx,
                        "node_id": log.story_node_id,
                        "choice_id": log.story_choice_id,
                    }
                )

            if bool(getattr(log, "key_decision", False)):
                key_decisions.append(
                    {
                        "step_index": idx,
                        "final_action": log.final_action or {},
                        "user_raw_input": log.user_raw_input,
                    }
                )

            if bool(getattr(log, "fallback_used", False)):
                for reason in (log.fallback_reasons or []):
                    fallback_summary[str(reason)] += 1

            state_timeline.append(
                {
                    "step": idx,
                    "delta": (log.state_delta or {}),
                    "state_after": (log.state_after or {}),
                }
            )

        return {
            "session_id": str(session_id),
            "total_steps": len(logs),
            "key_decisions": key_decisions,
            "fallback_summary": dict(fallback_summary),
            "story_path": story_path,
            "state_timeline": state_timeline,
        }


def upsert_replay_report(db: Session, session_id: uuid.UUID, report: dict) -> ReplayReport:
    existing = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if existing:
        existing.report_json = report
        return existing
    row = ReplayReport(session_id=session_id, report_json=report)
    db.add(row)
    db.flush()
    return row
