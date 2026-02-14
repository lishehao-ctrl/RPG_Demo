from app.modules.llm.prompts import build_narrative_prompt


def build_step_prompt(memory_summary: str, branch_result: dict, character_compact: list[dict], player_input: str, classification: dict) -> str:
    return build_narrative_prompt(
        memory_summary=memory_summary,
        branch_result=branch_result,
        character_compact=character_compact,
        player_input=player_input,
        classification=classification,
    )
