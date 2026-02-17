import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionLog, DialogueNode, ReplayReport, Session as StorySession, SessionCharacterState


class ReplayEngine:
    REQUIRED_DIMS = ('trust', 'attraction', 'fear', 'respect')

    def build_report(self, session_id: uuid.UUID, db: Session) -> dict:
        sess = db.get(StorySession, session_id)
        if not sess:
            raise ValueError('session not found')

        nodes = db.execute(
            select(DialogueNode).where(DialogueNode.session_id == session_id).order_by(DialogueNode.created_at.asc(), DialogueNode.id.asc())
        ).scalars().all()
        logs = db.execute(
            select(ActionLog).where(ActionLog.session_id == session_id).order_by(ActionLog.created_at.asc(), ActionLog.id.asc())
        ).scalars().all()
        final_states = db.execute(
            select(SessionCharacterState)
            .where(SessionCharacterState.session_id == session_id)
            .order_by(SessionCharacterState.character_id.asc())
        ).scalars().all()

        node_map = {str(n.id): n for n in nodes}

        route_type = 'default'
        for node in reversed(nodes):
            decision = node.branch_decision or {}
            if decision.get('route_type'):
                route_type = decision['route_type']
                break

        decision_points = []
        affection_timeline = defaultdict(list)
        attribution = []
        missed_routes = []
        what_if = []
        key_decisions = []
        fallback_summary: dict[str, int] = defaultdict(int)
        story_path = []

        score_delta_totals: dict[str, int] = defaultdict(int)
        vector_delta_totals: dict[str, dict[str, float]] = defaultdict(lambda: {dim: 0.0 for dim in self.REQUIRED_DIMS})
        for log in logs:
            for delta in log.affection_delta or []:
                char_id = str(delta.get('char_id'))
                score_delta_totals[char_id] += int(delta.get('score_delta', 0))
                vec_delta = delta.get('vector_delta') or {}
                for dim in self.REQUIRED_DIMS:
                    vector_delta_totals[char_id][dim] += float(vec_delta.get(dim, 0.0))

        accumulator = {}
        for state in final_states:
            char_id = str(state.character_id)
            relation = state.relation_vector or {}
            accumulator[char_id] = {
                'score_visible': int(state.score_visible),
                'relation_vector': {dim: float(relation.get(dim, 0.0)) for dim in self.REQUIRED_DIMS},
            }

        for char_id, cur in accumulator.items():
            cur['score_visible'] = max(0, min(100, cur['score_visible'] - score_delta_totals.get(char_id, 0)))
            for dim in self.REQUIRED_DIMS:
                cur['relation_vector'][dim] = max(
                    -1.0,
                    min(1.0, cur['relation_vector'][dim] - vector_delta_totals[char_id][dim]),
                )

            affection_timeline[char_id].append(
                {
                    'step_index': 0,
                    'timestamp': sess.created_at.isoformat(),
                    'score_visible': cur['score_visible'],
                    'relation_vector': dict(cur['relation_vector']),
                }
            )

        for idx, log in enumerate(logs, start=1):
            node = node_map.get(str(log.node_id)) if log.node_id else None
            classification = log.classification or {}
            branch_eval = log.branch_evaluation or []
            chosen = None
            if node and node.branch_decision:
                chosen = {
                    'branch_id': node.branch_decision.get('chosen_branch_id'),
                    'route_type': node.branch_decision.get('route_type'),
                }

            token_remaining = None
            if node and node.branch_decision:
                token_remaining = node.branch_decision.get('token_budget_remaining')

            decision_points.append(
                {
                    'step_index': idx,
                    'timestamp': log.created_at.isoformat(),
                    'node_id': str(log.node_id) if log.node_id else None,
                    'player_input': log.player_input,
                    'classification': {
                        'intent': classification.get('intent'),
                        'tone': classification.get('tone'),
                        'behavior_tags': classification.get('behavior_tags', []),
                    },
                    'chosen_branch': chosen,
                    'choices_shown': (node.choices if node else []),
                    'token_budget_remaining': token_remaining,
                }
            )

            if getattr(log, "story_node_id", None) is not None or getattr(log, "story_choice_id", None) is not None:
                story_path.append({"step": idx, "node_id": log.story_node_id, "choice_id": log.story_choice_id})

            if bool(getattr(log, 'key_decision', False)):
                key_decisions.append(
                    {
                        'step_index': idx,
                        'final_action': log.final_action or {},
                        'user_raw_input': log.user_raw_input,
                    }
                )

            if bool(getattr(log, 'fallback_used', False)):
                for reason in (log.fallback_reasons or []):
                    fallback_summary[str(reason)] += 1

            for delta in log.affection_delta or []:
                char_id = str(delta.get('char_id'))
                if char_id not in accumulator:
                    accumulator[char_id] = {
                        'score_visible': 50,
                        'relation_vector': {dim: 0.0 for dim in self.REQUIRED_DIMS},
                    }
                    affection_timeline[char_id].append(
                        {
                            'step_index': 0,
                            'timestamp': sess.created_at.isoformat(),
                            'score_visible': 50,
                            'relation_vector': {dim: 0.0 for dim in self.REQUIRED_DIMS},
                        }
                    )
                cur = accumulator[char_id]
                cur['score_visible'] += int(delta.get('score_delta', 0))
                cur['score_visible'] = max(0, min(100, cur['score_visible']))
                vec_delta = delta.get('vector_delta') or {}
                for dim in self.REQUIRED_DIMS:
                    cur['relation_vector'][dim] += float(vec_delta.get(dim, 0.0))
                    cur['relation_vector'][dim] = max(-1.0, min(1.0, cur['relation_vector'][dim]))

                affection_timeline[char_id].append(
                    {
                        'step_index': idx,
                        'timestamp': log.created_at.isoformat(),
                        'score_visible': cur['score_visible'],
                        'relation_vector': dict(cur['relation_vector']),
                    }
                )

            for hit in log.matched_rules or []:
                rule_id = hit.get('rule_id') if isinstance(hit, dict) else None
                if not rule_id:
                    continue
                attribution.append(
                    {
                        'step_index': idx,
                        'character_id': hit.get('character_id'),
                        'rule_id': rule_id,
                        'vector_delta': hit.get('vector_delta', {}),
                        'score_delta': hit.get('score_delta', 0),
                    }
                )

            alternatives = []
            for ev in branch_eval:
                is_chosen = chosen and ev.get('branch_id') == chosen.get('branch_id')
                if ev.get('matched') and not is_chosen:
                    missed_routes.append(
                        {
                            'step_index': idx,
                            'branch_id': ev.get('branch_id'),
                            'route_type': ev.get('route_type'),
                            'priority': ev.get('priority'),
                            'matched': True,
                            'reason': 'priority lost',
                            'unlock_hint': 'This branch already matched; increase priority or pick this choice.',
                        }
                    )
                    alternatives.append(
                        {
                            'step_index': idx,
                            'type': 'matched_alternative',
                            'message': f"If choose alternative branch {ev.get('route_type')}.",
                            'branch_id': ev.get('branch_id'),
                            'route_type': ev.get('route_type'),
                        }
                    )
                elif not ev.get('matched'):
                    hint = _hint_from_trace(ev.get('trace') or {})
                    missed_routes.append(
                        {
                            'step_index': idx,
                            'branch_id': ev.get('branch_id'),
                            'route_type': ev.get('route_type'),
                            'priority': ev.get('priority'),
                            'matched': False,
                            'reason': _reason_from_trace(ev.get('trace') or {}),
                            'unlock_hint': hint,
                        }
                    )
                    if hint:
                        alternatives.append(
                            {
                                'step_index': idx,
                                'type': 'near_miss',
                                'message': hint,
                                'branch_id': ev.get('branch_id'),
                                'route_type': ev.get('route_type'),
                            }
                        )

            what_if.extend(alternatives[:2])

        relation_vector_final = {}
        for state in final_states:
            relation = state.relation_vector or {}
            relation_vector_final[str(state.character_id)] = {dim: float(relation.get(dim, 0.0)) for dim in self.REQUIRED_DIMS}

        return {
            'session_id': str(session_id),
            'route_type': route_type,
            'decision_points': decision_points,
            'affection_timeline': dict(affection_timeline),
            'relation_vector_final': relation_vector_final,
            'affection_attribution': attribution,
            'missed_routes': missed_routes,
            'what_if': what_if,
            'key_decisions': key_decisions,
            'fallback_summary': dict(fallback_summary),
            'story_path': story_path,
        }


