from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from rpg_backend.author.display import theme_label, topology_label
from rpg_backend.author_v2.product_adapters import play_overview_from_package
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.config import Settings, get_settings
from rpg_backend.library.contracts import (
    PublishedStoryCard,
    PublishedStoryDetailResponse,
    PublishedStoryListFacets,
    PublishedStoryListMeta,
    PublishedStoryListView,
    PublishedStoryPlayOverview,
    PublishedStoryPresentation,
    PublishedStoryListResponse,
    PublishedStoryListSort,
    PublishedStoryRecord,
    StoryVisibility,
    UpdateStoryVisibilityRequest,
)
from rpg_backend.library.storage import SQLiteStoryLibraryStorage


class LibraryServiceError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class StoryLibraryService:
    def __init__(self, storage: SQLiteStoryLibraryStorage) -> None:
        self._storage = storage
        self._lock = Lock()

    @staticmethod
    def _build_story_card(
        *,
        story_id: str,
        summary,
        preview,
        published_at: datetime,
        visibility: StoryVisibility = "private",
        viewer_can_manage: bool = False,
    ) -> PublishedStoryCard:
        return PublishedStoryCard(
            story_id=story_id,
            title=summary.title,
            one_liner=summary.one_liner,
            premise=summary.premise,
            theme=summary.theme,
            tone=summary.tone,
            npc_count=summary.npc_count,
            beat_count=summary.beat_count,
            topology=topology_label(preview.structure.cast_topology),
            visibility=visibility,
            viewer_can_manage=viewer_can_manage,
            published_at=published_at,
        )

    @staticmethod
    def _build_dossier_ref(story_id: str) -> str:
        return f"Dossier N° {story_id[:3].upper()}"

    @classmethod
    def _build_story_presentation(
        cls,
        *,
        record: PublishedStoryRecord,
        engine_label: str,
    ) -> PublishedStoryPresentation:
        return PublishedStoryPresentation(
            dossier_ref=cls._build_dossier_ref(record.story.story_id),
            status="open_for_play",
            status_label="Open for play",
            classification_label=theme_label(record.preview.theme.primary_theme),
            engine_label=engine_label,
            visibility=record.visibility,
            viewer_can_manage=record.story.viewer_can_manage,
        )

    @staticmethod
    def _can_access(record: PublishedStoryRecord, *, actor_user_id: str | None) -> bool:
        return record.visibility == "public" or (
            actor_user_id is not None and record.owner_user_id == actor_user_id
        )

    @staticmethod
    def _with_viewer_story_fields(record: PublishedStoryRecord, *, actor_user_id: str | None) -> PublishedStoryRecord:
        can_manage = actor_user_id is not None and record.owner_user_id == actor_user_id
        updated_story = record.story.model_copy(update={"viewer_can_manage": can_manage})
        return record.model_copy(update={"story": updated_story})

    @staticmethod
    def _build_play_overview(record: PublishedStoryRecord) -> tuple[PublishedStoryPlayOverview, str]:
        protagonist, opening_narration, runtime_profile, runtime_profile_label, max_turns = play_overview_from_package(record.bundle)
        return (
            PublishedStoryPlayOverview(
                protagonist=protagonist,
                opening_narration=opening_narration,
                runtime_profile=runtime_profile,
                runtime_profile_label=runtime_profile_label,
                play_length_preset=record.bundle.compiled_play_plan.play_length_preset,
                max_turns=max_turns,
            ),
            "Relationship Drama V2 runtime",
        )

    def publish_story(
        self,
        *,
        owner_user_id: str,
        source_job_id: str,
        prompt_seed: str,
        summary,
        preview,
        bundle,
        visibility: StoryVisibility = "private",
    ) -> PublishedStoryCard:
        resolved_owner_user_id = owner_user_id
        with self._lock:
            existing = self._storage.get_by_source_job_id(source_job_id)
            if existing is not None:
                return existing.story.model_copy(update={"viewer_can_manage": existing.owner_user_id == resolved_owner_user_id})
            if not isinstance(bundle, RelationshipDramaV2Package):
                raise LibraryServiceError(
                    code="story_package_unsupported",
                    message="only relationship_drama_v2 package can be published",
                    status_code=400,
                )
            published_at = datetime.now(timezone.utc)
            package_version = "relationship_drama_v2"
            resolved_summary = summary
            resolved_preview = preview
            record = PublishedStoryRecord(
                story=self._build_story_card(
                    story_id=str(uuid4()),
                    summary=resolved_summary,
                    preview=resolved_preview,
                    published_at=published_at,
                    visibility=visibility,
                    viewer_can_manage=True,
                ),
                owner_user_id=resolved_owner_user_id,
                source_job_id=source_job_id,
                prompt_seed=prompt_seed,
                visibility=visibility,
                package_version=package_version,
                summary=resolved_summary,
                preview=resolved_preview,
                bundle=bundle,
            )
            try:
                inserted = self._storage.insert_story(record)
            except sqlite3.IntegrityError:
                existing = self._storage.get_by_source_job_id(source_job_id)
                if existing is None:
                    raise
                return existing.story
        return inserted.story

    @staticmethod
    def _decode_cursor(
        cursor: str | None,
        *,
        query: str | None,
        theme: str | None,
        view: PublishedStoryListView,
        sort: PublishedStoryListSort,
    ) -> int:
        if cursor is None:
            return 0
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8"))
        except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
            raise LibraryServiceError(
                code="story_cursor_invalid",
                message="story cursor is invalid",
                status_code=400,
            ) from exc
        if (
            payload.get("query") != (query or None)
            or payload.get("theme") != (theme or None)
            or payload.get("view") != view
            or payload.get("sort") != sort
        ):
            raise LibraryServiceError(
                code="story_cursor_invalid",
                message="story cursor does not match the current query",
                status_code=400,
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise LibraryServiceError(
                code="story_cursor_invalid",
                message="story cursor is invalid",
                status_code=400,
            )
        return offset

    @staticmethod
    def _encode_cursor(
        *,
        offset: int,
        query: str | None,
        theme: str | None,
        view: PublishedStoryListView,
        sort: PublishedStoryListSort,
    ) -> str:
        payload = {
            "offset": offset,
            "query": query or None,
            "theme": theme or None,
            "view": view,
            "sort": sort,
        }
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("utf-8")

    def list_stories(
        self,
        *,
        actor_user_id: str | None = None,
        query: str | None = None,
        theme: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort: PublishedStoryListSort | None = None,
        view: PublishedStoryListView = "accessible",
    ) -> PublishedStoryListResponse:
        if actor_user_id is None and view == "mine":
            raise LibraryServiceError(
                code="auth_session_required",
                message="Sign in required.",
                status_code=401,
            )
        normalized_query = (query or "").strip() or None
        normalized_theme = (theme or "").strip() or None
        resolved_sort: PublishedStoryListSort = sort or ("relevance" if normalized_query else "published_at_desc")
        include_public = actor_user_id is not None and view != "mine"
        public_only = view == "public" or actor_user_id is None
        offset = self._decode_cursor(
            cursor,
            query=normalized_query,
            theme=normalized_theme,
            view=view,
            sort=resolved_sort,
        )
        page = self._storage.list_stories(
            actor_user_id=actor_user_id,
            query=normalized_query,
            theme=normalized_theme,
            limit=limit,
            offset=offset,
            sort=resolved_sort,
            include_public=include_public,
            public_only=public_only,
        )
        next_cursor = (
            self._encode_cursor(
                offset=page.next_offset,
                query=normalized_query,
                theme=normalized_theme,
                view=view,
                sort=resolved_sort,
            )
            if page.next_offset is not None
            else None
        )
        return PublishedStoryListResponse(
            stories=[self._with_viewer_story_fields(record, actor_user_id=actor_user_id).story for record in page.records],
            meta=PublishedStoryListMeta(
                query=normalized_query,
                theme=normalized_theme,
                view=view,
                sort=resolved_sort,
                limit=limit,
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
                total=page.total,
            ),
            facets=PublishedStoryListFacets(themes=page.theme_facets),
        )

    def get_story_detail(self, story_id: str, *, actor_user_id: str | None = None) -> PublishedStoryDetailResponse:
        record = self._storage.get_story(story_id)
        if record is None or not self._can_access(record, actor_user_id=actor_user_id):
            raise LibraryServiceError(
                code="story_not_found",
                message=f"story '{story_id}' was not found",
                status_code=404,
            )
        visible_record = self._with_viewer_story_fields(record, actor_user_id=actor_user_id)
        play_overview, engine_label = self._build_play_overview(visible_record)
        return PublishedStoryDetailResponse(
            story=visible_record.story,
            preview=visible_record.preview,
            presentation=self._build_story_presentation(record=visible_record, engine_label=engine_label),
            play_overview=play_overview,
        )

    def get_story_record(self, story_id: str, *, actor_user_id: str | None = None) -> PublishedStoryRecord:
        record = self._storage.get_story(story_id)
        if record is None or not self._can_access(record, actor_user_id=actor_user_id):
            raise LibraryServiceError(
                code="story_not_found",
                message=f"story '{story_id}' was not found",
                status_code=404,
            )
        return self._with_viewer_story_fields(record, actor_user_id=actor_user_id)

    def update_story_visibility(
        self,
        *,
        actor_user_id: str | None = None,
        story_id: str,
        request: UpdateStoryVisibilityRequest,
    ) -> PublishedStoryCard:
        if actor_user_id is None:
            raise LibraryServiceError(
                code="auth_session_required",
                message="Sign in required.",
                status_code=401,
            )
        with self._lock:
            record = self._storage.get_story(story_id)
            if record is None or record.owner_user_id != actor_user_id:
                raise LibraryServiceError(
                    code="story_not_found",
                    message=f"story '{story_id}' was not found",
                    status_code=404,
                )
            updated = record.model_copy(update={"visibility": request.visibility})
            updated_story = updated.story.model_copy(update={"visibility": request.visibility, "viewer_can_manage": True})
            updated = updated.model_copy(update={"story": updated_story})
            self._storage.update_story_visibility(story_id=story_id, visibility=request.visibility)
            return updated.story

    def delete_story(self, *, actor_user_id: str | None = None, story_id: str) -> None:
        if actor_user_id is None:
            raise LibraryServiceError(
                code="auth_session_required",
                message="Sign in required.",
                status_code=401,
            )
        with self._lock:
            record = self._storage.get_story(story_id)
            if record is None or record.owner_user_id != actor_user_id:
                raise LibraryServiceError(
                    code="story_not_found",
                    message=f"story '{story_id}' was not found",
                    status_code=404,
                )
            deleted = self._storage.delete_story(story_id=story_id, owner_user_id=actor_user_id)
            if not deleted:
                raise LibraryServiceError(
                    code="story_not_found",
                    message=f"story '{story_id}' was not found",
                    status_code=404,
                )


def get_story_library_service(settings: Settings | None = None) -> StoryLibraryService:
    resolved = settings or get_settings()
    return StoryLibraryService(
        storage=SQLiteStoryLibraryStorage(resolved.story_library_db_path),
    )
