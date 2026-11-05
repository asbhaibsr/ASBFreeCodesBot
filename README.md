# 🎁 ASB FreeCodes Bot

Telegram Giveaway Bot — **Python + aiogram 3 + MongoDB Atlas**, Koyeb par deploy hone ke liye ready.
Bot: http://t.me/ASBFreeCodesBot

## ✨ Features

- `/start` par welcome message + 3 buttons: **Join Channel · Help · Enter Code**
- Galat code logic: `MAX_WRONG_ATTEMPTS` (3) se zyada galat code ⇒ **24 ghante lock**
- Ek giveaway me ek user ki **sirf ek entry** (duplicate par "spam mat karein" message)
- Sahi code par: entry DB me save → bot ka fixed message + **admin ka custom message** user ke DM me → entry details **private log channel** me
- `/admin` panel: **Stats · Add Giveaway Code · Select Winner · Broadcast · Clear Junk**
- Select Winner: code winner ke DM me → baaki sabko "winner declare ho gaya" message → purana code + sabhi entries auto-delete (naye giveaway ke liye reset)
- **Rate-limit queue + FloodWait protection**; bot block karne wale users auto **Junk List** me, **Clear Junk** se permanent remove
- Saara data MongoDB Atlas me (restart par bhi safe)

## 🔧 Setup

### 1) Bot token
[@BotFather](https://t.me/BotFather) → `/newbot` ya existing bot ka token lein → ye `BOT_TOKEN` hai.

### 2) MongoDB Atlas (free M0)
1. atlas.mongodb.com par cluster banayein (M0 Free).
2. **Database Access** → naya user + password banayein.
3. **Network Access** → `0.0.0.0/0` allow karein (Koyeb ka IP fixed nahi hota).
4. **Connect → Drivers** se connection string copy karein → ye `MONGO_URI` hai (`<password>` apna daalein).

### 3) Channels
- **Private Log Channel** me bot ko **Admin** banayein (post permission ke saath) — warna entry logs nahi jayenge.
- Task channel me bot ko Admin banana sirf tab zaroori hai jab `REQUIRE_JOIN=true` rakhein.

### 4) GitHub par upload
Is folder ki saari files ek naye repo me daalein (`bot.py`, `requirements.txt`, `Dockerfile`, `.gitignore`, `.dockerignore`, `.env.example`, `README.md`).
⚠️ **`BOT_TOKEN` aur `MONGO_URI` kabhi GitHub par na daalein** — ye sirf Koyeb ke Environment Variables me jayenge. Agar token leak ho jaye to BotFather me `/revoke` karein.

### 5) Koyeb par deploy
1. koyeb.com → **Create Service → Web Service → GitHub** → apna repo chunein.
2. **Builder: Dockerfile**.
3. **Instance: Free** (region Frankfurt ya Washington D.C.).
4. **Environment variables** (secret ke roop me daalein):
   - `BOT_TOKEN`
   - `MONGO_URI`
5. **Exposed port: 8000 (HTTP)** · **Health check path: `/health`**.
6. Deploy dabayein. Logs me `Bot started: @ASBFreeCodesBot` dikhna chahiye.

### 6) Bot ko jagaye rakhna (zaroori)
Koyeb ka free instance **1 ghante tak koi HTTP traffic na aaye to sleep ho jata hai**, aur ye band nahi kiya ja sakta. Bot polling use karta hai, isliye sleep me bot band ho jayega.
Fix: [UptimeRobot](https://uptimerobot.com) (free) me ek **HTTP monitor** banayein, URL = `https://<aapka-app>.koyeb.app/health`, interval 5 minute.

> Note: Koyeb ke free plan ki shartein (card verification, regions, limits) badalti rehti hain — signup ke waqt dashboard / koyeb.com/pricing check kar lein.

## 👑 Admin guide

`/admin` bhejein (sirf `ADMIN_ID` ke liye):

| Button | Kaam |
|---|---|
| 📊 Stats | Users, junk, locked, entries, winners, active code |
| ➕ Add Giveaway Code | Step 1: code · Step 2: custom admin message (sahi code par user ko jata hai) |
| 🏆 Select Winner | Winner ID → Redeem Code → Confirm. Auto: DM + non-winner broadcast + DB reset |
| 📢 Broadcast | Koi bhi message (text/photo/video) sabhi active users ko |
| 🧹 Clear Junk | Blocked users ko permanently delete |

Naya giveaway: **Add Giveaway Code** → users code daalte hain → **Select Winner** → process khatam hote hi sab reset.

## ⚙️ Environment variables

| Variable | Default | Matlab |
|---|---|---|
| `BOT_TOKEN` | — (zaroori) | BotFather token |
| `MONGO_URI` | — (zaroori) | MongoDB Atlas URI |
| `DB_NAME` | `asb_freecodes_bot` | Database name |
| `ADMIN_ID` | `7315805581` | Admin Telegram ID |
| `SUPPORT_USERNAME` | `@asbhaibsr` | Support username |
| `TASK_CHANNEL_LINK` / `TASK_CHANNEL_ID` | `https://t.me/asfreecodes` / `-1004474019310` | Task channel |
| `LOG_CHANNEL_LINK` / `LOG_CHANNEL_ID` | `https://t.me/+Te9_yU3XUQE4MTg1` / `-1003099940809` | Private log channel |
| `MAX_WRONG_ATTEMPTS` | `3` | Isse zyada galat ⇒ lock |
| `LOCK_HOURS` | `24` | Lock duration |
| `SEND_RATE` | `20` | Broadcast speed (msg/sec) |
| `REQUIRE_JOIN` | `false` | `true` = code lene se pehle channel join check |
| `WINNER_NOTIFY` | `entries` | `entries` = sirf participants ko winner-message, `all` = sabhi users ko |

## 🧪 Local run

```bash
pip install -r requirements.txt
cp .env.example .env      # BOT_TOKEN aur MONGO_URI bharein
python bot.py
```

## 📝 Notes

- Code compare **case-insensitive** hota hai (`abc` = `ABC`).
- Winner declare hote hi sabke galat-attempt count aur locks bhi reset ho jate hain (purana code hat gaya, naya giveaway fresh shuru).
- Winner process chalte waqt giveaway "closing" rehta hai taaki beech me nayi entries na aayein.
- Agar winner ko DM nahi ja paya (usne bot block kiya/start nahi kiya), to **kuch bhi delete nahi hota** — dusra winner chun sakte hain.
- Support: @asbhaibsr
