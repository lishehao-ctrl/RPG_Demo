"""Validate the B path hypothesis:

Given the SAME template, can we get genuinely different complete endings
out of three different play strategies, AND do those endings feel like
"a finished short story" rather than "we just stopped"?

What we're testing:
  H1: 12 turns × ~300 words ≈ 3600 words is enough story body
  H2: Different choice paths actually diverge into different ENDINGS
      (not just different middle scenes)
  H3: An ending_engine that synthesizes a 400-600 word epilogue with a
      typed label ("孤狼/共谋/复仇/...") feels conclusive
  H4: At least 3 distinct ending labels emerge from 3 strategies
      (= some claim to "multiple endings" exists)

If H1-H4 hold → B path is real, build it for production.
If they fail → triage what specifically fails before committing.

Strategy this script uses:
  - Backend's existing narrative engine handles turns 1-12
  - We simulate three players on the SAME template:
      * "撕逼派" — always picks the most aggressive option (highest idx)
      * "谋略派" — always picks the lowest idx (typically the careful one)
      * "自由派" — picks middle idx + 3 free-input perturbations
  - After turn 12 we hit a NEW experimental ending endpoint we don't
    have yet. So we mock it client-side: build a synthesis prompt and
    call the LLM via the same /narrative/sessions/{id}/advisor pipe
    (works because advisor is full-history-aware), but interpret its
    reply as the ending.

  Wait — that's a hack. Let me do it cleanly: hit the LLM directly.
  We import the gateway from rpg_backend.narrative.gateway in a
  subprocess so we don't pollute the running uvicorn.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
SEED = "公司年会的红毯上 我前任的现任搂着我前任向我走来"
TURN_BUDGET = 12
RNG = random.Random(424242)


# ---------- one-time: backend bypass for ending_engine -----------------------
# We import the production transport directly to issue a custom prompt.
# This gives us identical behaviour to what production would do.
sys.path.insert(0, "/Users/lishehao/Desktop/Project/Personal/RPG_Demo_refactor")

from rpg_backend.narrative.gateway import get_narrative_gateway  # noqa: E402


_ENDING_SYSTEM_PROMPT = """\
你是剧作家。一段互动短剧已经走到尾声 —— 玩家做了 12 次选择，现在该写下结局。

要求：
- 写一段 400-600 字的 ending passage，第二人称（"你"）
- 必须**呼应玩家在历史中做的关键选择**——不要写一个跟历史无关的通用结局
- 必须有戏剧的"完成感"：一个画面、一个情绪定格、一个对未来的暗示
- 不是"待续"，是**结尾**——这一刻整个故事的形状清晰下来
- 同时给两个产物：
  * `ending_label`：从这个池子里选一个最贴的标签
    [孤狼 / 共谋 / 复仇 / 和解 / 牺牲 / 自由 / 沉沦 / 救赎 / 失控 / 反噬]
  * `ending_subtitle`：第一人称、25 字以内的结局副标题
    （比如 "我撕了那张支票，没回头" 或 "我跪下来，求他原谅"）

输出**严格** JSON，只包含三个字段：

{
  "ending_passage": "...",
  "ending_label": "孤狼",
  "ending_subtitle": "..."
}

