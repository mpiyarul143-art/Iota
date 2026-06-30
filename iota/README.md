# 🤖 Iota Bot — Complete Setup Guide
**Owner: @Boobies_00**

---

## ✅ Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

---

## ✅ Step 2: MongoDB Atlas Setup

Your images show you already have MongoDB Atlas! Follow these steps:

1. Go to **MongoDB Atlas** → Your Cluster → **Connect**
2. Choose **"Connect your application"**
3. Copy the connection string
4. In `config.py`, replace `<PASSWORD>` with your actual password:
```python
MONGO_URI = "mongodb+srv://kalu923476:YOUR_PASSWORD@cluster0.tjpjh4k.mongodb.net/iota_bot?retryWrites=true&w=majority"
```

**Also add your IP to whitelist:**
- Atlas Dashboard → Network Access → Add IP Address → Allow from Anywhere (0.0.0.0/0)

---

## ✅ Step 3: BotFather Setup

1. Open @BotFather on Telegram
2. `/setcommands` → paste this list:

```
start - Talk To Iota
daily - Claim Daily Coins
bal - Check Balance
rob - Rob Someone
kill - Kill Someone
revive - Revive
protect - Buy Protection
give - Gift Coins
toprich - Top 10 Richest
topkill - Top 10 Killers
rank - Card Rank
profile - Full Profile
shop - Buy Titles
work - Earn Coins
top - Leaderboards
gems - Gems Store
claim - Group Reward
coupons - Coupon Guide
economy - Economy Info
game - All Games
card - Card Game
bomb - Bomb Game
bluff - Bluff Game
hack - Hack Game
tictactoe - Tic Tac Toe
rps - Rock Paper Scissors
quiz - Quiz Game
hangman - Hangman
wordgame - Word Game
leaders - Card Leaders
ship - Compatibility Check
roast - Roast Someone
compliment - Compliment Someone
truth - Truth Question
dare - Dare Challenge
horoscope - Daily Horoscope
shayari - Hindi Shayari
meme - Random Meme
whatif - AI Scenario
story - Group Story
ocr - Read Image Text
remindme - Set Reminder
voice - Text To Speech
tr - Translate Text
id - Get User ID
collect - Collect Resources
storage - Check Resources
mines - Mine Levels
build - Upgrade Buildings
train - Train Troops
troops - Show Army
walls - Build Walls
defense - Build Defense
spy - Scout Enemy
kingdom - Full Attack Plan
attack - Attack Player
vault - Check Vault And Rank
settle - Move Coins
convert - Resources To Coins
emperors - Top 10 Emperors
guide - Game Guide
items - Available Items
gift - Gift Item
pay - Buy Premium
fpay - Buy With Stars
check - Check Protection
help - Show All Commands
panel - Owner Panel
```

---

## ✅ Step 4: Run The Bot

```bash
python bot.py
```

---

## 📁 File Structure

```
iota_bot/
├── bot.py                    ← Main entry point
├── config.py                 ← All settings (BOT_TOKEN, MONGO_URI etc)
├── requirements.txt
├── handlers/
│   ├── start.py              ← /start with Riruru-style castle image
│   ├── economy.py            ← Baka-style economy with smallcaps fonts
│   ├── premium.py            ← /pay /fpay /fgems (Telegram Stars)
│   ├── games.py              ← Card, Bomb, Bluff, Hack, Word game
│   ├── extra_games.py        ← TicTacToe, RPS, Hangman, Quiz, Ship, Meme etc
│   ├── fun.py                ← Slap, Kiss, Hug, Valentine etc
│   ├── items.py              ← Shop items
│   ├── village_war.py        ← Full Riruru village + war system
│   ├── admin.py              ← .warn .ban .mute .imute .promote etc
│   ├── advanced_admin.py     ← /lock /flood /rules /captcha /notes etc
│   ├── ai_chat.py            ← Sarvam AI (Baka-style personality)
│   ├── alerts.py             ← Auto protection expiry DM alerts
│   ├── welcome.py            ← New member welcome with GIF
│   ├── protection.py         ← Anti-spam, anti-raid, reports
│   ├── utility.py            ← /tr /voice /id /ocr etc
│   └── owner_panel.py        ← /panel /addcoins /broadcast /announce
└── utils/
    ├── mongo_db.py           ← MongoDB async database
    ├── helpers.py            ← Utility functions
    └── fonts.py              ← Baka-style smallcaps fonts
```

---

## 🔑 Key Features

| Feature | Command |
|---------|---------|
| Baka-style fonts | All outputs use smallcaps |
| Protection alerts | Auto DM 6h, 2h, 30min before expiry |
| AI personality | Cute, sassy like Baka bot |
| Village war | /attack /troops /walls /defense |
| Card tournament | With GIF result like Baka |
| Telegram Stars payment | /fpay /fgems |
| Owner announce | /announce all <message> |
| Group protection | Flood, spam, link, raid auto-block |
| Advanced admin | /lock /captcha /rules /notes etc |

---

## ⚠️ Important Notes

1. **MongoDB password**: Must be URL-encoded (e.g., `@` → `%40`)
2. **Sarvam AI**: Already configured with your key
3. **GIFs**: Using Giphy URLs, can replace with Telegram file_ids for speed
4. **Castle image**: Replace with your own image URL in `start.py`
5. **Protection alerts**: Run automatically in background

---

## 👑 Owner Commands (Only @Boobies_00)

```
/panel        - Owner menu
/addcoins     - Add coins to user
/removecoins  - Remove coins
/addgems      - Add gems
/addpremium   - Give premium
/removepremium - Remove premium
/addcoupon    - Add coupon code
/banuser      - Ban from bot
/unbanuser    - Unban
/broadcast    - Message all users
/announce all <msg> - Send to all groups
/announce <group_id> <msg> - Send to specific group
/botstats     - Bot statistics
```
