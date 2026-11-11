# 🎁 ASB FreeCodes Bot (v3)

Telegram Giveaway Bot + Website + Mini App — **Python · aiogram 3 · MongoDB Atlas · aiohttp**, Koyeb par deploy hone ke liye ready.
Bot: http://t.me/ASBFreeCodesBot

> ✅ Ye bot **100% free** hai. Yahan kabhi paise, OTP, password ya card detail nahi maangi jaati. Winner ka proof hamesha channel par post hota hai.

## 📁 Files (GitHub repo me ye sab hone chahiye)

```
bot.py            ← main bot
site_app.py       ← website + API server
static/index.html ← website / Mini App page
requirements.txt  Dockerfile  .gitignore  .dockerignore  .env.example  README.md
```
GitHub app/web par `static/index.html` banane ke liye "Create new file" me naam `static/index.html` likhein — folder khud ban jayega.

## ✨ Features

### 🎁 Giveaway
| Feature | Kya karta hai |
|---|---|
| 🔑 Code entry | User code bhejta hai, ek giveaway me ek hi entry; galat code par lock (default 3 galat = 24 ghante) |
| 📍 Multi-platform links | Ek hi video YouTube + Instagram par ho to **2-4 links** do (`Instagram - link`, `YouTube - link`). User kisi bhi platform par ja sakta hai; har platform ka alag button |
| 📝 Note | Link ke alawa bhi bata sakte ho ki code kahan milega (jaise "Channel ke pinned post me"). Link skip kar sakte ho |
| ⏰ Winner date/time | Optional. `12 nov 9pm`, `kal 8:30pm`, `15/11 21:00` likho ya quick button dabao. Post, entry-confirm aur website par dikhta hai |
| 🔔 Time par ping | Winner time aate hi admin ko message (Random Pick / Select Winner button ke saath). Auto-winner nahi hota, kyunki redeem code aap dete ho |
| ⏳ 1 ghante pehle reminder | Winner time se 1 ghanta pehle entry karne walon ko DM reminder (agar giveaway 1 ghante se zyada pehle bana ho) |
| 🔒 Entries band (optional) | Winner time ke baad naye log entry nahi kar sakte (Preview/Edit card me ON/OFF) |
| ✏️ Edit Giveaway | Code, links, note, winner time, admin message — jo chahe wahi badlo. Entries safe rehti hain. Channel post khud update hoti hai |
| 📣 Repost | **Sirf chal rahe giveaway** ki post channel par dubara bhejta hai (purani delete). Khatam giveaway ka data delete ho jata hai, isliye uski repost nahi hoti |
| 📩 Admin message | Sahi code daalne par user ko DM me jata hai (optional, Skip kar sakte ho) |
| 🏆 Multi-winner | Ek giveaway me 1 se 5 winners, har ek ka alag redeem code |
| 🎲 Random Pick | Tickets ke hisaab se weighted random winner |
| 📣 Winner Proof | Winner declare hote hi channel par proof post; purani giveaway post "khatam ho gaya" ho jati hai |
| 🏆 Pichhle Winners | User ke menu me button: pichhle 5 winners (naam masked) + proof link |

### 🚀 Growth features
| Feature | Kya karta hai |
|---|---|
| 🛡 Verification | 1-tap math captcha — fake accounts/bots rokta hai |
| 👥 Refer & Earn | Referral link; verified dost = +1 ticket |
| 🎁 Daily Bonus | Roz claim, streak 3/7/14/30 din par +1/+2/+3/+5 tickets |
| 🎯 Reward Cards | Streak / refer poore karo, redeem code pao |
| ⚡ Free Code Drops | Time par live drop; Fast (sabse pehle tap) ya Lucky (random) mode |
| 🏅 Leaderboard | Top referrers / streaks (naam masked) |
| 🤝 Sponsors | Admin sponsor channels add karta hai; code dene se pehle join karna padta hai |
| 📢 Promo Broadcast | Koi bhi message + optional link button |
| 📣 Mini App Notice | Maintenance / offer ka notice Mini App ke upar sabko dikhta hai |
| 🌐 Website + Mini App | Live giveaway (saare platform links + winner time), winners proof wall, leaderboard, sponsors, FAQ; Telegram ke andar personal dashboard |

