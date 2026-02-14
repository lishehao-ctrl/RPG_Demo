from fastapi import FastAPI

from app.modules.session.router import router as session_router

app = FastAPI(title="RPG Demo Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(session_router)
