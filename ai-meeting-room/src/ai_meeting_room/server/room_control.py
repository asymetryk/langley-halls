"""HTTP host control API and web dashboard for interactive meetings."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ai_meeting_room.config import get_settings
from ai_meeting_room.room.controller import RoomController
from ai_meeting_room.server.token_server import mint_join_link

STATIC_DIR = Path(__file__).resolve().parent / "static"


class RelaySayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speak: bool = True


class CursorAckRequest(BaseModel):
    msg_ids: list[str] = Field(default_factory=list)


class CursorAgentCompleteRequest(BaseModel):
    msg_ids: list[str] = Field(default_factory=list)
    summary: str = Field(default="", max_length=2000)
    speak: bool = True


def create_room_control_app(controller: RoomController) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Meeting Room Control", version="0.2.0")

    def _auth(authorization: str | None = Header(default=None)) -> None:
        token = settings.room_control_token
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/")
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/meet")
    async def meet_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "meet.html")

    @app.get("/join-token")
    async def join_token(identity: str = "host", name: str | None = None) -> dict[str, Any]:
        display = name or ("You" if identity == "host" else identity.replace("-", " ").title())
        link = mint_join_link(room=settings.meeting_room_name, identity=identity, name=display)
        base = settings.room_control_public_url or f"http://{settings.room_control_host}:{settings.room_control_port}"
        link["meet_url"] = f"{base.rstrip('/')}/meet?identity={identity}&name={quote(display, safe='')}"
        return link

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/join-links", dependencies=[Depends(_auth)])
    async def join_links() -> dict[str, Any]:
        room = settings.meeting_room_name
        links = [
            mint_join_link(room=room, identity="host", name="You"),
            mint_join_link(room=room, identity="brother", name="Brother"),
        ]
        return {
            "room": room,
            "livekit_url": settings.livekit_url,
            "instructions": (
                "Open meet_url in a browser for human camera + audio. "
                "meet.livekit.io/custom works but often skips camera setup and can block remote audio."
            ),
            "links": links,
        }

    @app.get("/status", dependencies=[Depends(_auth)])
    async def status() -> dict[str, Any]:
        return controller.status()

    @app.get("/roster", dependencies=[Depends(_auth)])
    async def roster() -> list[dict[str, Any]]:
        return controller.roster()

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

    @app.post("/mute/{agent_key}", dependencies=[Depends(_auth)])
    async def mute(agent_key: str) -> dict[str, Any]:
        try:
            return controller.mute(agent_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/unmute/{agent_key}", dependencies=[Depends(_auth)])
    async def unmute(agent_key: str) -> dict[str, Any]:
        try:
            return controller.unmute(agent_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/pause", dependencies=[Depends(_auth)])
    async def pause() -> dict[str, Any]:
        return controller.pause()

    @app.post("/resume", dependencies=[Depends(_auth)])
    async def resume() -> dict[str, Any]:
        return controller.resume()

    @app.get("/relay/messages", dependencies=[Depends(_auth)])
    async def relay_messages(limit: int = 50) -> dict[str, Any]:
        return controller.relay_messages(limit=limit)

    @app.post("/relay/say", dependencies=[Depends(_auth)])
    async def relay_say(body: RelaySayRequest) -> dict[str, Any]:
        try:
            return await controller.relay_say(body.text, speak=body.speak)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/relay/cursor/pending", dependencies=[Depends(_auth)])
    async def cursor_pending() -> dict[str, Any]:
        return controller.cursor_pending()

    @app.get("/relay/cursor/agent-pending", dependencies=[Depends(_auth)])
    async def cursor_agent_pending() -> dict[str, Any]:
        return controller.cursor_agent_pending()

    @app.post("/relay/cursor/agent-complete", dependencies=[Depends(_auth)])
    async def cursor_agent_complete(body: CursorAgentCompleteRequest) -> dict[str, Any]:
        try:
            return await controller.cursor_agent_complete(
                body.msg_ids,
                summary=body.summary,
                speak=body.speak,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/relay/cursor/ack", dependencies=[Depends(_auth)])
    async def cursor_ack(body: CursorAckRequest | None = None) -> dict[str, Any]:
        ids = body.msg_ids if body and body.msg_ids else None
        return controller.cursor_ack(ids)

    @app.post("/relay/cursor/process", dependencies=[Depends(_auth)])
    async def cursor_process(speak: bool = True) -> dict[str, Any]:
        try:
            return await controller.cursor_process(speak=speak)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