## 💰 v3 — Wallet, Invite Code, Withdraw, Weekly Leaderboard

| Feature | Kaise kaam karta hai |
|---|---|
| **Refer = ₹0.20** | Dost verify + channel join kare to referrer ke **balance** me ₹0.20 (+ 1 ticket + refer card progress). `REF_REWARD_RS` se badal sakte ho. |
| **Invite Code** | Har user ka invite code = uski **Telegram ID**. Bot (Refer & Earn → *Invite Code Daalo*) aur Mini App (Profile / Home) dono me daal sakte hain. Pehle channel join check hota hai — join nahi to mana, join karke dobara code daalna hota hai. Reciprocal (A↔B) aur apna code block hai. |
| **Weekly Leaderboard** | Sunday 00:00 IST → agla Sunday. Top 3 ko **₹15 / ₹10 / ₹5** automatically balance me (sirf jinke us hafte **10+ refers** ho). Result channel par bhi post hota hai. Fraud-flag wale ka prize ruk jata hai (admin ko alert). |
| **Reward Cards** | Card complete hone par user **Claim Now** dabata hai → paisa seedha profile balance me. |
| **Withdraw** | Balance ≥ ₹50 par UPI / Bank (A/C + IFSC) / Mobile + **sahi naam**. Request DB me pending save hoti hai, admin ko card jata hai (**Paid / Reject**). Aap paisa khud bhejte ho → *Paid* dabate hi user ko "paise mil gaye?" **Haan / Nahi** buttons jate hain, jawab aapko milta hai. *Reject* par paisa balance me wapas. Admin Panel → **💸 Withdrawals** me saari pending requests. |
| **Start menu** | Chhote small-caps buttons: *Enter Code* (bada) · *Help* + *Channel Join* · *Refer & Earn* + *About* · *Mini App*. About me @asbhaibsr, channel aur group link. |
| **New-user log** | Har naye user ka message log channel me (spike me batch ho jata hai, flood nahi). |
| **Winner result post** | Channel par winner (pura naam, tappable) + participants (jo nahi jeete) side-by-side, quote style. Mini App → Top → Winners me bhi dikhta hai. |
| **Blocked winner** | Agar winner ne bot block/delete kiya hai to wahi code apne aap kisi aur entrant ko chala jata hai. |

**Naye DB fields/collections:** `users.balance_p / earned_p / withdrawn_p` (paise me), `users.wkc.<hafte ki Sunday date>` (weekly refer count), `withdrawals` collection. Purane users ka data safe hai (fields apne aap bante hain).

**Update kaise karein:** purani files (`bot.py`, `site_app.py`, `static/index.html`, `.env.example`, `README.md`) replace karo, naye env variables (upar `.env.example` me) optional hain — default already set hain. Redeploy karo.

## 🌐 Website
Aapki Koyeb public URL ek proper website hai. Bot ke menu me **🎁 DAILY BONUS & REWARDS** button isi ko Telegram ke andar kholta hai (kuch install nahi karna). Mini App me user ka apna dashboard (tickets, streak, referrals, rank, referral link) dikhta hai — ye Telegram ke signed `initData` se verify hota hai, to koi doosre ka data nahi dekh sakta. Public page par sirf masked naam (`Ra***`) dikhte hain.

## 🔧 Setup (pehli baar)
1. **BotFather** se token → `BOT_TOKEN`.
2. **MongoDB Atlas** (M0 free): user banayein, Network Access `0.0.0.0/0`, connection string → `MONGO_URI`.
3. **Channels:** Log channel me bot **Admin**. Task channel me bot **Admin** (giveaway post, repost aur winner proof ke liye zaroori; `REQUIRE_JOIN=true` ho to membership check ke liye bhi).
4. Files GitHub par upload karein. ⚠️ `BOT_TOKEN`/`MONGO_URI` kabhi repo me na daalein.
5. **Koyeb:** Web Service → GitHub repo → Builder **Dockerfile** → Instance **Free** → env vars (`BOT_TOKEN`, `MONGO_URI`) → port **8000**, health check path **`/health`** → Deploy.
6. **Bot ko jagaye rakhna:** Koyeb free instance 1 ghante bina traffic ke sleep ho jata hai. UptimeRobot me HTTP monitor banayein: `https://<aapka-app-url>/health`, interval 5 min.
   ⚠️ Winner-time ping aur 1-ghante wala reminder tabhi chalte hain jab bot jaag raha ho, isliye UptimeRobot zaroor lagayein.

