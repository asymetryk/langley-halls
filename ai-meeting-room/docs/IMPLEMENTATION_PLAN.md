# Phased Implementation Plan

## Phase 0 — POC (this repo) ✅

**Goal:** Prove four independent AI voice participants in one LiveKit room.

| Item | Status |
|------|--------|
| LiveKit room join as 4 identities | Done |
| ElevenLabs ConvAI bridge per participant | Done |
| AudioMixer for multi-participant listening | Done |
| Interruption handling via ElevenLabs events | Done |
| Baserow secrets adapter for ElevenLabs key | Done |
| Provider-agnostic reasoning (mock + OpenAI) | Done |
| Custom LLM API for ElevenLabs agents | Done |
| Per-agent system prompts + in-memory store | Done |
| CLI: validate / run / reasoning-api | Done |

**Exit criteria:** Human joins room; hears agents speak; agents hear human and each other; `validate` passes with credentials.

---

## Phase 1 — Hardening & observability

**Goal:** Reliable demo suitable for internal dogfooding.

1. **Process isolation** — one OS process per agent (LiveKit `WorkerOptions` dispatch or separate `main run --agent fred`).
2. **Structured logging** — correlate logs by `room`, `agent_id`, ElevenLabs `conversation_id`.
3. **Health checks** — `/health` on reasoning API; startup probe for LiveKit + ElevenLabs connectivity.
4. **Graceful shutdown** — drain WebSockets, unpublish tracks, leave room.
5. **Config validation** — fail fast with actionable errors (missing agent IDs, unreachable Baserow).

**Dependencies:** LiveKit Cloud project, ElevenLabs ConvAI agents, public Custom LLM URL.

---

## Phase 2 — Reasoning provider expansion

**Goal:** Plug in Codex, Claude, Gemini, HyperAgent without touching voice/room code.

1. **`AnthropicReasoningAdapter`** — Messages API → SSE translator.
2. **`GeminiReasoningAdapter`** — Google GenAI streaming.
3. **`HyperAgentReasoningAdapter`** — HTTP bridge to internal agent runtime.
4. **Router** — `REASONING_PROVIDER` per agent or per meeting in config / Baserow.
5. **Responses API** — add `/v1/responses` for ElevenLabs agents configured for Responses format.

**Exit criteria:** Same meeting room works with `REASONING_PROVIDER=openai|anthropic|gemini|hyperagent`.

---

## Phase 3 — Memory & context

**Goal:** Agents remember the meeting beyond the current ConvAI session.

1. **Shared meeting transcript bus** — LiveKit data channel or Redis pub/sub for `(speaker, text, ts)`.
2. **Per-agent memory** — upgrade `AgentMemory` to SQLite or Redis lists.
3. **Summarization** — periodic rollup injected into Custom LLM system context.
4. **Optional RAG** — Baserow / vector store for project docs (Architect, Project Alpha).

---

## Phase 4 — Turn-taking & meeting dynamics

**Goal:** More natural multi-agent meetings (who speaks when).

1. **Chair agent mode** — Fred gets lightweight orchestration tools (invite speaker, agenda).
2. **Speaking floor tokens** — optional data-channel mutex to reduce overlap (ElevenLabs still handles interrupt).
3. **Silence detection** — Project Alpha prompts next agenda item after N seconds quiet.
4. **Human mute / agent mute** — LiveKit track subscription controls.

---

## Phase 5 — Production deployment

**Goal:** Run on homelab / cloud with minimal ops.

1. **Containerize** — Docker images: `reasoning-api`, `agent-worker` (one image, `AGENT_KEY` env).
2. **LiveKit agent dispatch** — explicit dispatch via token `RoomAgentDispatch` or backend API.
3. **Secrets** — Baserow-only in prod; no env key fallback.
4. **Tunnel / ingress** — stable HTTPS for Custom LLM (Cloudflare Tunnel, Tailscale).
5. **Frontend** — minimal React meet UI or reuse LiveKit Meet with pre-minted tokens.

---

## Phase 6 — Integrations

**Goal:** Connect to existing Asymetryk / OpenProject workflows.

1. **Webhook tools** on ElevenLabs agents → OpenProject, Baserow.
2. **Meeting artifacts** — transcript export, action items to OpenProject.
3. **Scheduled rooms** — cron / automation creates room + dispatches agents.

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Four agents talking over each other | ElevenLabs turn mode + Phase 4 floor tokens; tune system prompts |
| Custom LLM latency | Colocate reasoning API; stream SSE early |
| Baserow unavailable | Chained adapter + env fallback (dev only) |
| ElevenLabs agent ID drift | `setup_elevenlabs_agents.py` idempotent update |
| Audio feedback (agent hears self) | Filter local participant identity in track handler |

---

## Suggested next step after POC

Run Phase 0 end-to-end with real credentials, record a 2-minute meeting with one human and four agents, then proceed to **Phase 1** process isolation before adding new reasoning providers.