def _reason_from_trace(trace: dict) -> str:
    if not trace:
        return 'no trace'
    if trace.get('op') in {'and', 'or'}:
        children = trace.get('children', [])
        child = next((c for c in children if not c.get('result')), children[0] if children else {})
        return _reason_from_trace(child)

    if trace.get('op') == 'flag':
        return f"flag {trace.get('key')} expected {trace.get('expected')} got {trace.get('actual_value')}"

    left = trace.get('left')
    op = trace.get('op')
    right = trace.get('right')
    actual = trace.get('actual_value')
    return f"{left} {op} {right}, actual={actual}"


def _hint_from_trace(trace: dict) -> str:
    if not trace:
        return ''
    if trace.get('op') in {'and', 'or'}:
        children = trace.get('children', [])
        child = next((c for c in children if not c.get('result')), children[0] if children else {})
        return _hint_from_trace(child)

    op = trace.get('op')
    if op == 'gte':
        return f"Increase {trace.get('left')} >= {trace.get('right')}"
    if op == 'lte':
        return f"Reduce {trace.get('left')} <= {trace.get('right')}"
    if op == 'flag':
        return f"Set flag {trace.get('key')}={trace.get('expected')}"
    if op == 'between':
        right = trace.get('right', {})
        return f"Adjust {trace.get('left')} to be between {right.get('min')} and {right.get('max')}"
    if op == 'contains':
        return f"Ensure {trace.get('left')} contains {trace.get('right')}"
    if op == 'eq':
        return f"Set {trace.get('left')} == {trace.get('right')}"
    return ''


def upsert_replay_report(db: Session, session_id: uuid.UUID, report: dict) -> ReplayReport:
    existing = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if existing:
        existing.report_json = report
        return existing
    row = ReplayReport(session_id=session_id, report_json=report)
    db.add(row)
    db.flush()
    return row
