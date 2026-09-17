# Langley Halls

Multi-agent voice meeting room POC: **LiveKit** for the room, **ElevenLabs** for TTS, **OmniRoute** for reasoning.

Four AI participants — Fred, Missy, Architect, Project Alpha — join the same LiveKit room. The supported demo path today is **interactive** (your mic → STT → OmniRoute → TTS). The original ElevenLabs Conversational AI `run` path is parked until WebSocket `internal_error (3001)` is fixed or dropped.

POC code lives in [`ai-meeting-room/`](ai-meeting-room/).

## Quick demo (interactive)

```bash
cd ai-meeting-room
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # fill LiveKit + ElevenLabs + OmniRoute (see below)
python -m ai_meeting_room.main validate          # exit 1 if LiveKit / ElevenLabs / OmniRoute missing
# python -m ai_meeting_room.main validate --offline  # keys only; skip network pings
python -m ai_meeting_room.main interactive
```

Dashboard: http://127.0.0.1:8092/

Join the LiveKit room (`MEETING_ROOM_NAME`, default `ai-meeting-room`) with [LiveKit Meet](https://meet.livekit.io/) or mint a token:

```bash
python -m ai_meeting_room.server.token_server --identity host --name "You"
```

Optional speak-only smoke test (no mic):

```bash
python -m ai_meeting_room.main demo
```

## Secrets

Copy `.env.example` → `.env`. Required for interactive/demo:

| Variable | Purpose |
|----------|---------|
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit Cloud room |
| `ELEVENLABS_API_KEY` | TTS fallback if Baserow is unset (and ConvAI if revived) |
| `OMNIROUTE_BASE_URL` / `OMNIROUTE_API_KEY` / `OMNIROUTE_MODEL` | Reasoning |

Optional: Baserow secrets table for the ElevenLabs key (`interactive` / `demo` / `validate` / ConvAI all use the same adapter chain). Defaults: `BASEROW_API_URL=https://baserow.tail21f530.ts.net`, value column `Secret`, row name `elevenlabs langley halls`. Documented SoT table is `828` (`BASEROW_SECRETS_TABLE_ID` in `.env.example`); if unset, Baserow is skipped. Set `BASEROW_API_TOKEN` in `.env` only (never commit it). Database tokens 401 on `/api/applications/` — expected; we read table rows only. Agent IDs (`ELEVENLABS_AGENT_ID_*`) are only needed for ConvAI `run`.

`main validate` reports LiveKit / ElevenLabs / OmniRoute as `pass` / `fail` / `skip` (ElevenLabs source is `baserow` | `env` | `missing`). It never prints secrets. Exit 0 only when those three are ok.

Do not commit `.env`.

## Commands

| Command | Status | Notes |
|---------|--------|-------|
| `main validate` | Supported | Interactive secrets: LiveKit, ElevenLabs, OmniRoute. Exit 1 if any required check fails. `--offline` skips network pings. |
| `main interactive` | **Supported demo** | Mic + dashboard + relay |
| `main demo` | Supported | Scripted TTS into room |
| `main room …` | Supported | Host controls while interactive runs |
| `main run` | Parked | ElevenLabs ConvAI — fails WS 3001 |
| `main reasoning-api` | ConvAI-only | Custom LLM for agents; not needed for interactive |

## What’s solid vs brittle

**Solid enough for a dogfood demo:** interactive path, host dashboard (kick/mute/chair/pause), relay Send & speak, transcript in `ai-meeting-room/relay/messages.jsonl`. Lines clearly addressed to Cursor or Relay are logged to the inbox and do not go to the chair.

**Known gaps:** ConvAI `run` broken; room → Cursor chat inbox queues but does not auto-inject into chat; no process isolation / health checks yet (Phase 1).

Details: [`ai-meeting-room/docs/HANDOFF.md`](ai-meeting-room/docs/HANDOFF.md).

## Docs

| Doc | What |
|-----|------|
| [`ai-meeting-room/README.md`](ai-meeting-room/README.md) | Full quick start (includes ConvAI setup) |
| [`ai-meeting-room/docs/ARCHITECTURE.md`](ai-meeting-room/docs/ARCHITECTURE.md) | Adapters, audio flow |
| [`ai-meeting-room/docs/HANDOFF.md`](ai-meeting-room/docs/HANDOFF.md) | Last session status + usage notes |
| [`ai-meeting-room/docs/IMPLEMENTATION_PLAN.md`](ai-meeting-room/docs/IMPLEMENTATION_PLAN.md) | Phased roadmap |

## Branch

Default working branch: `cursor/ai-meeting-room-poc-d881`.
