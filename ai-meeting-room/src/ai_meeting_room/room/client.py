"""CLI client for the room control API."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ai_meeting_room.config import Settings


class RoomControlClient:
    def __init__(self, settings: Settings) -> None:
        self._base = f"http://{settings.room_control_host}:{settings.room_control_port}"
        headers: dict[str, str] = {}
        if settings.room_control_token:
            headers["Authorization"] = f"Bearer {settings.room_control_token}"
        self._headers = headers

    async def _request(self, method: str, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, f"{self._base}{path}", headers=self._headers)
            response.raise_for_status()
            return response.json()

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/status")

    async def kick(self, agent_key: str) -> dict[str, Any]:
        return await self._request("POST", f"/kick/{agent_key}")

    async def invite(self, agent_key: str) -> dict[str, Any]:
        return await self._request("POST", f"/invite/{agent_key}")

    async def chair(self, agent_key: str) -> dict[str, Any]:
        return await self._request("POST", f"/chair/{agent_key}")

    async def pause(self) -> dict[str, Any]:
        return await self._request("POST", "/pause")

    async def resume(self) -> dict[str, Any]:
        return await self._request("POST", "/resume")


def format_status(payload: dict[str, Any]) -> str:
    in_call = ", ".join(a["name"] for a in payload.get("in_call", [])) or "(none)"
    excluded = ", ".join(payload.get("excluded", [])) or "(none)"
    paused = "yes" if payload.get("paused") else "no"
    return (
        f"Room: {payload.get('room')}\n"
        f"Paused: {paused}\n"
        f"Chair: {payload.get('chair_name')} ({payload.get('chair')})\n"
        f"In call: {in_call}\n"
        f"Excluded: {excluded}"
    )


def print_result(payload: dict[str, Any]) -> None:
    message = payload.get("message")
    if message:
        print(message)
    else:
        print(json.dumps(payload, indent=2))