### Update karna (v2 → v2.1)
Naye `bot.py`, `site_app.py`, `static/index.html`, `README.md` repo me daalein — Koyeb auto-redeploy karega. Database purana hi rahega.
- Chal raha purana giveaway (sirf ek video link wala) waise hi kaam karta rahega.
- Edit me ek baar naye links daalte hi wo naye format me aa jayega.

## 👑 Admin guide (`/admin`)
| Button | Kaam |
|---|---|
| 📊 Stats | Users, verified, junk, locked, entries, referrals, sponsors, winners, active code, winner time |
| ➕ Add Giveaway Code | 5 step: Code → Links → Note → Winner time → Admin message → **Preview → Publish** |
| ✏️ Edit Giveaway | Kisi bhi cheez ko alag se badlo ya 🗑 hata do |
| 📣 Repost | Chal rahe giveaway ki channel post dubara bhejo |
| 🏆 Select Winner | ID type karein **ya** 🎲 Random Pick → Redeem Code → (➕ aur winner) → Confirm |
| 📢 Broadcast | Koi bhi message + optional link button |
| ⚡ Free Code Drop | Codes → time → mode → label → confirm |
| 🎯 Reward Cards / 📣 Notice | Mini App ke rewards aur notice |
| 🧹 Clear Junk | Blocked users permanently delete |
| 🤝 Sponsors | Sponsor add/remove (channel ID + join link; bot us channel me admin ho) |

Commands: `/admin`, `/ban <id>`, `/unban <id>`, `/cancel`.

### Links kaise dein (Step 2)
Har line me `platform - link`:
```
Instagram - https://instagram.com/reel/xxxx
YouTube - https://youtu.be/xxxx
```
Platform ka naam na likho to link se apne aap pehchan leta hai. Link nahi hai to **Skip** dabao aur Step 3 me likho ki code kahan milega.

### Winner time kaise dein (Step 4)
`12 nov 9pm` · `12 nov 9:30 pm` · `kal 8:30pm` · `aaj 9pm` · `3 din 9pm` · `15/11 21:00` (time hamesha IST). Ya quick buttons: Aaj / Kal / 3 din / 7 din, raat 9 baje.

### Giveaway ka data kab delete hota hai
Winner declare hote hi giveaway ka code, links, note aur sab entries delete ho jaati hain (aur galat-attempt locks reset). Sirf winner ka proof record (masked naam, date, proof link) bachta hai taaki "Pichhle Winners" me dikhe. Isliye khatam hue giveaway ko edit/repost nahi kar sakte — sirf jo abhi chal raha hai (winner declare nahi hua) wahi.

## ⚙️ Environment variables
`.env.example` me poori list hai. Ye hamesha apne Koyeb me set karke rakhein: `BOT_TOKEN`, `MONGO_URI`, `TASK_CHANNEL_ID`, `TASK_CHANNEL_LINK`, `LOG_CHANNEL_ID`, `WEBSITE_URL`.
Doosre: `REFERRAL_TICKETS` (1), `MAX_BONUS_TICKETS` (20), `MAX_SPONSORS` (5), `POST_WINNER_TO_CHANNEL` (true), `MAX_WRONG_ATTEMPTS` (3), `LOCK_HOURS` (24), `WINNER_NOTIFY` (`entries` ya `all`).

## 📝 Notes
- Tickets: entry = 1 ticket. Entry se pehle mile bonus tickets entry par lag jaate hain; entry ke baad mile (referral/streak) seedha entry me jodte hain. Random pick me cap = 1 + `MAX_BONUS_TICKETS`.
- Naya giveaway shuru karte waqt agar purana chal raha ho to bot pooochta hai: ✏️ Edit karo ya 🆕 Naya (purani entries delete).
- Multi-winner me agar kisi winner ko DM na ja paye to jinko code chala gaya unki entry hata di jati hai aur giveaway wapas khul jata hai; baaki winner dobara chun kar declare karein.
- Admin ka input session ab 30 minute tak chalta hai.
- Website 20 sec cache ke saath chalti hai, free instance par halki rehti hai.
- Support: @asbhaibsr
