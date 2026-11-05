# 🎁 ASB FreeCodes Bot (v2)

Telegram Giveaway Bot + Website + Mini App — **Python · aiogram 3 · MongoDB Atlas · aiohttp**, Koyeb par deploy hone ke liye ready.
Bot: http://t.me/ASBFreeCodesBot

## 📁 Files (GitHub repo me ye sab hone chahiye)

```
bot.py            ← main bot
site_app.py       ← website + API server (NAYA)
static/index.html ← website / Mini App page (NAYA)
requirements.txt  Dockerfile  .gitignore  .dockerignore  .env.example  README.md
```
GitHub app/web par `static/index.html` banane ke liye "Create new file" me naam `static/index.html` likhein — folder khud ban jayega.

## ✨ Features

**Giveaway (pehle jaisa):** /start welcome + 3 buttons, galat code lock (24h), ek entry per giveaway, admin custom message, log channel, winner flow (DM + non-winner broadcast + auto reset), FloodWait queue, Junk list.

**Naye features:**
| Feature | Kya karta hai |
|---|---|
| 🛡 Verification | 1-tap math captcha — fake accounts/bots rokta hai |
| 👥 Refer & Earn | Referral link; verified dost = +1 ticket |
| 🎁 Daily Bonus | Roz claim, streak 3/7/14/30 din par +1/+2/+3/+5 tickets |
| 🏅 Leaderboard | Top referrers (naam masked) |
| 🤝 Sponsors | Admin sponsor channels add karta hai; users ko code dene se pehle join karna padta hai; har sponsor ke "verified members" ginti dikhti hai |
| 🎲 Random Winner | Select Winner me "Random Pick" — tickets ke hisaab se weighted |
| 📣 Winner Proof | Winner declare hote hi task channel par proof post |
| 📢 Promo Broadcast | Broadcast ke saath link button (sponsor promotion ke liye) |
| 🌐 Website + Mini App | Live status, winners proof wall, leaderboard, sponsors, FAQ; Telegram ke andar personal dashboard |

## 🌐 Website
Aapki Koyeb public URL ab ek proper website hai. Bot ke menu me **🌐 Website** button hai aur chat ke menu button se bhi khulti hai (Telegram ke andar Mini App ki tarah). Mini App me user ka apna dashboard (tickets, streak, referrals, rank, referral link) dikhta hai — ye Telegram ke signed `initData` se verify hota hai, to koi doosre ka data nahi dekh sakta. Public page par sirf masked naam (`Ra***`) dikhte hain.

## 🔧 Setup (pehli baar)
1. **BotFather** se token → `BOT_TOKEN`.
2. **MongoDB Atlas** (M0 free): user banayein, Network Access `0.0.0.0/0`, connection string → `MONGO_URI`.
3. **Channels:** Log channel me bot **Admin**. Task channel me bot **Admin** (winner proof post ke liye; `REQUIRE_JOIN=true` ho to membership check ke liye bhi).
4. Files GitHub par upload karein. ⚠️ `BOT_TOKEN`/`MONGO_URI` kabhi repo me na daalein.
5. **Koyeb:** Web Service → GitHub repo → Builder **Dockerfile** → Instance **Free** → env vars (`BOT_TOKEN`, `MONGO_URI`) → port **8000**, health check path **`/health`** → Deploy.
6. **Bot ko jagaye rakhna:** Koyeb free instance 1 ghante bina traffic ke sleep ho jata hai. UptimeRobot me HTTP monitor banayein: `https://<aapka-app-url>/health`, interval 5 min. (Website par aane wale visitors ka traffic bhi count hota hai.)

### Update karna (v1 → v2)
Naye `bot.py`, `site_app.py`, `static/index.html`, `Dockerfile` repo me daalein — Koyeb auto-redeploy karega. Database purana hi rahega; purane users ko ek baar verification karna hoga.

## 👑 Admin guide (`/admin`)
| Button | Kaam |
|---|---|
| 📊 Stats | Users, verified, junk, locked, entries, referrals, sponsors, winners, active code |
| ➕ Add Giveaway Code | Code → custom admin message |
| 🏆 Select Winner | Winner ID type karein **ya** 🎲 Random Pick → Redeem Code → Confirm |
| 📢 Broadcast | Koi bhi message + optional link button |
| 🧹 Clear Junk | Blocked users permanently delete |
| 🤝 Sponsors | Sponsor add/remove (channel ID + join link; bot us channel me admin ho) |

**Sponsor se kamai kaise:** sponsor add karein → users ko wo channel join karna padta hai → Sponsors screen me "verified members" ka count sponsor ko dikha sakte hain. Sirf asli channels rakhein, 1–3 sponsor kaafi hain.

## ⚙️ Environment variables
`.env.example` me poori list hai. Naye: `WEBSITE_URL`, `REFERRAL_TICKETS` (1), `MAX_BONUS_TICKETS` (20), `MAX_SPONSORS` (5), `POST_WINNER_TO_CHANNEL` (true).

## 📝 Notes
- Tickets: entry = 1 ticket. Entry se pehle mile bonus tickets entry par lag jaate hain; entry ke baad mile (referral/streak) seedha entry me jodte hain. Random pick me cap = 1 + `MAX_BONUS_TICKETS`.
- Winner declare hone par code, entries aur galat-attempt/locks reset hote hain; tickets entries ke saath khatam.
- Winner ko DM na ja paye to kuch delete nahi hota.
- Website sirf ek ya do chhote queries cache ke saath chalati hai (20 sec cache), free instance par halki rehti hai.
- Support: @asbhaibsr
