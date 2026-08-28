"""LiveKit access token helper for human participants."""

from __future__ import annotations

import argparse
from urllib.parse import quote

from livekit import api

from ai_meeting_room.config import get_settings

MEET_CUSTOM_BASE = "https://meet.livekit.io/custom/"


def mint_human_token(*, room: str, identity: str, name: str) -> str:
    settings = get_settings()
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET required")

    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
            )
        )
    )
    return token.to_jwt()


def build_meet_join_url(*, livekit_url: str, token: str) -> str:
    """One-click join URL for meet.livekit.io against a custom LiveKit project."""
    return (
        f"{MEET_CUSTOM_BASE}?liveKitUrl={quote(livekit_url, safe='')}"
        f"&token={quote(token, safe='')}"
    )


def mint_join_link(*, room: str, identity: str, name: str, livekit_url: str | None = None) -> dict[str, str]:
    settings = get_settings()
    server_url = livekit_url or settings.livekit_url
    token = mint_human_token(room=room, identity=identity, name=name)
    base = settings.room_control_public_url or f"http://{settings.room_control_host}:{settings.room_control_port}"
    meet_url = f"{base.rstrip('/')}/meet?identity={quote(identity, safe='')}&name={quote(name, safe='')}"
    return {
        "identity": identity,
        "name": name,
        "room": room,
        "livekit_url": server_url,
        "token": token,
        "join_url": build_meet_join_url(livekit_url=server_url, token=token),
        "meet_url": meet_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a LiveKit token for a human participant")
    parser.add_argument("--room", default=None)
    parser.add_argument("--identity", default="human-host")
    parser.add_argument("--name", default="Host")
    args = parser.parse_args()

    settings = get_settings()
    room = args.room or settings.meeting_room_name
    link = mint_join_link(
        room=room,
        identity=args.identity,
        name=args.name,
        livekit_url=settings.livekit_url,
    )
    print(link["join_url"])
    print()
    print(f"Room: {room}")
    print(f"Server: {settings.livekit_url}")
    print(f"Token (backup): {link['token']}")


if __name__ == "__main__":
    main()
