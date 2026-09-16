from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.domain.errors import AriadError
from app.routes import audio, encounters, public

app = FastAPI(title="ARIAD API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AriadError)
def handle_ariad_error(request: Request, exc: AriadError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": exc.code, "message": exc.message, "retryable": exc.retryable},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(encounters.router)
app.include_router(audio.router)
app.include_router(public.router)
