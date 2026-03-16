from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rpg_backend.author.contracts import AuthorBundleRequest, AuthorBundleResponse
from rpg_backend.author.gateway import AuthorGatewayError, get_author_llm_gateway
from rpg_backend.author.workflow import run_author_bundle

app = FastAPI(title="rpg-demo-rebuild")


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