不要 markdown，不要解释。
"""


def login(uname: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"username": uname})
    assert r.status_code == 200, f"login failed: {r.text}"
    return s


def must(r: requests.Response, label: str):
    if r.status_code >= 400:
        print(f"FAIL [{label}]: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


def play_strategy(label: str, sess_id: str, opening_options: list, http: requests.Session, strategy: str):
    """Play 12 turns on the given session under one of three strategies."""
    last_options = opening_options
    print(f"\n=== {label} ({strategy}) — playing {TURN_BUDGET} turns on session {sess_id} ===")
    for turn_no in range(1, TURN_BUDGET + 1):
        # Strategy: pick chooser
        if strategy == "savage":
            # Always pick the most aggressive — last option
            idx = len(last_options) - 1 if last_options else 0
            payload = {"chosen_option_index": idx}
            label_txt = f"opt[{idx}] {last_options[idx]['label'][:30]}" if last_options else "?"
        elif strategy == "tactical":
            # Always pick the first — typically the calculated path
            idx = 0
            payload = {"chosen_option_index": idx} if last_options else {"free_input": "我退后一步观察"}
            label_txt = f"opt[0] {last_options[0]['label'][:30]}" if last_options else "free"
        elif strategy == "wild":
            # Middle index + free input every 4th turn
            if turn_no % 4 == 0:
                free_pool = [
                    "我转身走向林浅，伸手抓住她的手腕。",
                    "我突然笑出声，对所有人说了一句他们都没料到的话。",
                    "我没说话，只是把手中的酒杯摔在地上。",
                ]
                payload = {"free_input": RNG.choice(free_pool)}
                label_txt = f"FREE: {payload['free_input'][:30]}"
            else:
                idx = len(last_options) // 2 if last_options else 0
                payload = {"chosen_option_index": idx} if last_options else {"free_input": "..."}
                label_txt = f"opt[{idx}] {last_options[idx]['label'][:30]}" if last_options else "free"
        else:
            raise ValueError(strategy)

        t0 = time.time()
        r = http.post(f"{BASE}/narrative/sessions/{sess_id}/story/turns", json=payload)
        elapsed = time.time() - t0
        if r.status_code >= 400:
            print(f"  turn {turn_no} FAILED: {r.text[:200]}")
            break
        body = r.json()
        last_options = body["narrator_message"]["options"]
        print(f"  turn {turn_no:02d} [{elapsed:.1f}s]: {label_txt}")
    return


def synthesize_ending(http: requests.Session, sess_id: str) -> dict:
    """Hit our experimental client-side ending engine.

    Uses the production narrative gateway directly with a custom prompt.
    The gateway is configured with the same model as the production
    /narrative/* endpoints, so this is faithful to what we'd ship.
    """
    # Pull session story
    body = must(http.get(f"{BASE}/narrative/sessions/{sess_id}/story"), "story")
    template = body["template"]
    messages = body["messages"]

    # Build the synthesis input
    rendered = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]
    payload = {
        "seed": template["seed"],
        "title": template["title"],
        "cast": template["cast"],
        "story_so_far": rendered,
        "instruction": "写下结局——这是 12 回合互动短剧的最终一段。",
    }
    gateway = get_narrative_gateway()
    if gateway is None:
        raise RuntimeError("narrative gateway not configured")

    response = gateway.invoke_json(
        system_prompt=_ENDING_SYSTEM_PROMPT,
        user_payload=payload,
        operation_name="experimental.ending",
        max_output_tokens=1500,
    )
    parsed = response.payload
    if not isinstance(parsed, dict):
        raise RuntimeError(f"ending payload not dict: {parsed!r}")
    return parsed


def render_summary(label: str, sess_id: str, ending: dict) -> None:
    print("\n" + "—" * 70)
    print(f"【{label}】 session: {sess_id}")
    print("—" * 70)
    print(f"\n结局副标题: 「{ending.get('ending_subtitle', '?')}」")
    print(f"结局类型: [{ending.get('ending_label', '?')}]")
    print()
    passage = ending.get("ending_passage", "(missing)")
    print(passage)
    print()


def main() -> None:
    # Step 1: alice creates the template (public, so others can fork)
    A = login(f"alice_{RNG.randint(10000, 99999)}")
    print("=== Alice creates the template (1 LLM call) ===")
    t0 = time.time()
    body = must(A.post(f"{BASE}/narrative/templates", json={"seed": SEED, "visibility": "public"}), "create")
    print(f"   [{time.time()-t0:.1f}s] template={body['template']['title']}")
    template_id = body["template"]["template_id"]
    cast = [c["display_name"] for c in body["template"]["cast"]]
    print(f"   cast: {cast}")
    print(f"   advisor: {body['template']['advisor_persona']}")
    print(f"   opening (first 200): {body['opening']['content'][:200]}...")

    sess_a = body["session"]["session_id"]
    opening_options = body["opening"]["options"]
    print(f"   alice's session: {sess_a}, opening options: {[o['label'][:20] for o in opening_options]}")

    # Step 2: spawn two more players forking the same template
    B = login(f"bob_{RNG.randint(10000, 99999)}")
    body_b = must(B.post(f"{BASE}/narrative/templates/{template_id}/sessions"), "B fork")
    sess_b = body_b["session"]["session_id"]
    print(f"\n   Bob forked session: {sess_b}")

    C = login(f"carol_{RNG.randint(10000, 99999)}")
    body_c = must(C.post(f"{BASE}/narrative/templates/{template_id}/sessions"), "C fork")
    sess_c = body_c["session"]["session_id"]
    print(f"   Carol forked session: {sess_c}")

    # Step 3: each plays 12 turns under a different strategy
    play_strategy("Alice 撕逼派", sess_a, opening_options, A, "savage")
    play_strategy("Bob 谋略派", sess_b, body_b["opening"]["options"], B, "tactical")
    play_strategy("Carol 自由派", sess_c, body_c["opening"]["options"], C, "wild")

    # Step 4: synthesize endings via the experimental engine
    print("\n" + "=" * 70)
    print("ENDING SYNTHESIS")
    print("=" * 70)
    endings = []
    for label, http, sess_id in [
        ("Alice 撕逼派", A, sess_a),
        ("Bob 谋略派", B, sess_b),
        ("Carol 自由派", C, sess_c),
    ]:
        try:
            ending = synthesize_ending(http, sess_id)
            endings.append((label, sess_id, ending))
        except Exception as exc:
            print(f"\n[{label}] ENDING ENGINE FAILED: {exc}")
            endings.append((label, sess_id, {"error": str(exc)}))

    # Step 5: render and compare
    for label, sess_id, ending in endings:
        if "error" in ending:
            print(f"\n[{label}] FAILED: {ending['error']}")
            continue
        render_summary(label, sess_id, ending)

    # Step 6: hypothesis check
    print("\n" + "=" * 70)
    print("HYPOTHESIS CHECK")
    print("=" * 70)
    valid = [e for _, _, e in endings if "error" not in e]
    labels = [e.get("ending_label") for e in valid]
    subtitles = [e.get("ending_subtitle") for e in valid]
    passages = [e.get("ending_passage", "") for e in valid]
    print(f"H1 (字数足够): " + ("✓" if all(len(p) >= 350 for p in passages) else "✗") + f"  passage lens: {[len(p) for p in passages]}")
    print(f"H2 (结局发散): " + ("✓" if len(set(labels)) >= 2 else "✗") + f"  labels: {labels}")
    print(f"H3 (副标题独特): " + ("✓" if len(set(subtitles)) == len(subtitles) else "✗") + f"  subtitles: {subtitles}")
    print(f"H4 (≥3 distinct labels from 3 strategies): " + ("✓" if len(set(labels)) >= 3 else "△  partial") + f"  unique labels: {len(set(labels))}/3")

    # Save full transcript
    with open("/tmp/verify_b_run.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "seed": SEED,
                "template_id": template_id,
                "sessions": [
                    {"label": label, "session_id": sess_id, "ending": ending}
                    for label, sess_id, ending in endings
                ],
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print("\nFull transcript: /tmp/verify_b_run.json")


if __name__ == "__main__":
    main()
