# IOTA — GAMES UI / ASSETS / SYSTEMS ROADMAP

> Goal: turn every Iota mini-game into a polished, *professional* product with a
> consistent visual language (PNG art + small-caps text), complete game logic,
> and future-proof systems — built systematically, with tests, targeting 0 bugs
> and 0 errors.
>
> Audited: 2026-07-11. Repo: `/workspaces/Iota/iota`.

---

## 1. WHAT ALREADY EXISTS (audited, do not rebuild)

| Layer | Status | Notes |
|-------|--------|-------|
| Small-caps text style | ✅ done | `bot.py:_install_smallcaps_output` wraps every user-facing string via `utils/fonts.sc_out` (tag/URL/entity aware). Games must reuse this; do NOT roll a new casing system. |
| Text-game UI kit | ✅ partial | `utils/game_ui.py` → `banner`, `medal`, `progress_bar`, `result_card`, `send_gif_result`, `back_button`. Good base, needs more primitives. |
| PNG rendering | ✅ proof | `utils/quote_render.py` (Pillow + NotoColorEmoji color glyphs, segmented emoji/text draw). Reuse as the engine for ALL game art. |
| Fonts | ✅ done | `utils/font_manager.py` + `utils/fonts.py` load Noto Sans / Devanagari / ColorEmoji. |
| Ludo Mini App | ✅ done | `webapp/ludo/` (HTML/CSS/JS) + `webapp/ludo_server.py` (aiohttp + WebSocket). The reference pattern for future Mini Apps. |
| Games (text/inline) | ✅ many | card, bet, bomb, wordgame, dice, slots, roulette, wheel, bluff, hack, tictactoe, rps, hangman, quiz, truth/dare, werewolf, ludo(chat). |
| Error handling | ✅ base | `utils/error_handler.py` global handler + `utils/system_gate.py` (`/close`/`/open`). |

**Key insight:** the missing piece is NOT logic for most games — it is a
*unified visual system* (PNG art for board/cards/dice/scoreboards) and a
*consistent inline navigation shell*, plus a few genuinely new systems.

---

## 2. DESIGN SYSTEM (the "professional" contract)

Reuse, extend — never fork.

- **Type / casing:** keep `sc_out` small-caps for ALL game text.
- **Color tokens** (mirror `webapp/ludo/static/css/ludo.css`):
  stage `#0f1220`, panel `#171b2e`, text `#f0ece0`, dim `#9aa0bd`, amber `#ffb648`.
- **Art:** all raster art via Pillow using a shared `utils/game_art.py` module
  (new) so cards/dice/boards share one renderer, one font stack, one palette.
- **Feedback:** `send_gif_result` already degrades to text — keep that contract.

---

## 3. PILLARS + PHASES

### PHASE 0 — Audit & design tokens (foundation)
- [ ] Catalog every game's missing buttons / dead callbacks / unhandled states.
- [ ] Define `utils/game_art.py` palette + canvas helpers (rounded rect, shadow,
      emoji/text segmented draw ported from `quote_render.py`).
- [ ] Add UI primitives to `game_ui.py`: `card_face`, `dice_face`, `board_thumb`,
      `scoreboard`, `nav_bar`, `chip`.

### PHASE 1 — Game Art Engine (Pillow PNG)
- [ ] `render_card(rank, suit)` → PNG card face (themed, amber border).
- [ ] `render_dice(value)` → PNG die (1–6) with weight/shadow.
- [ ] `render_slots(reels)` / `render_roulette(wheel, ball)` / `render_wheel(segments)`
      → PNG game-state snapshots.
- [ ] `render_scoreboard(players)` / `render_leaderboard(rows)` → PNG tables.
- [ ] All renderers: NEVER raise (fallback to text like `send_gif_result`).
- [ ] Unit tests with sample PNGs (deterministic seed) → guards 0-bug goal.

### PHASE 2 — Unified Games Hub + consistent inline shell
- [ ] One `games_hub` menu (already exists in `handlers/games.py`) gets a
      consistent `nav_bar` (Home / Back / Refresh) via `game_ui.py`.
- [ ] Standardize lobby→play→result→rematch flow across card/bet/bomb/roulette/
      wheel/bluff/hack so every game "feels like one product".
- [ ] Wire PNG art into each result card (Phase 1 renderers).

