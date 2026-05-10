from rpg_backend.narrative.engine import _parse_options


def test_parse_options_normalizes_chinese_intent_tags_for_english_templates() -> None:
    options = _parse_options(
        [
            {"label": "[反将] Show the burner phone feed", "hint": "Risk", "handle": "show feed"},
            {"label": "[挑拨] Signal Chen to stand up", "hint": "", "handle": "signal Chen"},
            {"label": "[妥协] Take the pen and sign", "hint": "", "handle": "sign"},
        ],
        language="en",
    )

    assert [o.label for o in options] == [
        "[Counter] Show the burner phone feed",
        "[Provoke] Signal Chen to stand up",
        "[Yield] Take the pen and sign",
    ]


def test_parse_options_normalizes_english_intent_tags_for_chinese_templates() -> None:
    options = _parse_options(
        [
            {"label": "[Counter] 亮出手机证据", "hint": "", "handle": "亮证据"},
            {"label": "[Probe] 试探董事态度", "hint": "", "handle": "试探"},
        ],
        language="zh",
    )

    assert [o.label for o in options] == [
        "[反将] 亮出手机证据",
        "[试探] 试探董事态度",
    ]


def test_parse_options_clips_long_labels_at_word_boundary() -> None:
    options = _parse_options(
        [
            {
                "label": "[Counter] Threaten to leak Chen's embezzlement evidence publicly at the podium",
                "hint": "High risk",
                "handle": "leak evidence",
            }
        ],
        language="en",
    )

    assert options[0].label == "[Counter] Threaten to leak Chen's embezzlement evidence..."
    assert len(options[0].label) <= 60
