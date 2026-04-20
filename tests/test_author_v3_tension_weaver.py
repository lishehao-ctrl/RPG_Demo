from __future__ import annotations

import pytest

from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.relationship_matrix import build_relationship_matrix
from rpg_backend.author_v3.tension_weaver import (
    HookRecord,
    OrganicSecret,
    SecretChain,
    TensionWeb,
    map_to_legacy_secret_class,
    score_narrative_potential,
    weave_secrets,
)
from rpg_backend.author_v3.world_forge import forge_world


@pytest.fixture
def config() -> WorldConfiguration:
    return forge_world("董事会权力斗争")


@pytest.fixture
def matrix(config: WorldConfiguration) -> RelationshipMatrix:
    return build_relationship_matrix(config)


@pytest.fixture
def tension_web(config: WorldConfiguration, matrix: RelationshipMatrix) -> TensionWeb:
    return weave_secrets(config, matrix)


class TestWeaveSecretsDeterministic:
    def test_returns_tension_web(self, tension_web: TensionWeb) -> None:
        assert isinstance(tension_web, TensionWeb)

    def test_has_secrets(self, tension_web: TensionWeb) -> None:
        assert len(tension_web.secrets) >= 5

    def test_secret_ids_unique(self, tension_web: TensionWeb) -> None:
        ids = [s.secret_id for s in tension_web.secrets]
        assert len(ids) == len(set(ids))

    def test_holders_are_valid_characters(
        self, tension_web: TensionWeb, config: WorldConfiguration
    ) -> None:
        char_ids = {c.character_id for c in config.characters}
        for secret in tension_web.secrets:
            for holder in secret.holders:
                assert holder in char_ids, f"holder {holder!r} not in characters"

    def test_knowers_are_valid_characters(
        self, tension_web: TensionWeb, config: WorldConfiguration
    ) -> None:
        char_ids = {c.character_id for c in config.characters}
        for secret in tension_web.secrets:
            for knower in secret.knowers:
                assert knower in char_ids, f"knower {knower!r} not in characters"

    def test_lethality_in_range(self, tension_web: TensionWeb) -> None:
        for secret in tension_web.secrets:
            assert 0.0 <= secret.lethality_score <= 1.0

    def test_has_hooks(self, tension_web: TensionWeb) -> None:
        assert len(tension_web.hooks) >= 3

    def test_hook_characters_valid(
        self, tension_web: TensionWeb, config: WorldConfiguration
    ) -> None:
        char_ids = {c.character_id for c in config.characters}
        for hook in tension_web.hooks:
            assert hook.holder_id in char_ids
            assert hook.target_id in char_ids
            assert hook.holder_id != hook.target_id

    def test_hook_source_secrets_valid(self, tension_web: TensionWeb) -> None:
        secret_ids = {s.secret_id for s in tension_web.secrets}
        for hook in tension_web.hooks:
            assert hook.source_secret_id in secret_ids

    def test_has_chains(self, tension_web: TensionWeb) -> None:
        assert len(tension_web.chains) >= 1

    def test_chain_secrets_valid(self, tension_web: TensionWeb) -> None:
        secret_ids = {s.secret_id for s in tension_web.secrets}
        for chain in tension_web.chains:
            assert chain.trigger_secret_id in secret_ids
            assert chain.unlocks_secret_id in secret_ids
            assert chain.trigger_secret_id != chain.unlocks_secret_id

    def test_narrative_potential_above_threshold(self, tension_web: TensionWeb) -> None:
        assert tension_web.narrative_potential_score >= 0.5

    def test_every_character_involved(
        self, tension_web: TensionWeb, config: WorldConfiguration
    ) -> None:
        involved: set[str] = set()
        for secret in tension_web.secrets:
            involved.update(secret.holders)
            involved.update(secret.knowers)
        char_ids = {c.character_id for c in config.characters}
        assert involved >= char_ids, f"missing: {char_ids - involved}"


class TestScoreNarrativePotential:
    def test_range(
        self, tension_web: TensionWeb, config: WorldConfiguration, matrix: RelationshipMatrix
    ) -> None:
        score = score_narrative_potential(tension_web, config, matrix)
        assert 0.0 <= score <= 1.0

    def test_matches_web_score(
        self, tension_web: TensionWeb, config: WorldConfiguration, matrix: RelationshipMatrix
    ) -> None:
        score = score_narrative_potential(tension_web, config, matrix)
        assert score == tension_web.narrative_potential_score


class TestLegacySecretClassMapping:
    def test_all_secrets_have_legacy_class(self, tension_web: TensionWeb) -> None:
        for secret in tension_web.secrets:
            assert secret.legacy_secret_class is not None

    def test_keyword_black_ledger(self) -> None:
        s = OrganicSecret(
            secret_id="test", title="黑账记录", description="财务黑账",
            holders=["a"], discovery_conditions=["审计"], exposure_consequence_chains=["破产"],
            lethality_score=0.5,
        )
        assert map_to_legacy_secret_class(s) == "black_ledger"

    def test_keyword_old_recording(self) -> None:
        s = OrganicSecret(
            secret_id="test", title="秘密录音", description="关键录音内容",
            holders=["a"], discovery_conditions=["泄露"], exposure_consequence_chains=["曝光"],
            lethality_score=0.5,
        )
        assert map_to_legacy_secret_class(s) == "old_recording"

    def test_keyword_contract_flip(self) -> None:
        s = OrganicSecret(
            secret_id="test", title="收购合同", description="并购内幕",
            holders=["a"], discovery_conditions=["审查"], exposure_consequence_chains=["失败"],
            lethality_score=0.5,
        )
        assert map_to_legacy_secret_class(s) == "contract_flip"

    def test_default_fallback(self) -> None:
        s = OrganicSecret(
            secret_id="test", title="普通秘密", description="一般性隐情",
            holders=["a"], discovery_conditions=["偶然"], exposure_consequence_chains=["尴尬"],
            lethality_score=0.5,
        )
        assert map_to_legacy_secret_class(s) == "black_ledger"


class TestTensionWebValidation:
    def test_rejects_empty_secrets(self) -> None:
        with pytest.raises(Exception):
            TensionWeb(secrets=[], hooks=[], chains=[], narrative_potential_score=0.5)

    def test_rejects_single_secret(self) -> None:
        with pytest.raises(Exception):
            TensionWeb(
                secrets=[
                    OrganicSecret(
                        secret_id="only", title="唯一秘密", description="描述",
                        holders=["a"], discovery_conditions=["条件"],
                        exposure_consequence_chains=["后果"], lethality_score=0.5,
                    )
                ],
                hooks=[], chains=[], narrative_potential_score=0.5,
            )
