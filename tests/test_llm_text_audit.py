from __future__ import annotations

from types import SimpleNamespace

from rpg_backend.config import HelperResponsesEndpoint, Settings
from tools.urban_author_play_benchmarks import llm_text_audit as llm_text_audit_tools


def _endpoint(slot_name: str, role: str, *, api_key: str = "test_key") -> HelperResponsesEndpoint:
    return HelperResponsesEndpoint(
        slot_name=slot_name,
        base_url=f"https://{slot_name}.example/v1",
        api_key=api_key,
        model="gpt-5.4-mini",
        use_session_cache=False,
        weight=1.0,
        role=role,  # type: ignore[arg-type]
    )


def test_audit_endpoints_only_keeps_primary_helper(monkeypatch) -> None:
    primary = _endpoint("helper_slot_2", "primary")
    backup = _endpoint("helper_slot_3", "backup")

    class _FakeSettings:
        @staticmethod
        def configured_helper_responses_endpoints() -> tuple[HelperResponsesEndpoint, ...]:
            return (primary, backup)

    monkeypatch.setattr(llm_text_audit_tools, "get_settings", lambda: _FakeSettings())
    endpoints = llm_text_audit_tools._audit_endpoints()
    assert endpoints == (primary,)


def test_llm_text_audit_timeout_default_and_explicit_value() -> None:
    assert Settings.model_fields["responses_timeout_seconds_llm_text_audit"].default == 120.0
    settings = Settings(responses_timeout_seconds_llm_text_audit=120.0)
    assert llm_text_audit_tools._llm_text_audit_timeout_seconds(settings) == 120.0


