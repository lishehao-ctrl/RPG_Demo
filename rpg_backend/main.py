from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from rpg_backend.author.contracts import (
    AuthorJobCreateRequest,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
)
from rpg_backend.author.gateway import AuthorGatewayError
from rpg_backend.author.jobs import AuthorJobService

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
