"""Tests for world-level play statistics: play_count, unique_player_count, ending_distribution.

We test the storage layer directly because the runtime path that fires these
stat updates is large and exercised elsewhere — the question this file answers
is whether the *accounting* logic is correct given that the runtime fires it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from tests.test_story_library_api import _publish_source


def _make_storage(tmp_path) -> SQLiteStoryLibraryStorage:
    return SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3"))


def _publish(storage: SQLiteStoryLibraryStorage, *, source_job_id: str = "job-stats-1") -> str:
    """Publish a record using the same factory the rest of the test suite uses."""
    source = _publish_source(source_job_id)
    from rpg_backend.library.contracts import PublishedStoryRecord
    from rpg_backend.library.service import StoryLibraryService

    service = StoryLibraryService(storage)
    card = service.publish_story(
        owner_user_id="usr_owner_1",
        source_job_id=source.source_job_id,
        prompt_seed=source.prompt_seed,
        summary=source.summary,
        preview=source.preview,
        bundle=source.bundle,
        visibility="public",
    )
    assert isinstance(card, type(card))  # type: ignore[arg-type]
    # Sanity: the record we just stored must be readable.
    record = storage.get_story(card.story_id)
    assert isinstance(record, PublishedStoryRecord)
    return card.story_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_play_count_increments_for_each_completion(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    story_id = _publish(storage)
    record = storage.get_story(story_id)
    assert record is not None
    assert record.story.play_count == 0
    assert record.story.unique_player_count == 0
    assert record.story.ending_distribution == {}

    storage.record_play_completion(
        story_id=story_id, player_user_id="usr_alice", ending_id="lovers", completed_at=_now()
    )
    storage.record_play_completion(
        story_id=story_id, player_user_id="usr_bob", ending_id="lovers", completed_at=_now()
    )
    storage.record_play_completion(
        story_id=story_id, player_user_id="usr_bob", ending_id="rivals", completed_at=_now()
    )

    record = storage.get_story(story_id)
    assert record is not None
    assert record.story.play_count == 3
    assert record.story.ending_distribution == {"lovers": 2, "rivals": 1}


def test_unique_player_count_dedupes_logged_in_players(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    story_id = _publish(storage, source_job_id="job-stats-unique")

    # Alice plays twice — should count as 1 unique.
    for _ in range(2):
        storage.record_play_completion(
            story_id=story_id, player_user_id="usr_alice", ending_id="lovers", completed_at=_now()
        )
    # Bob plays once — bumps unique to 2.
    storage.record_play_completion(
        story_id=story_id, player_user_id="usr_bob", ending_id="rivals", completed_at=_now()
    )

    record = storage.get_story(story_id)
    assert record is not None
    assert record.story.play_count == 3
    assert record.story.unique_player_count == 2


def test_anonymous_plays_do_not_count_unique_players(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    story_id = _publish(storage, source_job_id="job-stats-anon")

    # Three anonymous plays + one real player.
    for _ in range(3):
        storage.record_play_completion(
            story_id=story_id, player_user_id=None, ending_id="lovers", completed_at=_now()
        )
    storage.record_play_completion(
        story_id=story_id, player_user_id="usr_alice", ending_id="lovers", completed_at=_now()
    )

    record = storage.get_story(story_id)
    assert record is not None
    assert record.story.play_count == 4
    assert record.story.unique_player_count == 1  # only Alice
    assert record.story.ending_distribution == {"lovers": 4}


def test_ending_distribution_caps_unique_keys(tmp_path) -> None:
    """Junk ending_ids shouldn't grow the dict without bound."""
    storage = _make_storage(tmp_path)
    story_id = _publish(storage, source_job_id="job-stats-cap")
    cap = storage._ENDING_DIST_MAX_KEYS  # type: ignore[attr-defined]

    # Fill exactly to the cap.
    for i in range(cap):
        storage.record_play_completion(
            story_id=story_id,
            player_user_id=None,
            ending_id=f"ending_{i}",
            completed_at=_now(),
        )
    # Now add an ending past the cap — should be dropped.
    storage.record_play_completion(
        story_id=story_id,
        player_user_id=None,
        ending_id="overflow_ending",
        completed_at=_now(),
    )
    # Existing key gets bumped though.
    storage.record_play_completion(
        story_id=story_id,
        player_user_id=None,
        ending_id="ending_0",
        completed_at=_now(),
    )

    record = storage.get_story(story_id)
    assert record is not None
    assert len(record.story.ending_distribution) == cap
    assert "overflow_ending" not in record.story.ending_distribution
    assert record.story.ending_distribution["ending_0"] == 2
    # All increments still rolled into play_count.
    assert record.story.play_count == cap + 2


def test_ending_id_blank_falls_back_to_unknown(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    story_id = _publish(storage, source_job_id="job-stats-blank")

    storage.record_play_completion(
        story_id=story_id, player_user_id=None, ending_id="", completed_at=_now()
    )
    storage.record_play_completion(
        story_id=story_id, player_user_id=None, ending_id="   ", completed_at=_now()
    )

    record = storage.get_story(story_id)
    assert record is not None
    assert record.story.ending_distribution == {"unknown": 2}


def test_ending_id_too_long_is_truncated(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    story_id = _publish(storage, source_job_id="job-stats-long")
    cap = storage._ENDING_ID_MAX_LEN  # type: ignore[attr-defined]
    long_id = "x" * (cap + 50)

    storage.record_play_completion(
        story_id=story_id, player_user_id=None, ending_id=long_id, completed_at=_now()
    )

    record = storage.get_story(story_id)
    assert record is not None
    keys = list(record.story.ending_distribution.keys())
    assert len(keys) == 1
    assert len(keys[0]) == cap


def test_record_completion_on_missing_story_is_noop(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    # Should not raise — silently noop.
    storage.record_play_completion(
        story_id="does-not-exist",
        player_user_id="usr_alice",
        ending_id="lovers",
        completed_at=_now(),
    )
