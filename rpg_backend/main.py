from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from rpg_backend.auth import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthService,
    AuthServiceError,
    AuthSessionResponse,
    AuthenticatedSession,
    CurrentActorResponse,
)
from rpg_backend.author.contracts import (
    AuthorJobCreateRequest,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
)
from rpg_backend.author.gateway import AuthorGatewayError
from rpg_backend.benchmark.contracts import (
    BenchmarkAuthorJobDiagnosticsResponse,
    BenchmarkPlaySessionDiagnosticsResponse,
)
from rpg_backend.author_v2.product_jobs import ProductAuthorJobService
from rpg_backend.config import get_settings
from rpg_backend.library.contracts import (
    DeleteStoryResponse,
    PublishedStoryCard,
    PublishedStoryDetailResponse,
    PublishedStoryListResponse,
    PublishedStoryListSort,
    PublishedStoryListView,
    StoryVisibility,
    UpdateStoryVisibilityRequest,
)
from rpg_backend.library.service import LibraryServiceError, get_story_library_service
from rpg_backend.play.contracts import (
    PlayDraftIntentRequest,
    PlayDraftIntentResponse,
    PlaySessionHistoryResponse,
    PlaySessionCreateRequest,
    PlaySessionSnapshot,
    PlayTurnRequest,
)
from rpg_backend.play.service import PlayServiceError, PlaySessionService

app = FastAPI(title="rpg-demo-rebuild")
settings = get_settings()
auth_service = AuthService(settings=settings)
author_job_service = ProductAuthorJobService(settings=settings)
story_library_service = get_story_library_service(settings)
play_session_service = PlaySessionService(story_library_service=story_library_service, settings=settings)


def _require_benchmark_api() -> None:
    if not get_settings().enable_benchmark_api:
        raise HTTPException(status_code=404, detail="Not found")


def _apply_session_cookie(response: Response, session: AuthenticatedSession) -> None:
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=session.session_token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.auth_session_cookie_secure,
        samesite=settings.auth_session_cookie_samesite,
        path="/",
        domain=settings.auth_session_cookie_domain,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/",
        domain=settings.auth_session_cookie_domain,
    )


def get_optional_request_session(request: Request) -> AuthenticatedSession | None:
    return auth_service.resolve_session(request)


def get_required_request_session(request: Request) -> AuthenticatedSession:
    return auth_service.require_session(request)


def get_required_request_user(session: AuthenticatedSession = Depends(get_required_request_session)):
    return session.user


