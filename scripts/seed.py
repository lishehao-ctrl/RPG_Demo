import uuid

from sqlalchemy import select

from app.db.models import Branch, Character, DialogueNode, Session, SessionCharacterState, User
from app.db.session import SessionLocal


def run() -> None:
    with SessionLocal() as db:
        with db.begin():
            user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
            user = db.get(User, user_id)
            if not user:
                user = User(id=user_id, google_sub="seed-user", email="seed@example.com", display_name="Seed User")
                db.add(user)

            c1 = db.execute(select(Character).where(Character.name == "Alice")).scalar_one_or_none()
            if not c1:
                c1 = Character(
                    name="Alice",
                    base_personality={"kind": 0.8},
                    initial_relation_vector={"trust": 0.4, "attraction": 0.3, "fear": 0.0, "respect": 0.4},
                    initial_visible_score=55,
                )
                db.add(c1)

            c2 = db.execute(select(Character).where(Character.name == "Eve")).scalar_one_or_none()
            if not c2:
                c2 = Character(
                    name="Eve",
                    base_personality={"strict": 0.7},
                    initial_relation_vector={"trust": 0.2, "attraction": 0.1, "fear": 0.1, "respect": 0.5},
                    initial_visible_score=48,
                )
                db.add(c2)
            db.flush()

            sess = Session(user_id=user.id, status="active", active_characters=[str(c1.id), str(c2.id)])
            db.add(sess)
            db.flush()

            root = DialogueNode(session_id=sess.id, node_type="system", narrative_text="root", choices=[], branch_decision={})
            db.add(root)
            db.flush()
            sess.current_node_id = root.id

            db.add(SessionCharacterState(session_id=sess.id, character_id=c1.id, score_visible=55, relation_vector=c1.initial_relation_vector, personality_drift={}))
            db.add(SessionCharacterState(session_id=sess.id, character_id=c2.id, score_visible=48, relation_vector=c2.initial_relation_vector, personality_drift={}))

            b1 = Branch(from_node_id=root.id, priority=20, is_exclusive=True, is_default=False, route_type="good", rule_expr={"op": "gte", "left": f"characters.{c1.id}.score_visible", "right": 60})
            b2 = Branch(from_node_id=root.id, priority=10, is_exclusive=True, is_default=False, route_type="danger", rule_expr={"op": "gte", "left": f"characters.{c1.id}.relation.fear", "right": 0.5})
            b3 = Branch(from_node_id=root.id, priority=0, is_exclusive=False, is_default=True, route_type="default", rule_expr={"op": "eq", "left": "flags.always", "right": True})
            db.add_all([b1, b2, b3])

    print("seed done")


if __name__ == "__main__":
    run()
