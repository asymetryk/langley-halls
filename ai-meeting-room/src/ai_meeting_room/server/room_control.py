"""HTTP host control API for a running interactive meeting."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from ai_meeting_room.config import get_settings
from ai_meeting_room.room.controller import RoomController


def create_room_control_app(controller: RoomController) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Meeting Room Control", version="0.1.0")

    def _auth(authorization: str | None = Header(default=None)) -> None:
        token = settings.room_control_token
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(_auth)])
    async def status() -> dict[str, Any]:
        return controller.status()

    @app.post("/kick/{agent_key}", dependencies=[Depends(_auth)])
    async def kick(agent_key: str) -> dict[str, Any]:
        try:
            return await controller.kick(agent_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/invite/{agent_key}", dependencies=[Depends(_auth)])
    async def invite(agent_key: str) -> dict[str, Any]:
        try:
            return await controller.invite(agent_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/chair/{agent_key}", dependencies=[Depends(_auth)])
    async def chair(agent_key: str) -> dict[str, Any]:
        try:
            return await controller.set_chair(agent_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/pause", dependencies=[Depends(_auth)])
    async def pause() -> dict[str, Any]:
        return controller.pause()

    @app.post("/resume", dependencies=[Depends(_auth)])
    async def resume() -> dict[str, Any]:
        return controller.resume()

    return app