@app.exception_handler(AuthorGatewayError)
def handle_gateway_error(_: Request, exc: AuthorGatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(LibraryServiceError)
def handle_library_error(_: Request, exc: LibraryServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(PlayServiceError)
def handle_play_error(_: Request, exc: PlayServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(AuthServiceError)
def handle_auth_error(_: Request, exc: AuthServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/session", response_model=AuthSessionResponse)
def get_auth_session(session: AuthenticatedSession | None = Depends(get_optional_request_session)) -> AuthSessionResponse:
    return auth_service.build_session_response(session)


@app.post("/auth/register", response_model=AuthSessionResponse)
def register_auth_user(payload: AuthRegisterRequest, response: Response) -> AuthSessionResponse:
    session = auth_service.register(payload)
    _apply_session_cookie(response, session)
    return auth_service.build_session_response(session)


@app.post("/auth/login", response_model=AuthSessionResponse)
def login_auth_user(payload: AuthLoginRequest, response: Response) -> AuthSessionResponse:
    session = auth_service.login(payload)
    _apply_session_cookie(response, session)
    return auth_service.build_session_response(session)


@app.post("/auth/logout", status_code=204)
def logout_auth_user(request: Request, response: Response) -> Response:
    auth_service.logout(request)
    _clear_session_cookie(response)
    response.status_code = 204
    return response


@app.get("/me", response_model=CurrentActorResponse)
def get_current_actor(session: AuthenticatedSession = Depends(get_required_request_session)) -> CurrentActorResponse:
    return auth_service.build_current_actor_response(session)


@app.post("/author/story-previews", response_model=AuthorPreviewResponse)
def create_story_preview(
    payload: AuthorPreviewRequest,
    user=Depends(get_required_request_user),
) -> AuthorPreviewResponse:
    return author_job_service.create_preview(payload, actor_user_id=user.user_id)


@app.post("/author/jobs", response_model=AuthorJobStatusResponse)
def create_author_job(
    payload: AuthorJobCreateRequest,
    user=Depends(get_required_request_user),
) -> AuthorJobStatusResponse:
    return author_job_service.create_job(payload, actor_user_id=user.user_id)


@app.get("/author/jobs/{job_id}", response_model=AuthorJobStatusResponse)
def get_author_job(job_id: str, user=Depends(get_required_request_user)) -> AuthorJobStatusResponse:
    return author_job_service.get_job(job_id, actor_user_id=user.user_id)


@app.get("/author/jobs/{job_id}/events")
def stream_author_job_events(
    job_id: str,
    last_event_id: int | None = None,
    user=Depends(get_required_request_user),
) -> StreamingResponse:
    return StreamingResponse(
        author_job_service.stream_job_events(job_id, actor_user_id=user.user_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/author/jobs/{job_id}/result", response_model=AuthorJobResultResponse)
def get_author_job_result(job_id: str, user=Depends(get_required_request_user)) -> AuthorJobResultResponse:
    return author_job_service.get_job_result(job_id, actor_user_id=user.user_id)


@app.post("/author/jobs/{job_id}/publish", response_model=PublishedStoryCard)
def publish_author_job(
    job_id: str,
    visibility: StoryVisibility = Query(default="private"),
    user=Depends(get_required_request_user),
) -> PublishedStoryCard:
    source = author_job_service.get_publishable_job_source(job_id, actor_user_id=user.user_id)
    return story_library_service.publish_story(
        owner_user_id=user.user_id,
        source_job_id=source.source_job_id,
        prompt_seed=source.prompt_seed,
        summary=source.summary,
        preview=source.preview,
        bundle=source.bundle,
        visibility=visibility,
    )


@app.get(
    "/benchmark/author/jobs/{job_id}/diagnostics",
    response_model=BenchmarkAuthorJobDiagnosticsResponse,
)
def get_author_job_diagnostics(
    job_id: str,
    user=Depends(get_required_request_user),
) -> BenchmarkAuthorJobDiagnosticsResponse:
    _require_benchmark_api()
    return author_job_service.get_job_diagnostics(job_id, actor_user_id=user.user_id)


@app.get("/stories", response_model=PublishedStoryListResponse)
def list_stories(
    q: str | None = Query(default=None, max_length=200),
    theme: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    sort: PublishedStoryListSort | None = Query(default=None),
    view: PublishedStoryListView = Query(default="accessible"),
    session: AuthenticatedSession | None = Depends(get_optional_request_session),
) -> PublishedStoryListResponse:
    return story_library_service.list_stories(
        actor_user_id=session.user.user_id if session is not None else None,
        query=q,
        theme=theme,
        limit=limit,
        cursor=cursor,
        sort=sort,
        view=view,
    )


@app.get("/stories/{story_id}", response_model=PublishedStoryDetailResponse)
def get_story(
    story_id: str,
    session: AuthenticatedSession | None = Depends(get_optional_request_session),
) -> PublishedStoryDetailResponse:
    return story_library_service.get_story_detail(
        story_id,
        actor_user_id=session.user.user_id if session is not None else None,
    )


@app.patch("/stories/{story_id}/visibility", response_model=PublishedStoryCard)
def update_story_visibility(
    story_id: str,
    payload: UpdateStoryVisibilityRequest,
    user=Depends(get_required_request_user),
) -> PublishedStoryCard:
    return story_library_service.update_story_visibility(
        actor_user_id=user.user_id,
        story_id=story_id,
        request=payload,
    )


@app.delete("/stories/{story_id}", response_model=DeleteStoryResponse)
def delete_story(
    story_id: str,
    user=Depends(get_required_request_user),
) -> DeleteStoryResponse:
    play_session_service.delete_sessions_for_story(story_id=story_id)
    story_library_service.delete_story(actor_user_id=user.user_id, story_id=story_id)
    return DeleteStoryResponse(story_id=story_id, deleted=True)


@app.post("/play/sessions", response_model=PlaySessionSnapshot)
def create_play_session(
    payload: PlaySessionCreateRequest,
    user=Depends(get_required_request_user),
) -> PlaySessionSnapshot:
    return play_session_service.create_session(payload.story_id, actor_user_id=user.user_id)


@app.get("/play/sessions/{session_id}", response_model=PlaySessionSnapshot)
def get_play_session(
    session_id: str,
    user=Depends(get_required_request_user),
) -> PlaySessionSnapshot:
    return play_session_service.get_session(session_id, actor_user_id=user.user_id)


@app.get("/play/sessions/{session_id}/history", response_model=PlaySessionHistoryResponse)
def get_play_session_history(
    session_id: str,
    user=Depends(get_required_request_user),
) -> PlaySessionHistoryResponse:
    return play_session_service.get_session_history(session_id, actor_user_id=user.user_id)


@app.post("/play/sessions/{session_id}/draft-intent", response_model=PlayDraftIntentResponse)
def draft_play_turn_intent(
    session_id: str,
    payload: PlayDraftIntentRequest,
    user=Depends(get_required_request_user),
) -> PlayDraftIntentResponse:
    return play_session_service.draft_intent(session_id, payload, actor_user_id=user.user_id)


@app.post("/play/sessions/{session_id}/turns", response_model=PlaySessionSnapshot)
def submit_play_turn(
    session_id: str,
    payload: PlayTurnRequest,
    user=Depends(get_required_request_user),
) -> PlaySessionSnapshot:
    return play_session_service.submit_turn(session_id, payload, actor_user_id=user.user_id)


@app.get(
    "/benchmark/play/sessions/{session_id}/diagnostics",
    response_model=BenchmarkPlaySessionDiagnosticsResponse,
)
def get_play_session_diagnostics(
    session_id: str,
    user=Depends(get_required_request_user),
) -> BenchmarkPlaySessionDiagnosticsResponse:
    _require_benchmark_api()
    return play_session_service.get_session_diagnostics(session_id, actor_user_id=user.user_id)