def test_llm_text_audit_turn_uses_single_helper_endpoint(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    def _fake_turn_eval(active_endpoint, payload):  # noqa: ANN001, ANN201
        return llm_text_audit_tools.LlmTextAuditEndpointResult(
            slot_name=active_endpoint.slot_name,
            base_url=active_endpoint.base_url,
            model=active_endpoint.model,
            status="completed",
            scores={
                "tone_naturalness": 4.0,
                "character_specificity": 4.5,
                "dramatic_tension": 4.0,
                "shell_fidelity": 4.0,
                "consequence_clarity": 3.5,
                "anti_template_stiffness": 3.5,
            },
            strongest_signal="镜头追焦很有压迫。",
            main_issue="中段还可以更狠。",
            flags=["角色反应太泛"],
        )

    monkeypatch.setattr(llm_text_audit_tools, "_evaluate_turn_on_endpoint", _fake_turn_eval)
    record = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_a",
            "persona_id": "baodian",
            "turn_index": 2,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert record.llm_audit_status == "completed"
    assert record.scores is not None
    assert record.scores.character_specificity == 4.5
    assert record.disagreement_index is None
    assert record.flags == ["角色反应太泛"]
    assert len(record.endpoint_results) == 1


def test_llm_text_audit_session_fails_when_single_endpoint_fails(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    def _fake_session_eval(active_endpoint, payload):  # noqa: ANN001, ANN201
        return llm_text_audit_tools.LlmTextAuditEndpointResult(
            slot_name=active_endpoint.slot_name,
            base_url=active_endpoint.base_url,
            model=active_endpoint.model,
            status="failed",
            error="timeout",
        )

    monkeypatch.setattr(llm_text_audit_tools, "_evaluate_session_on_endpoint", _fake_session_eval)
    report = llm_text_audit_tools.evaluate_session_text(
        {
            "case_id": "case_a",
            "persona_id": "qinggan",
            "story_shell_id": "campus_romance",
            "turn_logs": [],
        }
    )

    assert report.llm_audit_status == "failed"
    assert report.scores is None
    assert any(item.status == "failed" for item in report.endpoint_results)


def test_llm_text_audit_round_robin_samples_helper_api_keys(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    settings = Settings(
        helper_responses_api_keys="pool_key_a,pool_key_b",
        responses_timeout_seconds=10.0,
    )
    captured_keys: list[str] = []
    monkeypatch.setattr(llm_text_audit_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    def _fake_invoke_endpoint_json(*, endpoint, instructions, payload, max_output_tokens):  # noqa: ANN001, ANN201
        captured_keys.append(endpoint.api_key)
        return (
            {
                "scores": {
                    "tone_naturalness": 4,
                    "character_specificity": 4,
                    "dramatic_tension": 4,
                    "shell_fidelity": 4,
                    "consequence_clarity": 4,
                    "anti_template_stiffness": 4,
                },
                "strongest_signal": "可。",
                "main_issue": "可。",
                "flags": [],
            },
            "resp_rr",
            10,
            5,
        )

    monkeypatch.setattr(llm_text_audit_tools, "_invoke_endpoint_json", _fake_invoke_endpoint_json)
    _ = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_rr",
            "persona_id": "p1",
            "turn_index": 1,
            "story_shell_id": "campus_romance",
            "segment_role": "opening",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )
    _ = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_rr",
            "persona_id": "p1",
            "turn_index": 2,
            "story_shell_id": "campus_romance",
            "segment_role": "misread",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert captured_keys[:2] == ["pool_key_a", "pool_key_b"]


def test_llm_text_audit_flags_and_scores_are_emitted(monkeypatch) -> None:
    endpoints = (_endpoint("helper_slot_2", "primary"),)
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: endpoints)

    def _fake_invoke_endpoint_json(*, endpoint, instructions, payload, max_output_tokens):  # noqa: ANN001, ANN201
        return (
            {
                "scores": {
                    "tone_naturalness": 6,
                    "character_specificity": 0,
                    "dramatic_tension": 4,
                    "shell_fidelity": 5,
                    "consequence_clarity": 4,
                    "anti_template_stiffness": 2,
                },
                "strongest_signal": "台下换边写得很清楚。",
                "main_issue": "结尾还不够痛。",
                "flags": ["角色反应太泛", "中文语感不足", "不在白名单"],
            },
            "resp_001",
            120,
            80,
        )

    monkeypatch.setattr(llm_text_audit_tools, "_invoke_endpoint_json", _fake_invoke_endpoint_json)
    record = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_b",
            "persona_id": "wenjian",
            "turn_index": 1,
            "story_shell_id": "campus_romance",
            "segment_role": "opening",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert record.llm_audit_status == "completed"
    assert record.scores is not None
    assert record.scores.tone_naturalness == 5.0
    assert record.scores.character_specificity == 1.0
    assert record.flags == ["角色反应太泛", "中文语感不足"]
    assert record.endpoint_results[0].latency_ms >= 0


def test_llm_text_audit_accepts_single_score_payload(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    def _fake_invoke_endpoint_json(*, endpoint, instructions, payload, max_output_tokens):  # noqa: ANN001, ANN201
        return (
            {
                "score": 4.2,
                "rationale": ["台下站队和评审失温写得清楚。", "中段还可以更狠。"],
            },
            "resp_score_only",
            40,
            20,
        )

    monkeypatch.setattr(llm_text_audit_tools, "_invoke_endpoint_json", _fake_invoke_endpoint_json)
    record = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_score_only",
            "persona_id": "probe",
            "turn_index": 1,
            "story_shell_id": "campus_romance",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert record.llm_audit_status == "completed"
    assert record.scores is not None
    assert record.scores.tone_naturalness == 4.2
    assert record.scores.character_specificity == 4.2
    assert record.strongest_signal == "台下站队和评审失温写得清楚。"


def test_llm_text_audit_fails_when_score_payload_missing(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    def _fake_invoke_endpoint_json(*, endpoint, instructions, payload, max_output_tokens):  # noqa: ANN001, ANN201
        return ({"rationale": ["只有解释没有分数。"]}, "resp_missing_score", 20, 10)

    monkeypatch.setattr(llm_text_audit_tools, "_invoke_endpoint_json", _fake_invoke_endpoint_json)
    record = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_missing_score",
            "persona_id": "probe",
            "turn_index": 1,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert record.llm_audit_status == "failed"
    assert record.scores is None
    assert len(record.endpoint_results) == 1
    assert record.endpoint_results[0].status == "failed"
    assert "missing_scores" in str(record.endpoint_results[0].error)


def test_llm_text_audit_build_client_uses_helper_rpm_limit(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    settings = Settings(helper_responses_requests_per_minute=100)
    captured: dict[str, object] = {}

    class _FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            return SimpleNamespace(
                id="resp_fake",
                output_text=(
                    '{"scores":{"tone_naturalness":4,"character_specificity":4,'
                    '"dramatic_tension":4,"shell_fidelity":4,'
                    '"consequence_clarity":4,"anti_template_stiffness":4}}'
                ),
                usage={"input_tokens": 10, "output_tokens": 5},
            )

    def _fake_build_openai_client(**kwargs):  # noqa: ANN001, ANN201
        captured.update(kwargs)
        return SimpleNamespace(responses=_FakeResponses())

    monkeypatch.setattr(llm_text_audit_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_text_audit_tools, "build_openai_client", _fake_build_openai_client)
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    _ = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_c",
            "persona_id": "baodian",
            "turn_index": 1,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert captured["requests_per_minute"] == 100
    assert captured["rate_limit_scope"] == "helper:llm_text_audit"


def test_llm_text_audit_can_enable_web_search_tool(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    settings = Settings(helper_responses_enable_web_search=True)
    captured_create_kwargs: dict[str, object] = {}

    class _FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_create_kwargs.update(kwargs)
            return SimpleNamespace(
                id="resp_web",
                output_text=(
                    '{"scores":{"tone_naturalness":4,"character_specificity":4,'
                    '"dramatic_tension":4,"shell_fidelity":4,'
                    '"consequence_clarity":4,"anti_template_stiffness":4}}'
                ),
                usage={"input_tokens": 8, "output_tokens": 4},
            )

    monkeypatch.setattr(llm_text_audit_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llm_text_audit_tools,
        "build_openai_client",
        lambda **kwargs: SimpleNamespace(responses=_FakeResponses()),
    )
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    _ = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_web",
            "persona_id": "probe",
            "turn_index": 1,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    assert captured_create_kwargs.get("tools") == [{"type": "web_search_preview"}]


def test_llm_text_audit_can_attach_json_content_type_hint(monkeypatch) -> None:
    endpoint = _endpoint("helper_slot_2", "primary")
    settings = Settings(helper_responses_enable_web_search=False, responses_json_content_type_hint=True)
    captured_create_kwargs: dict[str, object] = {}

    class _FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_create_kwargs.update(kwargs)
            return SimpleNamespace(
                id="resp_content_type",
                output_text=(
                    '{"scores":{"tone_naturalness":4,"character_specificity":4,'
                    '"dramatic_tension":4,"shell_fidelity":4,'
                    '"consequence_clarity":4,"anti_template_stiffness":4}}'
                ),
                usage={"input_tokens": 8, "output_tokens": 4},
            )

    monkeypatch.setattr(llm_text_audit_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llm_text_audit_tools,
        "build_openai_client",
        lambda **kwargs: SimpleNamespace(responses=_FakeResponses()),
    )
    monkeypatch.setattr(llm_text_audit_tools, "_audit_endpoints", lambda: (endpoint,))

    _ = llm_text_audit_tools.evaluate_turn_text(
        {
            "case_id": "case_content_type",
            "persona_id": "probe",
            "turn_index": 1,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "text": {"narration": "测试"},
            "signals": {},
        }
    )

    extra_body = dict(captured_create_kwargs.get("extra_body") or {})
    assert extra_body.get("response_format") == {"type": "json_object"}
    assert extra_body.get("content_type") == "json"
