# AI Meeting Room — Session Handoff (2026-08-28)

Everything is **shut down**. Restart with:

```bash
cd ai-meeting-room
PYTHONPATH=src python3 -m ai_meeting_room.main interactive
```

Dashboard: http://127.0.0.1:8092/

---

## Rough usage (this POC session)

Estimates from relay logs + last interactive server log. **Not billing-grade** — check provider dashboards for actuals.

### Relay log summary (`relay/messages.jsonl`)

| Metric | Count |
|--------|------:|
| Your speech (STT finals logged) | 39 |
| Agent replies (OmniRoute → TTS) | 10 |
| Room → Cursor (inbox) | 13 queued, 7 thread_out |
| Cursor → room (dashboard / auto-processor) | 6 spoken |
| Session restarts (system lines) | 5 |

**Agent that actually spoke:** Project Alpha (10 replies). Fred was excluded. Missy/Architect mostly quiet.

### ElevenLabs TTS (last interactive log slice)

5 TTS calls logged with `character-cost` headers:

| Call | Chars billed |
|------|-------------:|
| 1 | 40 |
| 2 | 26 |
| 3 | 28 |
| 4 | 50 |
| 5 | 23 |
| **Subtotal (last session)** | **~167** |

**Not in that log:** earlier `demo` mode (4 agents × scripted lines) and dashboard **Send & speak** tests (e.g. tongue twisters). Expect **hundreds** of ElevenLabs chars total, not thousands — unless ConvAI connection attempts also billed (see below).

### OmniRoute LLM

- ~4+ `chat/completions` calls in last log slice
- Each agent reply + Cursor inbox auto-processor batch = 1 call
- Demo mode earlier = 4+ calls

### LiveKit

- Participant-minutes for 4–5 AI identities + you, ~35–40 min wall time
- STT (Deepgram nova-3) active whenever you were in interactive mode with mic on

### ElevenLabs ConvAI

- **`main run` never worked** — every WebSocket died with `internal_error (3001)` immediately
- May still have incurred signed-URL / connection charges; check ElevenLabs usage

---

## What worked

- **`demo`** — scripted speak demo; you heard all four agents
- **`interactive`** — mic → STT → OmniRoute → TTS; two-way with agents
- **Host dashboard** — kick/mute/chair/pause (after mute fixes)
- **Relay Send & speak** — fast Cursor → room path
- **Relay log** — full transcript in `relay/messages.jsonl`
- **Cursor inbox + auto-processor** — room → OmniRoute → Relay voice (late in session)

---

## What didn't work / still broken

### P0 — Architecture

1. **ElevenLabs ConvAI (`main run`)** — all agents fail WebSocket `internal_error`. Needs ElevenLabs account/support investigation. Until fixed, use **interactive** path only.

2. **Room → this Cursor chat** — inbox queues messages but **does not auto-inject into the chat thread**. Timer subscription failed. Auto-processor replies **in the room via OmniRoute**, not here. To talk to Cursor in chat, still message this thread (agent can read `relay/cursor_inbox.jsonl`).

3. **Wrong agent answers** — room-wide questions route to **chair (Project Alpha)**, not Cursor. You said "Cursor, can you hear me?" and Alpha answered. Need explicit routing: questions to Cursor/Relay should not go to chair.

### P1 — Relay / UX

4. **Relay was interrupting** — said "Got it" on every trigger; mute didn't work initially (fixed later). Now muted by default.

5. **Relay trigger too broad initially** — matched "cursor"/"thread" anywhere. Tightened to "Relay/Bridge" at start + "tell cursor".

6. **STT fragmentation** — short partials ("Relay." alone) queued as separate inbox messages. Need minimum content threshold for inbox.

7. **Duplicate TTS/log lines** — Cursor replies logged/spoken twice (duplicate `thread_in` entries).

8. **OmniRoute Cursor in room ≠ real Cursor** — auto-processor can't run `cloc`, open files, etc. It only generates text. You asked LOC count; room-Cursor correctly said it had no repo access.

### P2 — Ops / config

9. **`.env` malformed line** — `REASONING_API_PUBLIC_URL=OMNIROUTE_BASE_URL=...` was merged; fixed in working copy, verify on pickup.

10. **No git remote** — branch `cursor/ai-meeting-room-poc-d881` never pushed.

11. **No cost dashboard** — add usage counters (TTS chars, LLM calls, STT minutes) to host UI.

12. **Cloud agent dashboard** — `127.0.0.1:8092` only local; needs tunnel/port-forward for remote browser.

---

## Suggested next session

1. Confirm ElevenLabs ConvAI status or drop it from POC
2. Wire **real** room → Cursor chat (Hive/Buzz, webhook, or working timer subscription)
3. Route "Cursor/Relay" questions away from Project Alpha
4. Give room-Cursor read-only access to repo stats OR clearly label it as "voice relay, not coding agent"
5. Add usage/cost meter to dashboard
6. Push branch + run from homelab for persistent hosting

---

## Repo size (you asked)

~**3,499 lines** of Python in `src/`, `tests/`, `scripts/` (excludes relay runtime logs).