### PHASE 3 — Level up top games with real visuals
- [ ] `/card` & `/bet`: send PNG card faces instead of `A♠` text.
- [ ] `/slots`: PNG reel strip + win-line highlight.
- [ ] `/roulette` & `/wheel`: PNG wheel with pointer + result.
- [ ] `/bomb`: PNG defuse timer / wire board.
- [ ] `/hangman`: PNG gallows stages.
- [ ] Ludo already visual (Mini App) — add PNG share-image of final board.

### PHASE 4 — Mini App shell for 2–3 more games
- [ ] Extract a generic Mini App skeleton from `webapp/ludo` (auth via Telegram
      `initData`, aiohttp + WebSocket, shared CSS tokens).
- [ ] Port `/roulette` (live wheel) and `/card` (live table) to Mini Apps —
      these benefit most from real-time animation.
- [ ] Keep chat/inline fallback when `WEBAPP_BASE_URL` is unset (like Ludo).

### PHASE 5 — New systems (the "future" layer)
- [ ] **Achievements** — first-win, streak, high-roller badges (PNG medal art).
- [ ] **Daily challenge** — one rotating game objective with reward.
- [ ] **Tournaments** — bracket of N players, auto-schedule via job queue.
- [ ] **Global leaderboard** — cross-group ranks (`/leaders` already exists; extend).
- [ ] **Spectator / replay** — reuse Ludo spectator pattern.
- [ ] **Stats profile** — per-user win/loss, favorite game (PNG infographic).

### PHASE 6 — Hardening (0 bugs / 0 errors)
- [ ] Unit tests for every engine (`ludo_engine`, `game_art`, game resolvers).
- [ ] Callback-data size guard (Telegram 64-byte limit) — compress/encode ids.
- [ ] Timeout/cleanup jobs for every lobby (no orphaned games).
- [ ] Lint + typecheck in CI; manual smoke pass of all `/commands`.

---

## 4. PER-GAME CHECKLIST (track completeness)

| Game | Logic | PNG art | Unified nav | Tests |
|------|-------|---------|-------------|-------|
| card / bet | ✅ | ⬜ | ⬜ | ⬜ |
| bomb | ✅ | ⬜ | ⬜ | ⬜ |
| wordgame | ✅ | ⬜ | ⬜ | ⬜ |
| dice | ✅ | ⬜ | ⬜ | ⬜ |
| slots | ✅ | ⬜ | ⬜ | ⬜ |
| roulette | ✅ | ⬜ | ⬜ | ⬜ |
| wheel | ✅ | ⬜ | ⬜ | ⬜ |
| bluff | ✅ | ⬜ | ⬜ | ⬜ |
| hack | ✅ | ⬜ | ⬜ | ⬜ |
| tictactoe | ✅ | ⬜ | ⬜ | ⬜ |
| rps | ✅ | ⬜ | ⬜ | ⬜ |
| hangman | ✅ | ⬜ | ⬜ | ⬜ |
| quiz | ✅ | ⬜ | ⬜ | ⬜ |
| truth/dare | ✅ | ⬜ | ⬜ | ⬜ |
| werewolf | ✅ | ⬜ | ⬜ | ⬜ |
| ludo (chat) | ✅ | ⬜ | ⬜ | ⬜ |
| ludo (mini) | ✅ | ✅ | ✅ | ⬜ |

---

## 5. GUARDRAILS (how we hit "0 bugs / 0 errors")
1. Every new renderer/image sender MUST degrade to text on failure (mirror
   `send_gif_result`).
2. No new casing logic — always `sc_out`.
3. All game state in MongoDB (existing `utils/mongo_db.py` / `utils/db.py`);
   never trust client-sent values (Mini App uses `initData` verify).
4. Every lobby gets a timeout job that cleans up.
5. Tests required per Phase before marking it done.

---

## 6. SUGGESTED BUILD ORDER (incremental, shippable each step)
1. Phase 0 + Phase 1 (art engine + tests) — visible, safe, no game breakage.
2. Phase 2 (hub/nav) — consistency win across all games at once.
3. Phase 3 (visuals per game) — one game at a time, each behind its own PR.
4. Phase 4 (Mini Apps) — only after chat version is solid.
5. Phase 5 (new systems) — additive, opt-in via `/close`/`/open`.
6. Phase 6 (hardening) — continuous.
