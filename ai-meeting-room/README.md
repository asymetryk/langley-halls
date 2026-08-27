# AI Meeting Room POC

A proof-of-concept **multi-agent voice meeting room** using **LiveKit** for real-time rooms/participants and **ElevenLabs Conversational AI** for speech (STT, TTS, turn-taking, interruptions).

Four independent AI participants — **Fred**, **Missy**, **Architect**, and **Project Alpha** — each join the same LiveKit room with their own identity, system prompt, and memory. Reasoning is provider-agnostic via adapters (mock, OpenAI/Codex today; Claude, Gemini, HyperAgent later).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram and adapter boundaries.

```
Human / browser ──► LiveKit Room ◄── AI participant (×4)
                         │                    │
                         │              ElevenLabs ConvAI WS
                         │                    │
                         │              Custom LLM (reasoning API)
                         │                    │
                         └──────────► Provider adapters (mock / OpenAI / …)
```

## Quick start

### 1. Install

```bash
cd ai-meeting-room
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
# Edit .env with LiveKit credentials
```

### 2. Configure secrets

ElevenLabs API key is loaded from the **Baserow secrets table** first, then falls back to `ELEVENLABS_API_KEY`:

| Baserow column | Example |
|----------------|---------|
| Name | `elevenlabs_api_key` |
| Value | `sk_…` |

Environment:

```bash
BASEROW_API_URL=https://api.baserow.io
BASEROW_API_TOKEN=…
BASEROW_SECRETS_TABLE_ID=12345
ELEVENLABS_SECRET_NAME=elevenlabs_api_key
```

### 3. Start reasoning API (Custom LLM for ElevenLabs)

Expose port 8090 publicly (ngrok, Cloudflare Tunnel, etc.) and set `REASONING_API_PUBLIC_URL`.

```bash
python -m ai_meeting_room.main reasoning-api
```

### 4. Create ElevenLabs agents

```bash
python scripts/setup_elevenlabs_agents.py \
  --custom-llm-url https://your-tunnel.example.com
```

Copy the printed agent IDs into `.env`.

### 5. Run the meeting

Terminal A — reasoning API (if not already running):

```bash
python -m ai_meeting_room.main reasoning-api
```

Terminal B — four AI participants join the room:

```bash
python -m ai_meeting_room.main run
```

Terminal C — mint a token for yourself:

```bash
python -m ai_meeting_room.server.token_server --identity host --name "You"
```

Join the room with [LiveKit Meet](https://meet.livekit.io/) or your own client using `LIVEKIT_URL`, room name `ai-meeting-room`, and the token.

### Validate configuration

```bash
python -m ai_meeting_room.main validate
```

## Project layout

```
src/ai_meeting_room/
  adapters/
    secrets/          # Baserow + env fallback
    reasoning/        # Provider-agnostic LLM (mock, OpenAI, …)
    voice/            # ElevenLabs ConvAI ↔ LiveKit bridge
    room/             # LiveKit participant + audio mixer
  agents/definitions.py   # Fred, Missy, Architect, Project Alpha
  memory/store.py         # Per-agent memory
  server/reasoning_api.py # OpenAI-compatible Custom LLM
  orchestrator.py         # Spawns all four participants
  main.py                 # CLI
```

## Design principles

- **No custom media infrastructure** — LiveKit handles WebRTC; ElevenLabs handles voice orchestration.
- **Adapter pattern** — swap secrets, reasoning, or voice backends without touching orchestration.
- **Independent participants** — each agent is its own LiveKit identity and ElevenLabs ConvAI session.
- **Natural turn-taking** — ElevenLabs ConvAI decides when to speak; `interruption` events clear the audio queue.

## Phased plan

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## License

MIT (POC)
