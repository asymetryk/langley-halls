"""LiveKit access token helper for human participants."""

from __future__ import annotations

import argparse

from livekit import api

from ai_meeting_room.config import get_settings


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a LiveKit token for a human participant")
    parser.add_argument("--room", default=None)
    parser.add_argument("--identity", default="human-host")
    parser.add_argument("--name", default="Host")
    args = parser.parse_args()

    settings = get_settings()
    room = args.room or settings.meeting_room_name
    print(mint_human_token(room=room, identity=args.identity, name=args.name))


if __name__ == "__main__":
    main()
