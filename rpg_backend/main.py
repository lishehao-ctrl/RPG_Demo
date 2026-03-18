from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from rpg_backend.author.contracts import (
    AuthorBundleRequest,
    AuthorBundleResponse,
    AuthorJobCreateRequest,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorJobTokenUsageDetailResponse,
    AuthorJobTokenUsageResponse,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
)
from rpg_backend.author.gateway import AuthorGatewayError, get_author_llm_gateway
from rpg_backend.author.jobs import AuthorJobService
from rpg_backend.author.workflow import run_author_bundle

app = FastAPI(title="rpg-demo-rebuild")
author_job_service = AuthorJobService()


@app.exception_handler(AuthorGatewayError)
def handle_gateway_error(_: Request, exc: AuthorGatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/author/design-bundles", response_model=AuthorBundleResponse)
def create_design_bundle(payload: AuthorBundleRequest) -> AuthorBundleResponse:
    result = run_author_bundle(payload, gateway=get_author_llm_gateway())
    return AuthorBundleResponse(run_id=result.run_id, bundle=result.bundle)


@app.post("/author/story-previews", response_model=AuthorPreviewResponse)
def create_story_preview(payload: AuthorPreviewRequest) -> AuthorPreviewResponse:
    return author_job_service.create_preview(payload)


@app.post("/author/jobs", response_model=AuthorJobStatusResponse)
def create_author_job(payload: AuthorJobCreateRequest) -> AuthorJobStatusResponse:
    return author_job_service.create_job(payload)


@app.get("/author/jobs/{job_id}", response_model=AuthorJobStatusResponse)
def get_author_job(job_id: str) -> AuthorJobStatusResponse:
    return author_job_service.get_job(job_id)


@app.get("/author/jobs/{job_id}/events")
def stream_author_job_events(job_id: str, last_event_id: int | None = None) -> StreamingResponse:
    return StreamingResponse(
        author_job_service.stream_job_events(job_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/author/jobs/{job_id}/result", response_model=AuthorJobResultResponse)
def get_author_job_result(job_id: str) -> AuthorJobResultResponse:
    return author_job_service.get_job_result(job_id)


@app.get("/author/jobs/{job_id}/token-usage", response_model=AuthorJobTokenUsageResponse)
def get_author_job_token_usage(job_id: str) -> AuthorJobTokenUsageResponse:
    return author_job_service.get_job_token_usage(job_id)


@app.get("/author/jobs/{job_id}/token-usage/detail", response_model=AuthorJobTokenUsageDetailResponse)
def get_author_job_token_usage_detail(job_id: str) -> AuthorJobTokenUsageDetailResponse:
    return author_job_service.get_job_token_usage_detail(job_id)
