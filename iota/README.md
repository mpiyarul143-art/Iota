# 🤖 IOTA BOT — Complete Telegram Bot

## ⚠️ FIRST: Required Setup (fixes "commands not working")

This update found and fixed the root causes behind most broken commands:

1. **MongoDB password placeholder** — `config.py` had a literal placeholder
   password (`YOUR_MONGODB_PASSWORD`), so the bot couldn't connect to its
   database at all. **You must open `config.py` and replace `_MONGO_PASS`
   with your real MongoDB Atlas password** (or your bot will start, but
   `/bal`, `/daily`, `/rob`, `/ludo` etc. will still fail).
2. **A missing `GIFS` config variable was crashing the entire bot on
   startup** (`village_war.py` imported it but it didn't exist) — fixed.
3. **Five handler files (`fun.py`, `items.py`, `welcome.py`,
   `protection.py`) were using an old, disconnected SQLite database**
   while the rest of the bot used MongoDB — meaning coins/items/settings
   never matched what `/bal` showed. All five are now migrated to the
   same MongoDB backend as everything else.
4. **Added a global error handler** so a bug in one command can no longer
   silently make it look like the bot "isn't responding" — you'll always
   get a clear message instead.
5. **Added a startup DB connection check** — if Mongo still isn't
   reachable, the owner gets DM'd immediately with the exact fix needed.

## ✨ Features

### 💰 Economy
`/daily` `/bal` `/rob` `/kill` `/revive` `/give` `/wallet` `/toprich`
`/global_rank` `/streak` `/protect`

### 🎮 Games
- **`/ludo [bet]`** — Professional Ludo (2-4 players, real board logic,
  captures, safe cells, coin betting, turn timers, visual board)
- **`/bluff`** — Rebuilt as a real multiplayer card game: `/bluff` (host
  opens a 2-min lobby) → `/enter` (join) → cards dealt via DM → `/drop a b`
  to play cards claiming the called number → `/judge` to call a bluff.
  First to empty their hand wins!
- **`/hack <reward> <digits>`** — Password Hacking mini-game:
  `/register` to join → `/guess <password>` → get HACKS/GLITCHES feedback
  → `/end` for the host to close it.
- **`/quiz [topic]`** — 🤖 **AI-generated** trivia questions, fresh every
  time (falls back to a curated question bank if AI is unreachable)
- **`/truth [topic]`** / **`/dare [topic]`** — 🤖 **AI-generated**, with
  free real-time web search grounding for topical questions. Reply to
  Iota's prompt and she reacts live, continuing a real conversation
  instead of a static message. Use `/truth classic` or `/dare classic`
  for the instant curated list.
- `/card` `/bet` `/bomb` `/wordgame` `/hangman` `/tictactoe` `/rps`
- `/roll [amount]` `/coinflip <heads/tails> [amount]`

### 🤖 AI Chat
- **Free real-time web search** (DuckDuckGo, no API key, unlimited) —
  automatically triggers for questions about current events, scores,
  prices, "latest", etc., so Iota's answers are grounded in real data.
- **Smart tag detection** — Iota replies in groups only when she's
  actually **@tagged**, **replied to**, or **directly addressed by name**
  at the start of a message. She no longer randomly replies just because
  someone says "iota" mid-sentence.
- `/ai <message>` / DM her directly / `/clearmemory`

### 👫 Social
`/marry` `/divorce` `/couple` `/couples` `/crush` `/love` `/look`
`/brain` `/stupid_meter` `/murder` `/slap` `/punch` `/kiss` `/hug`
`/bite` `/puzzle` `/confession` `/afk` `/valentine`

### 🛡️ Admin & Protection
`.warn` `.mute` `.ban` `.kick` `.promote` `.pin` `/lock` `/setflood`
`/rules` `/captcha` `/prot` (anti-flood/link/raid/profanity/bot)
`/report` `/reports` `/addword`

### 📜 Legal
`/terms` / `/refund` / `/policy` — Iota's Terms of Service & Refund
Policy for premium/Gems purchases.

### 🏰 Village & War
`/collect` `/storage` `/vault` `/mines` `/build` `/train` `/attack`
`/spy` `/kingdom` `/emperors`

### 🛠️ Utility
`/calc` `/poll` `/ping` `/tr` `/voice` `/id` `/detail` `/bio` `/setbio`
`/remindme` `/ocr` **`/last_seen <user_id>`** (shows last activity even
if the user has hidden it elsewhere)

### 💎 Premium
`/pay` `/fpay` `/check`

## 🚀 Setup

```bash
pip install -r requirements.txt
```

In `config.py`:
1. Set `_MONGO_PASS` to your real MongoDB Atlas password (**required**)
2. Set `BOT_TOKEN` to your bot's token
3. Set `OWNER_ID` to your Telegram user ID

```bash
python bot.py
```

On startup, check your logs (or your DM from the bot) to confirm
`✅ MongoDB connected successfully!` — if you instead see a connection
error, double-check the password and that your MongoDB Atlas cluster
allows connections from your server's IP (Network Access → Add IP).

## 📁 File Structure
```
iota_bot/
├── bot.py                  — Main entry point
├── config.py                — Configuration (⚠️ set _MONGO_PASS here)
├── handlers/
│   ├── ludo.py               — Professional Ludo Game (chat mode + Mini App launcher)
│   ├── werewolf_game.py       — 🆕 Werewolf social deduction game (5-10 players)
│   ├── slots_game.py            — 🆕 /slots casino game (native Telegram animation)
│   ├── quote_sticker.py           — 🆕 /q quote sticker generator
│   ├── connect.py               — 🆕 /connect shared AI memory between two users
│   ├── bluff_game.py          — 🆕 Real multiplayer Bluff card game
│   ├── hack_game.py           — 🆕 Password Hacking mini-game
│   ├── new_commands.py        — calc, poll, marry, streak, etc.
│   ├── games.py                — Card, Bomb, Word games
│   ├── extra_games.py          — 🆕 AI-powered Quiz, TTT, RPS, Hangman
│   ├── fun.py                   — 🆕 AI-powered Truth/Dare, social cmds
│   ├── ai_chat.py                — 🆕 AI chat + real-time search + smart tagging
│   ├── legal.py                   — 🆕 Terms & Refund Policy
│   ├── items.py / welcome.py / protection.py — 🆕 Migrated to MongoDB
│   ├── admin.py / advanced_admin.py — Moderation
│   ├── owner_panel.py              — 🆕 Owner-only bot administration
│   └── village_war.py              — Village & war system
├── webapp/
│   ├── ludo_server.py         — 🆕 Ludo Mini App backend (aiohttp server)
│   └── ludo/                    — 🆕 Ludo Mini App frontend (HTML/CSS/JS)
└── utils/
    ├── mongo_db.py            — All database operations (MongoDB)
    ├── ai_provider.py          — Free + premium AI model routing
    ├── search.py                — 🆕 Free unlimited real-time web search
    ├── gif_provider.py            — 🆕 Live/unlimited GIF search (Tenor)
    ├── reactions.py                 — 🆕 Iota's emoji reaction system
    ├── connect.py                    — 🆕 Shared AI memory between two connected users
    ├── command_knowledge.py            — 🆕 Single source of truth for Iota's self-knowledge
    ├── ludo_engine.py               — 🆕 Shared Ludo rules engine (chat + Mini App)
    ├── quote_render.py                — 🆕 /q quote-sticker image rendering (Pillow)
    ├── font_manager.py                  — 🆕 Font handling for quote stickers
    ├── system_gate.py                     — 🆕 /close-/open decorators (games/economy/village)
    ├── permissions.py                 — 🆕 Unified owner/admin/group/DM decorators
    ├── safe_html.py                    — 🆕 HTML-escaping helpers
    ├── error_handler.py                 — 🆕 Global error handler
    ├── ai_memory.py                       — Per-user AI conversation memory
    └── helpers.py                          — Utility functions
```

## 🎲 Ludo Mini App Setup

`/ludo` now offers a real, visual, multiplayer Ludo board via Telegram's
Mini App feature (in addition to the classic chat-button game, which
always works with zero setup).

**The Mini App requires one thing you must configure: a public HTTPS URL.**
Telegram will refuse to open a Mini App that isn't served over HTTPS from
a real domain (no `localhost`, no bare IP address) — this is a Telegram
platform requirement, not something in this code.

### Steps to enable it
1. Deploy this bot somewhere with a public HTTPS domain (most hosts —
   Railway, Render, a VPS with a domain + reverse proxy, etc. — can do
   this). The Mini App server runs **in the same process** as the bot
   itself (started automatically), listening on `config.WEBAPP_PORT`
   (default `8080`) — point your HTTPS reverse proxy at that port.
2. Set `WEBAPP_BASE_URL` in `config.py` to that public HTTPS domain,
   e.g. `WEBAPP_BASE_URL = "https://ludo.yourdomain.com"`.
3. Restart the bot. `/ludo` will now show **"🎮 Play Ludo"** and
   **"👀 Watch"** buttons that open the real board.

Until `WEBAPP_BASE_URL` is set, `/ludo` automatically falls back to the
classic chat-button game — nothing breaks, you just don't get the visual
board until the domain is configured.

### What the Mini App includes
- Real animated SVG board with all 4 colors, safe cells, and home stretch
- Live dice rolls with a tumble animation, synced instantly to all
  players and spectators via WebSocket
- Spectator mode — anyone can watch a game live without playing
- In-lobby / in-game chat, visible to players and spectators
- The exact same rules engine (`utils/ludo_engine.py`) as the chat
  version, so results are always fair and consistent
- Every request is authenticated via Telegram's official `initData`
  signature check — a user can never impersonate another player

## ⭐ How Telegram Stars payments work

`/pay` and `/gems` charge real Telegram Stars via `send_invoice()`.
Telegram Stars **always** accumulate on the Telegram account that
registered this bot with @BotFather — there is no per-payment "send to
a different account" option in the Bot API, and none is needed: as long
as you (config.OWNER_ID) are that bot's registered owner, every Star
already lands with you automatically. You withdraw accumulated Stars via
[Fragment](https://fragment.com), separately from this bot's code.
Users never see any of this — `/starsstats` (owner-only) is the only
place transaction history is visible.

## 📢 Update Channel Setup

`/start`'s menu has a button (where "Friends" used to be) that links
straight to your update channel:
1. Create a Telegram channel, make it **public** (so it gets a @username).
   Suggested short name to check availability on: **IotaUpdates**.
2. Set `UPDATE_CHANNEL_USERNAME = "IotaUpdates"` (no leading @) in `config.py`.
3. Restart the bot. The button now links directly to your channel.

Leave it blank and the button falls back to the original Friends menu —
nothing ever points to a broken link.

## 🎭 Setting up sticker packs

`/addsticker <mood>` (reply to any sticker, owner-only) — builds up
Iota's own reply-stickers entirely from Telegram, no code edits needed.
See `/panel` for the full list: `/stickerpacks`, `/previewsticker`,
`/clearstickers`.

## 🔊 Voice/TTS settings

`/ttssettings` (owner-only) — change Iota's voice model, speaker, speed,
pitch, and loudness directly from Telegram. `/previewtts <text>` to hear
the current settings before committing to them.

## 🖼️ /q Quote Stickers

Reply to any text message with `/q` to turn it into a styled quote
sticker (name + avatar + text). Works out of the box, but for guaranteed
offline-safe, best-quality Hindi/emoji rendering, download these once
and place them in `assets/fonts/` (the bot will also try to auto-download
them on first use if your host has internet access):
- `NotoSans-Regular.ttf` / `NotoSans-Bold.ttf` — https://fonts.google.com/noto/specimen/Noto+Sans
- `NotoSansDevanagari-Regular.ttf` / `NotoSansDevanagari-Bold.ttf` — https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari

## 🔒 /close and /open (games / economy / village)

Group admins can disable all games, all economy commands, all village-
war commands — or any combination — with `/close` (add `games`,
`economy`, or `village` to close just one system). `/open` reopens the
same way. State is saved in MongoDB, so it survives a bot restart.


