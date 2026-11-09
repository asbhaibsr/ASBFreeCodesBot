"""
ASB FreeCodes Bot  —  Telegram Giveaway Bot  (v2)
Stack : Python 3.12 + aiogram 3 + MongoDB Atlas (PyMongo Async) + aiohttp website
Deploy: Koyeb (free web service)  ->  website + health server on $PORT
Bot   : http://t.me/ASBFreeCodesBot

Features: Giveaway codes, lock system, referral tickets, daily streak bonus,
human verification (captcha), sponsor channels, leaderboard, random winner,
promo broadcast (with button), winner proof post, website + Telegram Mini App.
v2.1: multi-platform links, winner date/time, edit + repost giveaway, multi-winner,
      entry-close at winner time, 1-hour reminder, past-winners proof button.
"""

import asyncio
import html
import logging
import os
import random
import re
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from urllib.parse import quote

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    User,
    WebAppInfo,
)
from aiogram.methods import AnswerCallbackQuery, CopyMessage, EditMessageText, SendMessage
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

import site_app
from site_app import fmt_when, gw_links, link_label, link_text, mask_name, short_name

try:  # local testing ke liye .env support (Koyeb par env variables use hote hain)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ======================================================================
#  CONFIG / VARIABLES
# ======================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()          # BotFather se (SECRET)
MONGO_URI = os.getenv("MONGO_URI", "").strip()          # MongoDB Atlas URI (SECRET)
DB_NAME = os.getenv("DB_NAME", "asb_freecodes_bot")

BOT_NAME = "ASB FreeCodes Bot"
BOT_LINK = os.getenv("BOT_LINK", "http://t.me/ASBFreeCodesBot")
BOT_USERNAME = BOT_LINK.rstrip("/").split("/")[-1]

WEBSITE_URL = os.getenv(
    "WEBSITE_URL", "https://worrying-theodosia-asbhaibsr-5d8015e1.apps.mistral.run"
).rstrip("/")

ADMIN_ID = int(os.getenv("ADMIN_ID", "7315805581"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@asbhaibsr")
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"

TASK_CHANNEL_LINK = os.getenv("TASK_CHANNEL_LINK", "https://t.me/asfreecodes")
TASK_CHANNEL_ID = int(os.getenv("TASK_CHANNEL_ID", "-1002892671107"))

LOG_CHANNEL_LINK = os.getenv("LOG_CHANNEL_LINK", "https://t.me/+Te9_yU3XUQE4MTg1")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003099940809"))

MAX_WRONG_ATTEMPTS = int(os.getenv("MAX_WRONG_ATTEMPTS", "3"))   # isse zyada galat => lock
LOCK_HOURS = int(os.getenv("LOCK_HOURS", "24"))
SEND_RATE = float(os.getenv("SEND_RATE", "25"))                  # messages / second (limit ~30)
REQUIRE_JOIN = os.getenv("REQUIRE_JOIN", "false").lower() == "true"
WINNER_NOTIFY = os.getenv("WINNER_NOTIFY", "entries").lower()    # "entries" ya "all"
PORT = int(os.getenv("PORT", "8000"))

REFERRAL_TICKETS = int(os.getenv("REFERRAL_TICKETS", "1"))       # per verified referral
MAX_BONUS_TICKETS = int(os.getenv("MAX_BONUS_TICKETS", "20"))    # random pick me cap (1 + 20)
MAX_SPONSORS = int(os.getenv("MAX_SPONSORS", "5"))
POST_WINNER_TO_CHANNEL = os.getenv("POST_WINNER_TO_CHANNEL", "true").lower() == "true"
STREAK_REWARDS = {3: 1, 7: 2, 14: 3, 30: 5}                      # streak din -> bonus tickets
DROP_TIMEOUT_MIN = float(os.getenv("DROP_TIMEOUT_MIN", "10"))     # live drop max kitni der chalega
DROP_MAX_CODES = int(os.getenv("DROP_MAX_CODES", "50"))
BULK_RATE = float(os.getenv("BULK_RATE", "12"))                    # broadcast/DM fan-out speed (msg/sec)
LUCKY_WINDOW = int(os.getenv("LUCKY_WINDOW", "10"))                 # lucky drop join window (sec)
STREAK_GRACE_DAYS = int(os.getenv("STREAK_GRACE_DAYS", "0"))        # 0 = sakht (ek din miss = streak reset)
REFERRAL_REQUIRE_JOIN = os.getenv("REFERRAL_REQUIRE_JOIN", "true").lower() == "true"
STREAK_REMIND_HOUR = int(os.getenv("STREAK_REMIND_HOUR", "20"))     # IST
STREAK_REMIND_MIN = int(os.getenv("STREAK_REMIND_MIN", "5"))        # kam se kam itni streak par reminder
STREAK_REMIND_MAX = int(os.getenv("STREAK_REMIND_MAX", "400"))
MAX_CONCURRENT_UPDATES = int(os.getenv("MAX_CONCURRENT_UPDATES", "25"))
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "300"))
USER_THROTTLE_SEC = float(os.getenv("USER_THROTTLE_SEC", "0.6"))
MEM_ALERT_MB = float(os.getenv("MEM_ALERT_MB", "380"))
LOAD_ALERT_PER_MIN = int(os.getenv("LOAD_ALERT_PER_MIN", "900"))
ALERT_COOLDOWN_SEC = float(os.getenv("ALERT_COOLDOWN_SEC", "600"))
MINIAPP_LINK = os.getenv("MINIAPP_LINK", "").strip()              # optional: https://t.me/ASBFreeCodesBot/app (BotFather /newapp)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("asb-bot")

IST = timezone(timedelta(hours=5, minutes=30))

# shared state (Mini App server bhi yahi dicts padhta hai)
REWARD_CFG = {
    "streak": [[20, 10], [50, 20], [100, 40], [200, 75]],
    "refer": [[15, 10], [30, 20], [50, 35], [100, 70], [200, 150]],
}
STATUS = {"degraded": False, "msg": ""}
NOTICE = {"text": ""}
live_state = {"v": 0, "drop": None}

# website ke liye shared context (db collections bot start hone par bharte hain)
site_ctx = {
    "live": live_state,
    "status": STATUS,
    "notice": NOTICE,
    "reward_cfg": REWARD_CFG,
    "hooks": {},
    "db": {},
    "actions": {},
    "bot_token": BOT_TOKEN,
    "public": {
        "bot_username": BOT_USERNAME,
        "bot_link": f"https://t.me/{BOT_USERNAME}",
        "channel_link": TASK_CHANNEL_LINK,
        "support_username": SUPPORT_USERNAME,
        "support_link": SUPPORT_LINK,
        "lucky_window": LUCKY_WINDOW,
    },
}

# ======================================================================
#  GLOBALS (main() me set hote hain)
# ======================================================================
bot: Bot = None  # type: ignore
mongo: AsyncMongoClient = None  # type: ignore
users = entries = states = config = winners = sponsors = sponsor_joins = None
drops = drop_codes = drop_claims = rewards = None
drop_tasks: dict = {}

router = Router()
router.message.filter(F.chat.type == "private")

broadcast_lock = asyncio.Lock()
_tasks: set = set()

OK, JUNK, FAIL = "ok", "junk", "fail"
JUNK_HINTS = (
    "chat not found",
    "user is deactivated",
    "peer_id_invalid",
    "bot was blocked",
    "bot can't initiate",
    "have no rights to send",
)


# ======================================================================
#  SMALL HELPERS
# ======================================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def fmt_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")


def fmt_td(td: timedelta) -> str:
    total = max(int(td.total_seconds()), 0)
    h, rem = divmod(total, 3600)
    return f"{h} ghante {rem // 60} minute"


def esc(value) -> str:
    return html.escape(str(value or ""))


def full_name(u: User) -> str:
    return " ".join(p for p in (u.first_name, u.last_name) if p) or "User"


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def btn(
    text: str,
    data: Optional[str] = None,
    url: Optional[str] = None,
    web_app: Optional[str] = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=data,
        url=url,
        web_app=WebAppInfo(url=web_app) if web_app else None,
    )


def kb(*rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def ref_link(uid: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"


def code_where_text(gw: Optional[dict]) -> str:
    """'Code yahan milega' block (note + links ke liye)."""
    gw = gw or {}
    links, note = gw_links(gw), gw.get("note")
    if not links and not note:
        return ""
    lines = ["📍 <b>Code yahan milega:</b>"]
    if note:
        lines.append(note)
    if links:
        lines.append("👇 <i>Neeche ke button se jaakar code dhundo</i>")
    return "\n".join(lines)


def when_line(gw: Optional[dict]) -> str:
    wa = (gw or {}).get("winner_at")
    return f"⏰ <b>Winner:</b> {esc(fmt_when(wa))}" if wa else ""


def code_links_rows(gw: Optional[dict]) -> list:
    return [[btn(link_text(l), url=l["url"])] for l in gw_links(gw)]


def giveaway_post_text(gw: dict) -> str:
    parts = ["🎁 <b>GIVEAWAY LIVE HAI!</b> 🔥", ""]
    where = code_where_text(gw)
    if where:
        parts += [where, ""]
    wt = when_line(gw)
    if wt:
        parts += [wt, ""]
    parts += [
        "<b>Kaise bhaag lein?</b>",
        "1️⃣ Upar bataye gaye jagah se <b>code</b> dhundo",
        "2️⃣ <b>🔑 Enter Code</b> dabake bot me code bhejo",
        "3️⃣ Winner ko <b>redeem code</b> seedha DM me milta hai 🏆",
        "",
        "✅ <b>100% FREE</b> — koi paise nahi maange jaate",
        f"⚠️ <i>Galat code baar-baar daaloge to {LOCK_HOURS} ghante ka lock lag jayega.</i>",
    ]
    return "\n".join(parts)


def giveaway_post_kb(gw: dict) -> InlineKeyboardMarkup:
    rows = code_links_rows(gw)
    rows.append([btn("🔑 Enter Code", url=f"https://t.me/{BOT_USERNAME}?start=code")])
    return kb(*rows)


def app_link() -> str:
    """Channel posts ke liye Mini App link (BotFather direct link ho to wahi, warna bot deep-link)."""
    return MINIAPP_LINK or f"https://t.me/{BOT_USERNAME}?start=drop"


# ---------------------------------------------------------------- keyboards
def main_menu_kb(verified: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if not verified:
        rows.append([btn("🛡 VERIFY KARO (1 tap)", "verify")])
    rows += [
        [btn("🔑 CODE DAALO — GIVEAWAY ENTRY", "enter_code")],
        [btn("📢 CHANNEL JOIN KARO", url=TASK_CHANNEL_LINK)],
        [btn("🎁 DAILY BONUS & REWARDS", web_app=WEBSITE_URL)],
        [btn("🏆 Pichhle Winners (Proof)", "winners")],
        [btn("❓ Kaise Kaam Karta Hai?", "help")],
    ]
    return kb(*rows)


async def user_menu(uid: int) -> InlineKeyboardMarkup:
    return main_menu_kb(await is_verified(uid))


def channel_kb() -> InlineKeyboardMarkup:
    return kb([btn("📢 Join Channel", url=TASK_CHANNEL_LINK)])


def retry_kb(gw: Optional[dict] = None) -> InlineKeyboardMarkup:
    rows = code_links_rows(gw) if gw else []
    rows += [
        [btn("🔑 Dobara Code Daalo", "enter_code")],
        [btn("📢 Join Channel", url=TASK_CHANNEL_LINK)],
    ]
    return kb(*rows)


def back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Menu", "menu")])


def admin_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("📊 Stats", "adm:stats")],
        [btn("➕ Add Giveaway Code", "adm:add")],
        [btn("✏️ Edit Giveaway", "adm:edit"), btn("📣 Repost", "adm:repost")],
        [btn("🏆 Select Winner", "adm:winner")],
        [btn("📢 Broadcast", "adm:bc")],
        [btn("⚡ Free Code Drop", "adm:drop"), btn("🤝 Sponsors", "adm:sponsors")],
        [btn("📥 Reward Requests", "adm:rw"), btn("🎯 Reward Cards", "adm:rwcfg")],
        [btn("📣 Notice", "adm:notice"), btn("🧹 Clear Junk", "adm:junk")],
    )


def admin_back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Admin Panel", "adm:home")])


def admin_cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn("❌ Cancel", "adm:home")])


ADMIN_HOME_TEXT = "👑 <b>Admin Panel</b>\n\nKya karna chahte hain? 👇"


# ---------------------------------------------------------------- texts
def welcome_text(name: str) -> str:
    return (
        f"👋 <b>Namaste {esc(name)}!</b>\n"
        f"🎁 <b>{BOT_NAME}</b> me aapka swagat hai\n\n"
        "✅ <b>Bilkul FREE</b> — <i>yahan kabhi paise, OTP ya password nahi maange jaate.</i>\n\n"
        "<b>Kaise kaam karta hai? (sirf 3 step)</b>\n"
        "1️⃣ Video / post me chhupa <b>code</b> dhundo\n"
        "2️⃣ <b>🔑 CODE DAALO</b> dabake code bhejo\n"
        "3️⃣ Winner ko <b>redeem code</b> seedha DM me milta hai 🏆\n\n"
        "🎁 <b>Daily Bonus &amp; Rewards</b> me roz ka bonus, Refer &amp; Earn aur Free Code Drops milte hain — "
        "ye <i>Telegram ke andar hi khulta hai, kuch install nahi karna.</i>\n\n"
        "👇 <b>Shuru karne ke liye neeche button dabayein:</b>"
    )


def help_text() -> str:
    return (
        "❓ <b>Kaise kaam karta hai?</b>\n\n"
        "1️⃣ <b>🛡 Verify</b> — 1 tap me verification (fake accounts rokne ke liye)\n"
        "2️⃣ <b>📢 Channel Join</b> karein\n"
        "3️⃣ Video / post me bataye gaye <b>📍 jagah</b> se code dhundein\n"
        "4️⃣ <b>🔑 CODE DAALO</b> dabake code bhejein — entry confirm ✅\n"
        "5️⃣ Winner ko redeem code seedha <b>DM</b> me milta hai 🏆\n\n"
        "🎁 <b>Daily Bonus &amp; Rewards</b> me:\n"
        f"• 👥 Refer &amp; Earn: har verified dost = +{REFERRAL_TICKETS} ticket\n"
        "• 🔥 Daily Bonus: streak 3/7/14/30 din par extra tickets\n"
        "• 🎯 Reward Cards: streak / refer poore karo, ₹ redeem code pao\n"
        "• ⚡ Free Code Drops: time par sabse pehle CLAIM karo\n"
        "• 🎟 Live entries, 🏆 winners aur 🏅 leaderboard\n\n"
        "🔒 <b>Safe hai?</b>\n"
        "• Yahan kabhi paise, OTP, password ya card detail nahi maangi jaati\n"
        "• Winner ka proof hamesha channel par post hota hai (<b>🏆 Pichhle Winners</b> button)\n"
        "• Winner random pick (tickets ke hisaab se) se bhi chuna jata hai\n\n"
        "⚠️ <b>Dhyan rahe:</b>\n"
        f"• {MAX_WRONG_ATTEMPTS} baar se zyada galat code par <b>{LOCK_HOURS} ghante</b> ka lock lag jata hai\n"
        "• Ek giveaway me sirf <b>ek hi entry</b> hoti hai — spam na karein\n\n"
        f"🆘 Support: {esc(SUPPORT_USERNAME)}"
    )


def entry_confirmed_text(
    admin_msg: Optional[str], tickets: int = 1, entry_no: Optional[int] = None, winner_at: Optional[datetime] = None
) -> str:
    lines = ["🎉 <b>Badhai ho! Aapki entry confirm ho gayi</b> ✅", ""]
    if entry_no:
        lines.append(f"🔢 Entry No: <b>#{entry_no}</b>")
    lines.append(f"🎟 Aapke tickets: <b>{tickets}</b>")
    if winner_at:
        lines.append(f"⏰ Winner chuna jayega: <b>{esc(fmt_when(winner_at))}</b>")
    lines += [
        "",
        "⏳ Ab bas <b>intezaar</b> karein — aur kuch karna zaroori nahi.",
        "🏆 Winner ko redeem code seedha uske <b>personal DM</b> me milega.",
        f"📢 Result aur proof channel par post hoga:\n{TASK_CHANNEL_LINK}",
        "",
        "💡 Tickets badhane ke liye <b>Refer &amp; Earn</b> aur <b>Daily Bonus</b> use karein (🎁 Rewards button).",
    ]
    base = "\n".join(lines)
    if admin_msg:
        base += "\n\n━━━━━━━━━━━━━━\n📩 <b>Admin ka message:</b>\n\n" + admin_msg
    return base


def winner_dm_text(code: str) -> str:
    return (
        "🏆 <b>CONGRATULATIONS! Aap WINNER ho!</b> 🎉\n\n"
        "🎁 Ye raha aapka <b>Redeem Code</b>:\n\n"
        f"<code>{esc(code)}</code>\n\n"
        "👆 Code par tap karke copy kar lein.\n\n"
        f"📢 Channel: {TASK_CHANNEL_LINK}\n"
        f"🆘 Support: {esc(SUPPORT_USERNAME)}"
    )


def non_winner_text(winner_label: str, n: int = 1) -> str:
    who = (
        f"🏆 <b>{winner_label}</b> aaj ka winner ban gaya hai 🎉"
        if n == 1
        else f"🏆 <b>{winner_label}</b> aaj ke {n} winners ban gaye hain 🎉"
    )
    return (
        "📢 <b>Giveaway ka Winner declare ho gaya!</b>\n\n"
        f"{who}\n\n"
        "😊 Aap niraash na hon — <b>agli baar zaroor try karein!</b>\n"
        "Hamare channel par bane rahein, kabhi-kabhi yahan <b>free redeem codes</b> "
        "bhi milte rehte hain 🎁\n\n"
        "🔒 Winner ka proof channel par post ho chuka hai.\n"
        f"🆘 Support ke liye contact karein: {esc(SUPPORT_USERNAME)}"
    )


# ======================================================================
#  DATABASE HELPERS
# ======================================================================
async def init_db() -> None:
    global mongo, users, entries, states, config, winners, sponsors, sponsor_joins
    global drops, drop_codes, drop_claims, rewards
    mongo = AsyncMongoClient(
        MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, socketTimeoutMS=15000,
        maxPoolSize=int(os.getenv("MONGO_POOL", "30")), minPoolSize=0, maxIdleTimeMS=60000, appName="asb-bot",
    )
    await mongo.admin.command("ping")
    db = mongo[DB_NAME]
    users, entries, states = db["users"], db["entries"], db["states"]
    config, winners = db["config"], db["winners"]
    sponsors, sponsor_joins = db["sponsors"], db["sponsor_joins"]
    drops, drop_codes, drop_claims = db["drops"], db["drop_codes"], db["drop_claims"]
    rewards = db["rewards"]
    await states.create_index("expires_at", expireAfterSeconds=0)  # TTL auto-clean
    await users.create_index("junk")
    await users.create_index([("ref_count", -1)])
    await sponsor_joins.create_index("sid")
    await drop_codes.create_index([("drop", 1), ("claimed_by", 1)])
    await drop_claims.create_index([("drop", 1), ("rank", 1)])
    await drop_claims.create_index("uid")
    await rewards.create_index([("uid", 1), ("earned_at", -1)])
    await rewards.create_index([("status", 1), ("remind_at", 1)])
    await users.create_index("streak")
    cfg = await config.find_one({"_id": "reward_cfg"})
    for k in ("streak", "refer"):
        if cfg and cfg.get(k):
            REWARD_CFG[k] = cfg[k]
    nt = await config.find_one({"_id": "notice"})
    NOTICE["text"] = (nt or {}).get("text", "")
    site_ctx["db"].update(
        users=users, entries=entries, config=config, winners=winners, sponsors=sponsors,
        drops=drops, drop_claims=drop_claims, rewards=rewards,
    )
    logger.info("MongoDB connected ✅  (db=%s)", DB_NAME)


_ucache: dict = {}
_touched: dict = {}
UCACHE_TTL = 120.0


async def get_user_cached(uid: int) -> Optional[dict]:
    """User ke zaroori fields (2 min cache) — DB hits kam karne ke liye."""
    now = time.monotonic()
    hit = _ucache.get(uid)
    if hit and now - hit[0] < UCACHE_TTL:
        return hit[1]
    u = await users.find_one(
        {"_id": uid}, {"name": 1, "username": 1, "verified": 1, "banned": 1, "ref_by": 1, "ref_credited": 1}
    )
    if len(_ucache) > 20000:
        _ucache.clear()
    if u:
        _ucache[uid] = (now, u)
    return u


def invalidate_user(uid: int) -> None:
    _ucache.pop(uid, None)
    _touched.pop(uid, None)


async def touch_user(u: User, force: bool = False) -> bool:
    """User ko save/update karo (10 min me ek baar hi DB write). True = bilkul naya user."""
    now = time.monotonic()
    if not force and now - _touched.get(u.id, -1e9) < 600:
        return False
    res = await users.update_one(
        {"_id": u.id},
        {
            "$set": {
                "name": full_name(u),
                "username": u.username,
                "last_seen": now_utc(),
                "junk": False,
            },
            "$unset": {"junk_at": ""},
            "$setOnInsert": {
                "joined_at": now_utc(),
                "wrong_count": 0,
                "locked_until": None,
                "verified": False,
                "ref_count": 0,
                "bonus_tickets": 0,
                "streak": 0,
            },
        },
        upsert=True,
    )
    if len(_touched) > 50000:
        _touched.clear()
    _touched[u.id] = now
    return res.upserted_id is not None


async def mark_junk(uid: int) -> None:
    await users.update_one({"_id": uid}, {"$set": {"junk": True, "junk_at": now_utc()}})


async def is_verified(uid: int) -> bool:
    u = await get_user_cached(uid)
    return bool(u and u.get("verified"))


async def set_state(uid: int, name: str, data: Optional[dict] = None, ttl_min: int = 30) -> None:
    await states.replace_one(
        {"_id": uid},
        {
            "_id": uid,
            "name": name,
            "data": data or {},
            "expires_at": now_utc() + timedelta(minutes=ttl_min),
        },
        upsert=True,
    )


async def get_state(uid: int) -> Optional[dict]:
    doc = await states.find_one({"_id": uid})
    if not doc:
        return None
    if doc["expires_at"] < now_utc():
        await states.delete_one({"_id": uid})
        return None
    return doc


async def clear_state(uid: int) -> None:
    await states.delete_one({"_id": uid})


async def get_giveaway() -> Optional[dict]:
    return await config.find_one({"_id": "giveaway"})


async def lock_remaining(uid: int) -> Optional[timedelta]:
    u = await users.find_one({"_id": uid}, {"locked_until": 1})
    lu = (u or {}).get("locked_until")
    if not lu:
        return None
    if lu > now_utc():
        return lu - now_utc()
    await users.update_one({"_id": uid}, {"$set": {"wrong_count": 0, "locked_until": None}})
    return None


async def has_entered(uid: int) -> bool:
    return await entries.find_one({"_id": uid}, {"_id": 1}) is not None


async def add_tickets(uid: int, n: int) -> None:
    """Entry hai to seedha entry me, nahi to bonus_tickets me (agli entry par lagenge)."""
    res = await entries.update_one({"_id": uid}, {"$inc": {"tickets": n}})
    if res.matched_count == 0:
        await users.update_one({"_id": uid}, {"$inc": {"bonus_tickets": n}})


async def non_winner_ids(winner_id) -> list:
    """winner_id: ek id ya ids ka set/list — in sabko chhodkar baaki."""
    skip = list(winner_id) if isinstance(winner_id, (set, list, tuple)) else [winner_id]
    if WINNER_NOTIFY == "all":
        cur = users.find({"junk": {"$ne": True}, "_id": {"$nin": skip}}, {"_id": 1})
        return [d["_id"] async for d in cur]
    ids = [d["_id"] async for d in entries.find({"_id": {"$nin": skip}}, {"_id": 1})]
    if not ids:
        return []
    cur = users.find({"_id": {"$in": ids}, "junk": {"$ne": True}}, {"_id": 1})
    return [d["_id"] async for d in cur]


async def pick_random_winner(exclude: Optional[set] = None) -> Optional[dict]:
    """Tickets ke hisaab se weighted random pick (cap: 1 + MAX_BONUS_TICKETS)."""
    docs = [d async for d in entries.find({}, {"_id": 1, "tickets": 1})]
    junk = {d["_id"] async for d in users.find({"junk": True}, {"_id": 1})}
    skip = set(exclude or ())
    pool = [d for d in docs if d["_id"] not in junk and d["_id"] not in skip]
    if not pool:
        return None
    cap = 1 + MAX_BONUS_TICKETS
    weights = [min(max(int(d.get("tickets", 1)), 1), cap) for d in pool]
    return random.SystemRandom().choices(pool, weights=weights, k=1)[0]


# ======================================================================
#  RATE LIMIT QUEUE + FLOODWAIT PROTECTION
# ======================================================================
class RateLimiter:
    """Messages ko fixed speed par nikalta hai; FloodWait aaye to sabko pause kar deta hai."""

    def __init__(self, rate: float):
        self.interval = 1.0 / max(rate, 1.0)
        self._next = 0.0
        self._pause_until = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next, self._pause_until)
            self._next = start + self.interval
        delay = start - now
        if delay > 0:
            await asyncio.sleep(delay)

    def pause(self, seconds: float) -> None:
        self._pause_until = max(self._pause_until, time.monotonic() + seconds)


limiter = RateLimiter(SEND_RATE)          # saare outgoing messages (middleware)
bulk_limiter = RateLimiter(BULK_RATE)     # broadcast / DM fan-out (interactive replies ko jagah milti hai)


async def deliver_result(uid: int, sender: Callable[[int], Awaitable]) -> tuple:
    """Ek message safely bhejta hai. Returns (OK/JUNK/FAIL, telegram result)."""
    for _ in range(6):
        try:
            return OK, await sender(uid)
        except TelegramRetryAfter as e:
            wait = int(e.retry_after) + 1
            logger.warning("FloodWait %ss — queue paused", wait)
            limiter.pause(wait)
        except TelegramForbiddenError:
            return JUNK, None
        except TelegramBadRequest as e:
            if any(h in str(e).lower() for h in JUNK_HINTS):
                return JUNK, None
            logger.warning("BadRequest (%s): %s", uid, e)
            return FAIL, None
        except TelegramNetworkError:
            await asyncio.sleep(2)
        except TelegramAPIError as e:
            logger.warning("TelegramAPIError (%s): %s", uid, e)
            return FAIL, None
    return FAIL, None


async def deliver(uid: int, sender: Callable[[int], Awaitable]) -> str:
    """Result: OK / JUNK (blocked etc.) / FAIL."""
    return (await deliver_result(uid, sender))[0]


async def run_broadcast(uids: list, sender: Callable[[int], Awaitable], on_progress=None) -> dict:
    stats = {"total": len(uids), "sent": 0, "junk": 0, "failed": 0}
    for i, uid in enumerate(uids, 1):
        await bulk_limiter.wait()
        res = await deliver(uid, sender)
        if res == OK:
            stats["sent"] += 1
        elif res == JUNK:
            stats["junk"] += 1
            await mark_junk(uid)  # blocked user -> Junk List
        else:
            stats["failed"] += 1
        if on_progress:
            await on_progress(i, stats)
    return stats


def make_progress(status_msg: Message, label: str):
    last = [0.0]

    async def _cb(done: int, stats: dict) -> None:
        if done < stats["total"] and time.monotonic() - last[0] < 8:
            return
        last[0] = time.monotonic()
        try:
            await bot.edit_message_text(
                f"{label}\n⏳ {done}/{stats['total']}  |  ✅ {stats['sent']}  |  "
                f"🚫 {stats['junk']}  |  ⚠️ {stats['failed']}",
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
            )
        except TelegramAPIError:
            pass

    return _cb


async def safe_log(text: str) -> None:
    res = await deliver(LOG_CHANNEL_ID, lambda cid: bot.send_message(cid, text))
    if res != OK:
        logger.warning("Log channel me message nahi gaya (bot ko channel me admin banayein).")


async def notify_admin(text: str, markup: Optional[InlineKeyboardMarkup] = None) -> None:
    await deliver(ADMIN_ID, lambda cid: bot.send_message(cid, text, reply_markup=markup))


async def safe_edit(cb: CallbackQuery, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return
        await bot.send_message(cb.from_user.id, text, reply_markup=markup)


# ======================================================================
#  LOAD PROTECTION + ADMIN ALERTS  (free tier par bhi hang na ho)
# ======================================================================
metrics = {"updates": 0, "shed": 0, "errors": 0, "flood": 0}
_alert_last: dict = {}
_alert_skipped: dict = {}


async def alert_admin(key: str, text: str, cooldown: Optional[float] = None) -> None:
    """Admin ko Telegram par alert. Same type ka alert cooldown ke andar dobara nahi jata."""
    if bot is None:
        return
    cd = ALERT_COOLDOWN_SEC if cooldown is None else cooldown
    now = time.monotonic()
    if now - _alert_last.get(key, -1e9) < cd:
        _alert_skipped[key] = _alert_skipped.get(key, 0) + 1
        return
    _alert_last[key] = now
    extra = _alert_skipped.pop(key, 0)
    if extra:
        text += f"\n\n(+{extra} baar aur hua is dauran)"
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as e:  # alert fail hone se kuch nahi rukna chahiye
        logger.warning("alert_admin fail: %s", e)


def note_flood(seconds: int) -> None:
    metrics["flood"] += 1
    if seconds >= 10:
        spawn(alert_admin("flood", f"⚠️ <b>Telegram FloodWait</b> — sending {seconds}s ke liye slow ki gayi (traffic zyada hai)."))


PACED_METHODS = (SendMessage, CopyMessage, EditMessageText)


class PacedRequests(BaseRequestMiddleware):
    """Saare outgoing messages ko ek global speed par nikalta hai + FloodWait par auto-retry."""

    async def __call__(self, make_request, bot, method):
        paced = isinstance(method, PACED_METHODS)
        for attempt in range(4):
            if paced:
                await limiter.wait()
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as e:
                wait = int(e.retry_after) + 1
                note_flood(wait)
                if isinstance(method, AnswerCallbackQuery) or attempt == 3:
                    raise
                if paced:
                    limiter.pause(wait)
                else:
                    await asyncio.sleep(wait)


class LoadGuard(BaseMiddleware):
    """Ek saath bahut updates aaye to bot hang na ho: concurrency cap + spam throttle + load shedding."""

    def __init__(self) -> None:
        self.sem = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)
        self.inflight = 0
        self.last: dict = {}

    @staticmethod
    def _user(update):
        if getattr(update, "callback_query", None):
            return update.callback_query.from_user
        if getattr(update, "message", None):
            return update.message.from_user
        return None

    async def __call__(self, handler, event, data):
        metrics["updates"] += 1
        user = self._user(event)
        if user and user.id != ADMIN_ID:
            now = time.monotonic()
            if now - self.last.get(user.id, -1e9) < USER_THROTTLE_SEC:
                return None  # button-mashing / spam ignore
            if len(self.last) > 50000:
                self.last.clear()
            self.last[user.id] = now
        if self.inflight >= MAX_QUEUE:
            metrics["shed"] += 1
            spawn(alert_admin("overload", "🚨 <b>Bot par bahut zyada load hai</b> — kuch requests skip ho rahi hain. Traffic kam hote hi normal ho jayega."))
            cbq = getattr(event, "callback_query", None)
            if cbq:
                try:
                    await cbq.answer("⏳ Bahut zyada traffic hai — 1 minute baad try karein 🙏", show_alert=True)
                except Exception:
                    pass
            return None
        self.inflight += 1
        try:
            async with self.sem:
                return await handler(event, data)
        finally:
            self.inflight -= 1


def rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


async def monitor_loop() -> None:
    """Har 10s event-loop lag, har ~1 min DB ping / memory / traffic check; dikkat par admin ko alert."""
    last = time.monotonic()
    ticks = bad_db = lag_bad = 0
    down = False
    while True:
        await asyncio.sleep(10)
        now = time.monotonic()
        lag = now - last - 10
        last = now
        ticks += 1
        lag_bad = lag_bad + 1 if lag > 3 else 0
        if lag_bad >= 2:
            spawn(alert_admin("lag", f"🐢 <b>Bot slow chal raha hai</b> (lag {lag:.1f}s) — server par load zyada ho sakta hai."))
        if ticks % 6:
            continue
        try:
            await asyncio.wait_for(mongo.admin.command("ping"), 8)
            bad_db = 0
            if down:
                down = False
                STATUS.update(degraded=False, msg="")
                spawn(alert_admin("db_up", "🟢 <b>Database wapas OK</b> — bot normal chal raha hai.", cooldown=0))
        except Exception:
            bad_db += 1
            if bad_db >= 2 and not down:
                down = True
                STATUS.update(degraded=True, msg="Technical dikkat chal rahi hai — thodi der baad try karein 🙏")
                spawn(alert_admin("db_down", "🔴 <b>Database connect nahi ho raha!</b>\nUsers ko 'thodi der baad try karein' dikh raha hai. MongoDB Atlas / network check karein.", cooldown=0))
        ups, metrics["updates"] = metrics["updates"], 0
        if ups > LOAD_ALERT_PER_MIN:
            spawn(alert_admin("load", f"📈 <b>Traffic zyada hai</b>: ~{ups} requests/min. Bot protection mode me chal raha hai."))
        mem = rss_mb()
        if mem > MEM_ALERT_MB:
            spawn(alert_admin("mem", f"🧠 <b>Memory zyada</b>: {mem:.0f} MB (free limit 512 MB). Restart ho sakta hai.", cooldown=1800))


@router.errors()
async def on_error(event: ErrorEvent):
    exc = event.exception
    metrics["errors"] += 1
    logger.error("Handler error: %r", exc, exc_info=exc)
    spawn(
        alert_admin(
            f"err:{type(exc).__name__}",
            f"⚠️ <b>Bot error</b>\n<code>{esc(type(exc).__name__)}</code>: {esc(str(exc))[:300]}",
            cooldown=300,
        )
    )
    upd = event.update
    try:
        if upd.callback_query:
            await upd.callback_query.answer("⚠️ Abhi thodi dikkat hai — kuch der baad try karein 🙏", show_alert=True)
        elif upd.message:
            await upd.message.answer("⚠️ Abhi thodi technical dikkat hai. Kuch der baad dobara try karein 🙏\nAdmin ko khabar mil gayi hai.")
    except Exception:
        pass
    return True


# ======================================================================
#  CHANNEL MEMBERSHIP (task channel optional + sponsors)
# ======================================================================
async def is_member(chat_id: int, uid: int) -> Optional[bool]:
    """True/False, ya None agar verify nahi ho paya (bot channel me admin nahi)."""
    try:
        member = await bot.get_chat_member(chat_id, uid)
    except TelegramAPIError as e:
        logger.warning("Membership check fail (chat %s): %s", chat_id, e)
        return None
    if member.status in ("left", "kicked"):
        return False
    if member.status == "restricted":
        return bool(getattr(member, "is_member", True))
    return True


async def required_channels() -> list:
    chans = []
    if REQUIRE_JOIN:
        chans.append(
            {"_id": TASK_CHANNEL_ID, "title": "Official Channel", "link": TASK_CHANNEL_LINK, "main": True}
        )
    async for s in sponsors.find({"active": True}):
        chans.append(s)
    return chans


async def missing_channels(uid: int) -> list:
    missing = []
    for ch in await required_channels():
        ok = await is_member(ch["_id"], uid)
        if ok is False:
            missing.append(ch)
        elif ok is True and not ch.get("main"):  # sponsor ke liye verified member record
            try:
                await sponsor_joins.insert_one(
                    {"_id": f"{ch['_id']}:{uid}", "sid": ch["_id"], "uid": uid, "at": now_utc()}
                )
            except DuplicateKeyError:
                pass
    return missing


# ======================================================================
#  VERIFICATION (captcha) + REFERRAL CREDIT
# ======================================================================
async def send_captcha(uid: int, cb: Optional[CallbackQuery] = None, note: str = "") -> None:
    a, b = random.randint(2, 9), random.randint(2, 9)
    answer = a + b
    opts = {answer}
    while len(opts) < 4:
        opts.add(max(2, answer + random.choice([-4, -3, -2, -1, 1, 2, 3, 4])))
    options = random.sample(sorted(opts), 4)
    await set_state(uid, "captcha", {"answer": answer}, ttl_min=10)
    text = (
        f"{note}🛡 <b>Human Verification</b>\n\n"
        "Fake accounts / bots rokne ke liye ek chhota sawaal:\n\n"
        f"<b>{a} + {b} = ?</b>"
    )
    markup = kb([btn(str(o), f"cap:{o}") for o in options])
    if cb:
        await safe_edit(cb, text, markup)
    else:
        await bot.send_message(uid, text, reply_markup=markup)


_ref_burst: dict = {}


async def credit_referral(uid: int) -> None:
    """Verified + channel-join hote hi referrer ko ticket + reward-card progress (sirf ek baar)."""
    doc = await users.find_one_and_update(
        {"_id": uid, "ref_by": {"$ne": None}, "ref_credited": {"$ne": True}},
        {"$set": {"ref_credited": True}},
    )
    if not doc:
        return
    ref = doc["ref_by"]
    ru = await users.find_one_and_update(
        {"_id": ref}, {"$inc": {"ref_count": 1, "ref_cycle_count": 1}}, return_document=ReturnDocument.AFTER
    )
    if ru:
        cnt, cycle = int(ru.get("ref_cycle_count", 1)), int(ru.get("ref_cycle", 1))
        card = await grant_card(ref, "refer", cycle, cnt)
        if card:
            spawn(notify_card_earned(ref, card))
        if cnt >= max(t for t, _ in REWARD_CFG["refer"]):  # cycle poora -> fresh start
            await users.update_one({"_id": ref}, {"$set": {"ref_cycle_count": 0, "ref_cycle": cycle + 1}})
        dq = _ref_burst.setdefault(ref, deque(maxlen=20))
        dq.append(time.monotonic())
        recent = [t for t in dq if time.monotonic() - t < 600]
        if len(recent) >= 8:  # fraud flag
            await users.update_one({"_id": ref}, {"$set": {"ref_flag": True}})
            spawn(alert_admin(
                f"refburst:{ref}",
                f"⚠️ <b>Referral burst</b>: {mention(ref, ru.get('name'))} (<code>{ref}</code>) ke 10 min me {len(recent)} referrals!\n"
                f"Check karein. Ban: <code>/ban {ref}</code>",
                cooldown=1800,
            ))
    await add_tickets(ref, REFERRAL_TICKETS)
    site_invalidate(ref)
    await deliver(
        ref,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>{esc(mask_name(doc.get('name')))}</b> aapke link se join hua aur verify ho gaya!\n"
            f"🎟 Aapko <b>+{REFERRAL_TICKETS} ticket</b> mila + referral card progress badha 🎯",
        ),
    )


async def maybe_credit_referral(uid: int) -> str:
    """Referral tabhi gina jata hai jab dost verify kare AUR task channel join kare."""
    u = await get_user_cached(uid)
    if not u or not u.get("ref_by") or u.get("ref_credited"):
        return "none"
    fresh = await users.find_one({"_id": uid}, {"ref_by": 1, "ref_credited": 1, "verified": 1})
    if not fresh or not fresh.get("ref_by") or fresh.get("ref_credited") or not fresh.get("verified"):
        invalidate_user(uid)
        return "none"
    if REFERRAL_REQUIRE_JOIN and await is_member(TASK_CHANNEL_ID, uid) is False:
        return "need_join"
    await credit_referral(uid)
    invalidate_user(uid)
    return "credited"


# ======================================================================
#  USER HANDLERS
# ======================================================================
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    uid = m.from_user.id
    is_new = await touch_user(m.from_user, force=True)
    await clear_state(uid)

    args = (command.args or "").strip()
    if is_new and args.startswith("ref_"):
        try:
            ref = int(args[4:])
        except ValueError:
            ref = 0
        if ref and ref != uid and await users.find_one({"_id": ref}, {"_id": 1}):
            await users.update_one({"_id": uid}, {"$set": {"ref_by": ref}})
            invalidate_user(uid)

    await m.answer(welcome_text(m.from_user.first_name), reply_markup=await user_menu(uid))
    if args in ("drop", "app"):
        await m.answer(
            "⚡ <b>Free Code Drops</b> aur baaki sab features ke liye App kholein 👇",
            reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)]),
        )
    if args == "code":
        await enter_code_flow(m.from_user)


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    await clear_state(m.from_user.id)
    await m.answer("❌ Cancel ho gaya. Menu ke liye /start dabayein.")


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery):
    await cb.answer()
    await safe_edit(cb, welcome_text(cb.from_user.first_name), await user_menu(cb.from_user.id))


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    await safe_edit(
        cb,
        help_text(),
        kb(
            [btn("🆘 Contact Support", url=SUPPORT_LINK)],
            [btn("⬅️ Back", "menu")],
        ),
    )


# ---------------------------------------------------------------- past winners (proof)
@router.callback_query(F.data == "winners")
async def cb_winners(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    docs = [d async for d in winners.find({}).sort("declared_at", -1).limit(5)]
    if not docs:
        text = (
            "🏆 <b>Pichhle Winners</b>\n\n"
            "Pehla winner jald hi yahan dikhega.\n"
            "Har winner ka proof hamesha hamare channel par post hota hai 📢"
        )
    else:
        lines = ["🏆 <b>Pichhle Winners (Proof)</b>\n"]
        for d in docs:
            allw = d.get("winners_all") or []
            names = ", ".join(esc(mask_name(x.get("name"))) for x in allw) if allw else esc(mask_name(d.get("name")))
            when = d["declared_at"].astimezone(IST).strftime("%d %b %Y") if d.get("declared_at") else ""
            line = f"🎁 <b>#{d.get('giveaway_no', '?')}</b> — {names} — {when}"
            if d.get("proof_url"):
                line += f' — <a href="{esc(d["proof_url"])}">Proof dekho</a>'
            lines.append(line)
        lines.append("\n🔒 Naam privacy ke liye chhupaye gaye hain. Poora proof channel par hai 👇")
        text = "\n".join(lines)
    await safe_edit(
        cb,
        text,
        kb(
            [btn("📢 Channel par saare proof", url=TASK_CHANNEL_LINK)],
            [btn("⬅️ Menu", "menu")],
        ),
    )


# ---------------------------------------------------------------- verify
@router.callback_query(F.data == "verify")
async def cb_verify(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    if await is_verified(cb.from_user.id):
        await safe_edit(cb, "✅ Aap pehle se <b>verified</b> hain!", back_kb())
        return
    await send_captcha(cb.from_user.id, cb)


@router.callback_query(F.data.startswith("cap:"))
async def cb_captcha(cb: CallbackQuery):
    uid = cb.from_user.id
    st = await get_state(uid)
    if not st or st["name"] != "captcha":
        await cb.answer("⌛ Expire ho gaya — dobara Verify dabayein", show_alert=True)
        return
    try:
        picked = int(cb.data.split(":", 1)[1])
    except ValueError:
        await cb.answer()
        return
    if picked != st["data"]["answer"]:
        await cb.answer("❌ Galat jawab! Naya sawaal 👇")
        await send_captcha(uid, cb)
        return
    await cb.answer("✅ Verified!")
    await clear_state(uid)
    await touch_user(cb.from_user)
    await users.update_one({"_id": uid}, {"$set": {"verified": True, "verified_at": now_utc()}})
    invalidate_user(uid)
    res = await maybe_credit_referral(uid)
    await safe_edit(
        cb,
        "✅ <b>Verification complete!</b>\n\nAb aap Enter Code, Daily Bonus aur Refer & Earn use kar sakte hain 🎉",
        await user_menu(uid),
    )
    if res == "need_join":
        await bot.send_message(
            uid,
            "📢 <b>Ek kaam baaki!</b> Hamara channel join karein — tabhi aapke dost ko reward milega.",
            reply_markup=kb([btn("📢 Join Channel", url=TASK_CHANNEL_LINK)], [btn("✅ Join kar liya", "refcheck")]),
        )


# ---------------------------------------------------------------- enter code
async def enter_code_flow(user: User) -> None:
    uid = user.id
    await touch_user(user)
    u = await get_user_cached(uid)
    if u and u.get("banned"):
        await bot.send_message(uid, f"🚫 Aapka account restricted hai. Support: {esc(SUPPORT_USERNAME)}")
        return
    await maybe_credit_referral(uid)  # pending referral (channel join ke baad) credit

    # 1) pehle hi code daal chuka hai?
    if await has_entered(uid):
        await bot.send_message(
            uid,
            "⚠️ <b>Aapne pehle hi code daal rakha hai!</b>\n\n"
            "Spam mat karein 🙏 — channel par wait karein, winner jald declare hoga.",
            reply_markup=channel_kb(),
        )
        return

    # 2) lock check
    remaining = await lock_remaining(uid)
    if remaining:
        await bot.send_message(
            uid,
            f"🔒 Aap abhi <b>lock</b> hain.\n⏳ <b>{fmt_td(remaining)}</b> baad dobara try karein.\n\n"
            "Pehle channel se sahi link ke through sahi code laayein.",
            reply_markup=channel_kb(),
        )
        return

    # 3) giveaway active hai?
    gw = await get_giveaway()
    if not gw:
        await bot.send_message(
            uid,
            "⏳ Abhi koi giveaway active nahi hai.\nNaye giveaway ke liye channel par bane rahein 📢",
            reply_markup=channel_kb(),
        )
        return
    if gw.get("closing"):
        await bot.send_message(
            uid,
            "🏆 Winner abhi declare ho raha hai — thodi der baad naye giveaway ka wait karein.",
            reply_markup=channel_kb(),
        )
        return

    if entries_closed(gw):
        await bot.send_message(
            uid,
            "⏰ <b>Entries band ho chuki hain</b>\n\n"
            "Winner jald hi declare hoga — result channel par post hoga 📢",
            reply_markup=channel_kb(),
        )
        return

    # 4) human verification
    if not await is_verified(uid):
        await send_captcha(uid, note="Pehle verification zaroori hai.\n\n")
        return

    # 5) required channels (sponsors + optional task channel)
    missing = await missing_channels(uid)
    if missing:
        rows = [[btn(f"➕ Join {c['title'][:30]}", url=c["link"])] for c in missing]
        rows.append([btn("✅ Maine Join Kar Liya", "enter_code")])
        names = "\n".join(f"• {esc(c['title'])}" for c in missing)
        await bot.send_message(
            uid,
            f"📢 Code dene se pehle ye channel(s) <b>join</b> karein:\n\n{names}\n\n"
            "Join karke <b>“Maine Join Kar Liya”</b> dabayein 👇",
            reply_markup=kb(*rows),
        )
        return

    await set_state(uid, "await_code", ttl_min=10)
    text = "🔑 <b>Apna code ab yahan bhejein</b> 👇\n\n<i>(Cancel karne ke liye /cancel)</i>"
    where = code_where_text(gw)
    if where:
        text += "\n\n" + where
    wt = when_line(gw)
    if wt:
        text += "\n\n" + wt
    rows = code_links_rows(gw)
    await bot.send_message(uid, text, reply_markup=kb(*rows) if rows else None)


@router.callback_query(F.data == "enter_code")
async def cb_enter_code(cb: CallbackQuery):
    await cb.answer()
    await enter_code_flow(cb.from_user)


async def handle_code(m: Message) -> None:
    uid = m.from_user.id
    if not m.text:
        await m.answer("⚠️ Code <b>text</b> me bhejein.")
        return
    await clear_state(uid)

    # dobara checks (state purani ho sakti hai)
    if await has_entered(uid):
        await m.answer(
            "⚠️ <b>Aapne pehle hi code daal rakha hai!</b>\nSpam mat karein, channel par wait karein.",
            reply_markup=channel_kb(),
        )
        return
    remaining = await lock_remaining(uid)
    if remaining:
        await m.answer(
            f"🔒 Aap lock hain. <b>{fmt_td(remaining)}</b> baad try karein.",
            reply_markup=channel_kb(),
        )
        return
    gw = await get_giveaway()
    if not gw or gw.get("closing"):
        await m.answer("⏳ Abhi giveaway active nahi hai. Channel par wait karein 📢", reply_markup=channel_kb())
        return

    if entries_closed(gw):
        await m.answer("⏰ <b>Entries band ho chuki hain.</b>\nWinner jald declare hoga 📢", reply_markup=channel_kb())
        return

    typed = m.text.strip()
    if typed.casefold() == str(gw["code"]).strip().casefold():
        await accept_entry(m, gw)
    else:
        await wrong_code(m, gw)


async def accept_entry(m: Message, gw: dict) -> None:
    u = m.from_user
    now = now_utc()
    try:
        await entries.insert_one(
            {"_id": u.id, "name": full_name(u), "username": u.username, "entered_at": now, "tickets": 1}
        )
    except DuplicateKeyError:
        await m.answer(
            "⚠️ <b>Aapne pehle hi code daal rakha hai!</b>\nSpam mat karein, channel par wait karein.",
            reply_markup=channel_kb(),
        )
        return

    # pehle se jama bonus tickets entry me lag jate hain
    prev = await users.find_one_and_update(
        {"_id": u.id}, {"$set": {"wrong_count": 0, "locked_until": None, "bonus_tickets": 0}}
    )
    bonus = int((prev or {}).get("bonus_tickets", 0))
    if bonus > 0:
        await entries.update_one({"_id": u.id}, {"$inc": {"tickets": bonus}})
    tickets = 1 + bonus
    total = await entries.count_documents({})

    # bot ka fixed message + admin ka custom message  -> user ke DM me
    text = entry_confirmed_text(gw.get("admin_message"), tickets, total, gw.get("winner_at"))
    if len(text) <= 4000:
        await m.answer(text, reply_markup=await user_menu(u.id))
    else:  # bahut lamba ho to 2 parts me
        await m.answer(
            entry_confirmed_text(None, tickets, total, gw.get("winner_at")), reply_markup=await user_menu(u.id)
        )
        await m.answer(gw["admin_message"])

    # entry details -> private log channel
    await safe_log(
        "✅ <b>New Entry Confirmed</b>\n\n"
        f"👤 Name: {esc(full_name(u))}\n"
        f"🔗 Username: {('@' + esc(u.username)) if u.username else 'N/A'}\n"
        f"🆔 ID: <code>{u.id}</code>\n"
        f"🎟 Tickets: <b>{tickets}</b>\n"
        f"🔢 Entry No: <b>#{total}</b>\n"
        f"🕒 Time: {fmt_ist(now)}"
    )


async def wrong_code(m: Message, gw: Optional[dict] = None) -> None:
    u = m.from_user
    doc = await users.find_one_and_update(
        {"_id": u.id},
        {"$inc": {"wrong_count": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    count = doc.get("wrong_count", 1)

    if count > MAX_WRONG_ATTEMPTS:
        until = now_utc() + timedelta(hours=LOCK_HOURS)
        await users.update_one({"_id": u.id}, {"$set": {"locked_until": until}})
        await m.answer(
            "🚫 <b>Aapne galat code daala hai!</b>\n\n"
            "Pehle <b>sahi link</b> se <b>sahi code</b> laaye.\n"
            f"🔒 Ab aap <b>{LOCK_HOURS} ghante</b> ke liye lock ho chuke hain.\n\n"
            f"Madad ke liye: {esc(SUPPORT_USERNAME)}",
            reply_markup=channel_kb(),
        )
        await safe_log(
            "🔒 <b>User Locked</b>\n\n"
            f"👤 {esc(full_name(u))}  (<code>{u.id}</code>)\n"
            f"❌ Galat attempts: {count}\n"
            f"⏳ Unlock: {fmt_ist(until)}"
        )
        return

    left = MAX_WRONG_ATTEMPTS - count
    warn = (
        f"Aap <b>{left}</b> galat attempt aur kar sakte hain."
        if left > 0
        else "⚠️ <b>Ye aakhri chance tha</b> — agla galat code aapko lock kar dega."
    )
    await m.answer(
        "❌ <b>Galat code!</b>\n\n"
        "📍 Code <b>video / post</b> me bataye gaye jagah se hi lijiye, phir dobara try karein.\n"
        f"{warn}",
        reply_markup=retry_kb(gw),
    )


# ---------------------------------------------------------------- daily bonus
async def daily_core(uid: int) -> dict:
    """Daily bonus claim — bot aur Mini App dono yahi use karte hain."""
    u0 = await get_user_cached(uid)
    if not u0 or not u0.get("verified"):
        return {"status": "unverified"}
    if u0.get("banned"):
        return {"status": "banned"}
    today = today_ist()
    prev = await users.find_one_and_update(
        {"_id": uid, "last_claim": {"$ne": today}}, {"$set": {"last_claim": today}}
    )
    if prev is None:
        u = await users.find_one({"_id": uid}) or {}
        return {"status": "already", "streak": u.get("streak", 0), "best": u.get("best_streak", 0)}

    last = prev.get("last_claim")
    try:
        gap = (date.fromisoformat(today) - date.fromisoformat(last)).days if last else None
    except ValueError:
        gap = None
    streak = prev.get("streak", 0) + 1 if gap is not None and 1 <= gap <= 1 + STREAK_GRACE_DAYS else 1
    best = max(prev.get("best_streak", 0), streak)
    cycle = int(prev.get("streak_cycle", 1))
    upd = {"streak": streak, "best_streak": best}
    reset = streak >= max(t for t, _ in REWARD_CFG["streak"])
    if reset:  # top milestone poora -> fresh cycle
        upd.update(streak=0, streak_cycle=cycle + 1)
    await users.update_one({"_id": uid}, {"$set": upd})
    card = await grant_card(uid, "streak", cycle, streak)
    if card:
        spawn(notify_card_earned(uid, card))
    reward = STREAK_REWARDS.get(streak, 0)
    if reward:
        await add_tickets(uid, reward)
    nxt = next((d for d in sorted(STREAK_REWARDS) if d > streak), None)
    site_invalidate(uid)
    return {
        "status": "ok", "streak": streak, "best": best, "reward": reward, "card": card, "cycle_reset": reset,
        "next_day": nxt, "next_reward": STREAK_REWARDS.get(nxt) if nxt else None,
    }


@router.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    r = await daily_core(uid)
    if r["status"] == "unverified":
        await send_captcha(uid, note="Daily Bonus ke liye pehle verification zaroori hai.\n\n")
        return
    if r["status"] == "banned":
        await bot.send_message(uid, f"🚫 Aapka account restricted hai. Support: {esc(SUPPORT_USERNAME)}")
        return
    if r["status"] == "already":
        await bot.send_message(
            uid,
            "✅ <b>Aaj ka bonus claim ho chuka hai!</b>\n\n"
            f"🔥 Streak: <b>{r['streak']} din</b>\n"
            "⏳ Agla bonus kal (12 AM IST ke baad) milega — streak mat todna!",
            reply_markup=back_kb(),
        )
        return
    streak, best, reward, nxt = r["streak"], r["best"], r["reward"], r["next_day"]
    reward_line = (
        f"🎉 Milestone! <b>+{reward} ticket</b> mil gaya 🎟"
        if reward
        else "Aaj ke liye ticket reward nahi — milestone ka wait karein 😊"
    )
    next_line = (
        f"🎯 Agla reward: <b>{nxt} din</b> par (+{r['next_reward']} ticket) — {nxt - streak} din baaki"
        if nxt
        else "🏆 Aapne sabhi milestones paar kar liye!"
    )
    card_line = f"\n🎁 <b>Reward Card unlock: ₹{r['card']['amount']}!</b> App → Rewards me Redeem karein." if r.get("card") else ""
    await bot.send_message(
        uid,
        "🎁 <b>Daily Bonus Claimed!</b>\n\n"
        f"🔥 Streak: <b>{streak} din</b> (best: {best})\n"
        f"{reward_line}\n{next_line}{card_line}\n\n"
        "Kal wapas aana — streak toot jayegi agar ek din miss hua!",
        reply_markup=back_kb(),
    )


# ---------------------------------------------------------------- refer
@router.callback_query(F.data == "refer")
async def cb_refer(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    u = await users.find_one({"_id": uid}) or {}
    entry = await entries.find_one({"_id": uid})
    link = ref_link(uid)
    tickets_line = (
        f"🎟 Current giveaway tickets: <b>{entry.get('tickets', 1)}</b>"
        if entry
        else f"🎟 Jama bonus tickets (agli entry par lagenge): <b>{u.get('bonus_tickets', 0)}</b>"
    )
    share_text = "🎁 Free redeem codes jeeto! Is bot ko join karo:"
    await safe_edit(
        cb,
        "👥 <b>Refer & Earn</b>\n\n"
        f"Har dost jo aapke link se aakar <b>verify</b> karega = <b>+{REFERRAL_TICKETS} ticket</b> 🎟\n"
        "Zyada tickets = random winner pick me zyada chance!\n\n"
        f"🔗 <b>Aapka link:</b>\n<code>{link}</code>\n\n"
        f"👥 Total referrals: <b>{u.get('ref_count', 0)}</b>\n{tickets_line}",
        kb(
            [btn("📤 Share Link", url=f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}")],
            [btn("⬅️ Back", "menu")],
        ),
    )


# ---------------------------------------------------------------- leaderboard
@router.callback_query(F.data == "top")
async def cb_top(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    top = [d async for d in users.find({"ref_count": {"$gt": 0}}).sort("ref_count", -1).limit(10)]
    medals = ["🥇", "🥈", "🥉"]
    if top:
        lines = [
            f"{medals[i] if i < 3 else str(i + 1) + '.'} {esc(mask_name(d.get('name')))} — "
            f"<b>{d.get('ref_count', 0)}</b> referrals"
            for i, d in enumerate(top)
        ]
        body = "\n".join(lines)
    else:
        body = "Abhi koi referral nahi — pehle aap bano champion! 🚀"
    me = await users.find_one({"_id": uid}) or {}
    mine = int(me.get("ref_count", 0))
    if mine > 0:
        rank = await users.count_documents({"ref_count": {"$gt": mine}}) + 1
        you = f"\n\n📍 Aapka rank: <b>#{rank}</b> ({mine} referrals)"
    else:
        you = "\n\n📍 Aapke abhi 0 referrals hain — <b>Refer & Earn</b> se shuru karein!"
    await safe_edit(
        cb,
        f"🏅 <b>Top Referrers</b>\n\n{body}{you}",
        kb([btn("👥 Refer & Earn", "refer")], [btn("⬅️ Back", "menu")]),
    )


# ======================================================================
#  ADMIN: COMMAND + CALLBACKS
# ======================================================================
@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id):
        return
    await clear_state(ADMIN_ID)
    await m.answer(ADMIN_HOME_TEXT, reply_markup=admin_kb())


@router.message(Command("ban"))
async def cmd_ban(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    try:
        uid = int((command.args or "").split()[0])
    except (ValueError, IndexError):
        await m.answer("Use: <code>/ban 123456789</code>")
        return
    res = await users.update_one({"_id": uid}, {"$set": {"banned": True}})
    invalidate_user(uid)
    await m.answer(f"🚫 <code>{uid}</code> ban ho gaya." if res.matched_count else "⚠️ Ye user database me nahi mila.")


@router.message(Command("unban"))
async def cmd_unban(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    try:
        uid = int((command.args or "").split()[0])
    except (ValueError, IndexError):
        await m.answer("Use: <code>/unban 123456789</code>")
        return
    res = await users.update_one({"_id": uid}, {"$set": {"banned": False}})
    invalidate_user(uid)
    await m.answer(f"✅ <code>{uid}</code> unban ho gaya." if res.matched_count else "⚠️ Ye user database me nahi mila.")


async def render_sponsors(cb: CallbackQuery) -> None:
    rows = [s async for s in sponsors.find({})]
    lines, buttons = [], []
    for s in rows:
        joins = await sponsor_joins.count_documents({"sid": s["_id"]})
        lines.append(f"• <b>{esc(s['title'])}</b> — ✅ {joins} verified members")
        buttons.append([btn(f"🗑 Remove: {s['title'][:22]}", f"adm:sp_del:{s['_id']}")])
    text = (
        "🤝 <b>Sponsors</b>\n\n"
        + ("\n".join(lines) if lines else "Abhi koi sponsor nahi hai.")
        + f"\n\nUsers ko code dene se pehle ye channels join karne honge (max {MAX_SPONSORS}).\n"
        "Bot ko sponsor channel me <b>Admin</b> banana zaroori hai (membership check ke liye)."
    )
    if len(rows) < MAX_SPONSORS:
        buttons.append([btn("➕ Add Sponsor", "adm:sp_add")])
    buttons.append([btn("⬅️ Admin Panel", "adm:home")])
    await safe_edit(cb, text, kb(*buttons))


def bc_confirm_card(n_users: int, data: dict) -> tuple:
    has_btn = bool(data.get("btn_text"))
    text = (
        f"📢 Ye message <b>{n_users}</b> users ko bheja jayega.\n"
        + (f"🔘 Button: <b>{esc(data['btn_text'])}</b> → {esc(data['btn_url'])}\n" if has_btn else "🔘 Button: nahi\n")
        + "\nConfirm karein?"
    )
    markup = kb([btn("✅ Send Broadcast", "adm:bc_go")], [btn("❌ Cancel", "adm:home")])
    return text, markup


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Sirf admin ke liye", show_alert=True)
        return
    await cb.answer()
    action = cb.data.split(":", 1)[1]

    # ---------------------------------------------------------- home
    if action == "home":
        await clear_state(ADMIN_ID)
        await safe_edit(cb, ADMIN_HOME_TEXT, admin_kb())

    # ---------------------------------------------------------- stats
    elif action == "stats":
        total = await users.count_documents({})
        junk = await users.count_documents({"junk": True})
        verified = await users.count_documents({"verified": True})
        locked = await users.count_documents({"locked_until": {"$gt": now_utc()}})
        n_entries = await entries.count_documents({})
        n_winners = await winners.count_documents({})
        n_refs = await users.count_documents({"ref_credited": True})
        n_sp = await sponsors.count_documents({})
        n_sp_joins = await sponsor_joins.count_documents({})
        n_rw = await rewards.count_documents({"status": "requested"})
        n_ban = await users.count_documents({"banned": True})
        gw = await get_giveaway()
        if gw:
            status = "🔄 Winner process chal raha hai" if gw.get("closing") else "🟢 Active"
            gw_line = f"{status}\n🔑 Code: <code>{esc(gw['code'])}</code>"
            if gw.get("winner_at"):
                gw_line += f"\n⏰ Winner time: {esc(fmt_when(gw['winner_at']))}"
        else:
            gw_line = "🔴 Koi active giveaway nahi (Add Giveaway Code karein)"
        await safe_edit(
            cb,
            "📊 <b>Bot Stats</b>\n\n"
            f"👥 Total Users: <b>{total}</b>\n"
            f"✅ Active Users: <b>{total - junk}</b>\n"
            f"🛡 Verified: <b>{verified}</b>\n"
            f"🗑 Junk (blocked): <b>{junk}</b>\n"
            f"🔒 Locked Users: <b>{locked}</b>\n"
            f"🎟 Current Entries: <b>{n_entries}</b>\n"
            f"👥 Referrals (credited): <b>{n_refs}</b>\n"
            f"🤝 Sponsors: <b>{n_sp}</b> (verified members: {n_sp_joins})\n"
            f"🏆 Winners Declared: <b>{n_winners}</b>\n"
            f"🎯 Reward requests pending: <b>{n_rw}</b>\n"
            f"🚫 Banned: <b>{n_ban}</b>\n"
            f"{'⚠️ Degraded mode ON' if STATUS['degraded'] else '🟢 Bot healthy'}\n\n"
            f"🎁 <b>Giveaway:</b> {gw_line}",
            admin_back_kb(),
        )

    # ---------------------------------------------------------- add code
    elif action == "add":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi winner/broadcast process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        gw = await get_giveaway()
        if gw and not gw.get("closing"):
            n = await entries.count_documents({})
            await safe_edit(
                cb,
                "⚠️ <b>Ek giveaway pehle se chal raha hai</b>\n\n"
                f"🔑 Code: <code>{esc(gw['code'])}</code>\n"
                f"🎟 Entries: <b>{n}</b>\n\n"
                "✏️ <b>Edit</b> — code / link / time badalna ho to (entries safe rahengi)\n"
                f"🆕 <b>Naya</b> — purana giveaway aur {n} entries delete ho jayengi",
                kb(
                    [btn("✏️ Edit Giveaway", "adm:edit")],
                    [btn("🆕 Naya Giveaway Shuru Karo", "adm:add_new")],
                    [btn("⬅️ Admin Panel", "adm:home")],
                ),
            )
            return
        await start_add_flow(cb, reset=False)

    elif action == "add_new":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi winner/broadcast process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        await start_add_flow(cb, reset=True)

    # ---------------------------------------------------------- winner
    elif action == "winner":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi ek process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_win_id", {"list": []})
        n = await entries.count_documents({})
        await safe_edit(
            cb,
            win_pick_prompt(n, 0),
            kb(
                [btn("🎲 Random Pick", "adm:win_rand")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

    elif action == "win_rand":
        st = await get_state(ADMIN_ID)
        lst = list(st["data"].get("list", [])) if st and st["name"] == "admin_win_id" else []
        pick = await pick_random_winner({x["id"] for x in lst})
        if not pick:
            await safe_edit(cb, "⚠️ Koi entry nahi mili jisme se random pick ho sake.", admin_back_kb())
            return
        u = await users.find_one({"_id": pick["_id"]}) or {}
        await set_state(ADMIN_ID, "admin_win_code", {"winner_id": pick["_id"], "random": True, "list": lst})
        await safe_edit(
            cb,
            "🎲 <b>Random Pick</b>\n\n"
            f"👤 {esc(u.get('name'))}  (<code>{pick['_id']}</code>)\n"
            f"🎟 Tickets: <b>{pick.get('tickets', 1)}</b>\n\n"
            "Step 2/2 — Ab <b>Redeem Code</b> bhejein jo winner ko DM me jayega:",
            admin_cancel_kb(),
        )

    elif action == "win_more":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_win_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Select Winner try karein.", admin_back_kb())
            return
        lst = list(st["data"]["list"])
        if len(lst) >= MAX_WINNERS:
            await safe_edit(cb, f"⚠️ Ek giveaway me max {MAX_WINNERS} winners ho sakte hain.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_win_id", {"list": lst})
        n = await entries.count_documents({})
        await safe_edit(
            cb,
            win_pick_prompt(n, len(lst)),
            kb(
                [btn("🎲 Random Pick", "adm:win_rand")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

    elif action == "win_go":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_win_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Select Winner try karein.", admin_back_kb())
            return
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Ek process pehle se chal raha hai.", admin_back_kb())
            return
        data = st["data"]
        await clear_state(ADMIN_ID)
        await safe_edit(cb, "⏳ Winner process shuru ho gaya… report yahan aayegi.", admin_back_kb())
        spawn(declare_winner(list(data["list"])))

    # ---------------------------------------------------------- broadcast
    elif action == "bc":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi ek process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_bc_msg")
        await safe_edit(
            cb,
            "📢 <b>Broadcast</b>\n\nJo message sabko bhejna hai wo <b>abhi bhejein</b> "
            "(text, photo, video — kuch bhi):",
            admin_cancel_kb(),
        )

    elif action == "bc_skip":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_bc_btn":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Broadcast try karein.", admin_back_kb())
            return
        data = dict(st["data"])
        n = await users.count_documents({"junk": {"$ne": True}})
        await set_state(ADMIN_ID, "admin_bc_confirm", data)
        text, markup = bc_confirm_card(n, data)
        await safe_edit(cb, text, markup)

    elif action == "bc_go":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_bc_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Broadcast try karein.", admin_back_kb())
            return
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Ek process pehle se chal raha hai.", admin_back_kb())
            return
        data = st["data"]
        await clear_state(ADMIN_ID)
        await safe_edit(cb, "⏳ Broadcast shuru ho gaya… report yahan aayegi.", admin_back_kb())
        spawn(
            run_admin_broadcast(
                int(data["chat_id"]), int(data["message_id"]), data.get("btn_text"), data.get("btn_url")
            )
        )

    # ---------------------------------------------------------- junk
    elif action == "junk":
        n = await users.count_documents({"junk": True})
        if n == 0:
            await safe_edit(cb, "🧹 <b>Junk List khaali hai.</b>\n\nKoi blocked user nahi mila ✅", admin_back_kb())
            return
        await safe_edit(
            cb,
            f"🧹 <b>Clear Junk</b>\n\nJunk List me <b>{n}</b> users hain "
            "(jinhone bot block kiya / account delete kiya).\n\n"
            "Inhe database se <b>permanently remove</b> karein?",
            kb(
                [btn(f"🗑 Remove {n} users", "adm:junk_go")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

    elif action == "junk_go":
        ids = [d["_id"] async for d in users.find({"junk": True}, {"_id": 1})]
        if ids:
            await users.delete_many({"_id": {"$in": ids}})
            await entries.delete_many({"_id": {"$in": ids}})
            await states.delete_many({"_id": {"$in": ids}})
            for i in ids:
                invalidate_user(i)
        await safe_edit(cb, f"✅ <b>{len(ids)}</b> junk users permanently remove ho gaye.", admin_back_kb())

    # ---------------------------------------------------------- giveaway add: skips / publish
    elif action in ("add_skiplinks", "add_skipnote", "add_skiptime", "add_skipmsg"):
        need = {
            "add_skiplinks": "admin_add_links",
            "add_skipnote": "admin_add_note",
            "add_skiptime": "admin_add_time",
            "add_skipmsg": "admin_add_msg",
        }[action]
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != need:
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Add Giveaway Code karein.", admin_back_kb())
            return
        data = dict(st["data"])
        if action == "add_skiplinks":
            await set_state(ADMIN_ID, "admin_add_note", {**data, "links": []})
            await safe_edit(cb, add_note_prompt(False), add_skip_kb("add_skipnote"))
        elif action == "add_skipnote":
            await set_state(ADMIN_ID, "admin_add_time", {**data, "note": None})
            await safe_edit(cb, ADD_TIME_PROMPT, add_time_kb())
        elif action == "add_skiptime":
            await set_state(ADMIN_ID, "admin_add_msg", {**data, "winner_at": None})
            await safe_edit(cb, ADD_MSG_PROMPT, add_skip_kb("add_skipmsg"))
        else:
            nd = {**data, "admin_message": None}
            await set_state(ADMIN_ID, "admin_add_confirm", nd)
            text, markup = add_confirm_card(nd)
            await safe_edit(cb, text, markup)

    elif action == "add_tgl":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_add_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Add Giveaway Code karein.", admin_back_kb())
            return
        nd = dict(st["data"])
        nd["close_entries"] = not nd.get("close_entries")
        await set_state(ADMIN_ID, "admin_add_confirm", nd)
        text, markup = add_confirm_card(nd)
        await safe_edit(cb, text, markup)

    elif action == "add_publish":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_add_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara Add Giveaway Code karein.", admin_back_kb())
            return
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi ek process chal raha hai, thodi der baad try karein.", admin_back_kb())
            return
        data = dict(st["data"])
        await clear_state(ADMIN_ID)
        text = await publish_giveaway(data)
        await safe_edit(cb, text, admin_back_kb())
        if data.get("admin_message"):
            await bot.send_message(ADMIN_ID, "📩 <b>Admin message preview:</b>\n\n" + data["admin_message"])

    # ---------------------------------------------------------- giveaway quick winner-time buttons
    elif action.startswith("wt:"):
        st = await get_state(ADMIN_ID)
        if not st or st["name"] not in ("admin_add_time", "admin_edit_time"):
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara try karein.", admin_back_kb())
            return
        try:
            days = int(action.split(":", 1)[1])
        except ValueError:
            return
        wa = winner_at_days(days)
        if wa <= now_utc():
            await bot.send_message(ADMIN_ID, "⏰ Ye time nikal chuka hai, koi aur option chunein.")
            return
        if st["name"] == "admin_add_time":
            await set_state(ADMIN_ID, "admin_add_msg", {**st["data"], "winner_at": wa.isoformat()})
            await safe_edit(
                cb, f"✅ Winner time: <b>{esc(fmt_when(wa))}</b>\n\n" + ADD_MSG_PROMPT, add_skip_kb("add_skipmsg")
            )
        else:
            gw = await get_giveaway()
            if not gw or gw.get("closing"):
                await safe_edit(cb, "⚠️ Abhi koi active giveaway nahi hai.", admin_back_kb())
                return
            await clear_state(ADMIN_ID)
            upd = {"winner_at": wa, **winner_time_flags(wa)}
            await config.update_one({"_id": "giveaway"}, {"$set": upd})
            live_state["v"] += 1
            gw.update(upd)
            note = "✅ <b>Winner time update ho gaya!</b>\n📣 Channel post: " + await refresh_channel_post(gw)
            text, markup = await edit_card(gw, note)
            await safe_edit(cb, text, markup)

    # ---------------------------------------------------------- giveaway edit / repost
    elif action == "edit":
        await clear_state(ADMIN_ID)
        gw = await get_giveaway()
        if not gw:
            await safe_edit(cb, "🔴 Koi active giveaway nahi hai.\n\nPehle <b>Add Giveaway Code</b> karein.", admin_back_kb())
            return
        if gw.get("closing"):
            await safe_edit(cb, "🔄 Winner process chal raha hai — abhi edit nahi ho sakta.", admin_back_kb())
            return
        text, markup = await edit_card(gw)
        await safe_edit(cb, text, markup)

    elif action.startswith("ed:"):
        field = action.split(":", 1)[1]
        gw = await get_giveaway()
        if field not in EDIT_PROMPTS or not gw or gw.get("closing"):
            await safe_edit(cb, "⚠️ Abhi koi active giveaway nahi hai.", admin_back_kb())
            return
        await set_state(ADMIN_ID, f"admin_edit_{field}")
        rows = time_quick_rows() if field == "time" else []
        if field != "code":
            rows.append([btn("🗑 Hata do", f"adm:ed_clear:{field}")])
        rows.append([btn("↩️ Wapas", "adm:edit")])
        await safe_edit(cb, EDIT_PROMPTS[field], kb(*rows))

    elif action.startswith("ed_clear:"):
        field = action.split(":", 1)[1]
        gw = await get_giveaway()
        if field not in ("links", "note", "time", "msg") or not gw or gw.get("closing"):
            await safe_edit(cb, "⚠️ Abhi koi active giveaway nahi hai.", admin_back_kb())
            return
        upd = {
            "links": {"links": [], "video_url": None},
            "note": {"note": None},
            "time": {"winner_at": None, "close_entries": False},
            "msg": {"admin_message": None},
        }[field]
        await clear_state(ADMIN_ID)
        await config.update_one({"_id": "giveaway"}, {"$set": upd})
        live_state["v"] += 1
        gw.update(upd)
        note = "🗑 <b>Hata diya gaya.</b>"
        if field in ("links", "note", "time"):
            note += "\n📣 Channel post: " + await refresh_channel_post(gw)
        text, markup = await edit_card(gw, note)
        await safe_edit(cb, text, markup)

    elif action == "ed_tgl":
        gw = await get_giveaway()
        if not gw or gw.get("closing"):
            await safe_edit(cb, "⚠️ Abhi koi active giveaway nahi hai.", admin_back_kb())
            return
        if not gw.get("winner_at"):
            await bot.send_message(ADMIN_ID, "⚠️ Pehle ⏰ Winner Time set karein, phir ye option chalega.")
            return
        upd = {"close_entries": not gw.get("close_entries")}
        await config.update_one({"_id": "giveaway"}, {"$set": upd})
        gw.update(upd)
        text, markup = await edit_card(gw)
        await safe_edit(cb, text, markup)

    elif action == "repost":
        gw = await get_giveaway()
        if not gw or gw.get("closing"):
            await safe_edit(
                cb,
                "⚠️ Abhi koi active giveaway nahi hai.\n\n"
                "Jo giveaway khatam ho chuka hai uski post dobara nahi bheji jati.",
                admin_back_kb(),
            )
            return
        mid = await send_giveaway_post(gw)
        if not mid:
            await safe_edit(cb, "⚠️ Post nahi gayi (bot ko channel me admin banayein).", admin_back_kb())
            return
        old = gw.get("post_msg_id")
        deleted = await drop_channel_post(old) if old else False
        await config.update_one({"_id": "giveaway"}, {"$set": {"post_msg_id": mid}})
        await safe_edit(
            cb,
            "✅ <b>Post dubara bhej di gayi!</b>" + ("\n🗑 Purani post delete ho gayi." if deleted else ""),
            kb([btn("✏️ Edit Giveaway", "adm:edit")], [btn("⬅️ Admin Panel", "adm:home")]),
        )

    # ---------------------------------------------------------- rewards (admin)
    elif action == "rw":
        pend = [r async for r in rewards.find({"status": "requested"}).sort("deadline", 1).limit(8)]
        total = await rewards.count_documents({"status": "requested"})
        if not pend:
            await safe_edit(cb, "📥 <b>Reward Requests</b>\n\nAbhi koi pending request nahi ✅", admin_back_kb())
            return
        lines, rows = [], []
        for r in pend:
            left = r["deadline"] - now_utc()
            t = fmt_td(left) if left.total_seconds() > 0 else "⚠️ late"
            lines.append(f"• <code>{r['uid']}</code> — ₹{r['amount']} ({TRACKS[r['track']][0]} {r['target']}) — {t}")
            rows.append([btn(f"₹{r['amount']} · {r['uid']}", f"rw:view:{r['_id']}")])
        rows.append([btn("⬅️ Admin Panel", "adm:home")])
        await safe_edit(
            cb,
            f"📥 <b>Reward Requests</b> — pending: <b>{total}</b>\n\n" + "\n".join(lines)
            + "\n\nCard kholne ke liye neeche tap karein 👇",
            kb(*rows),
        )

    elif action == "rwcfg":
        await safe_edit(
            cb,
            "🎯 <b>Reward Cards</b>\n\n"
            f"🔥 <b>Streak:</b> {cards_text('streak')}\n"
            f"👥 <b>Refer:</b> {cards_text('refer')}\n\n"
            "Cycle poora (sabse bada target) hone par count 0 se dobara shuru hota hai.\n"
            "Badlaav sirf aage ke cards par lagta hai.",
            kb(
                [btn("✏️ Streak edit", "adm:rwcfg_edit:streak"), btn("✏️ Refer edit", "adm:rwcfg_edit:refer")],
                [btn("⬅️ Admin Panel", "adm:home")],
            ),
        )

    elif action.startswith("rwcfg_edit:"):
        track = action.split(":", 1)[1]
        if track not in TRACKS:
            return
        await set_state(ADMIN_ID, f"admin_rwcfg_{track}")
        await safe_edit(
            cb,
            f"✏️ <b>{TRACKS[track][0]} cards edit</b>\n\nFormat: <code>target:₹amount, target:₹amount</code>\n"
            "Jaise: <code>20:10, 50:20, 100:40, 200:75</code>\n(targets chhote se bade, max 8)\n\n"
            f"Abhi: {cards_text(track)}",
            admin_cancel_kb(),
        )

    # ---------------------------------------------------------- notice (Mini App banner)
    elif action == "notice":
        cur = NOTICE["text"]
        await safe_edit(
            cb,
            "📣 <b>Mini App Notice</b>\n\n"
            + (f"Abhi chal raha hai:\n<i>{esc(cur)}</i>" if cur else "Abhi koi notice nahi hai.")
            + "\n\nYe notice Mini App ke upar sabko dikhta hai (maintenance / update / offer ke liye).",
            kb(
                [btn("✏️ Set Notice", "adm:notice_set")],
                [btn("🗑 Clear Notice", "adm:notice_clear")],
                [btn("⬅️ Admin Panel", "adm:home")],
            ),
        )

    elif action == "notice_set":
        await set_state(ADMIN_ID, "admin_notice")
        await safe_edit(cb, "✏️ Notice ka text bhejein (max 200 characters):", admin_cancel_kb())

    elif action == "notice_clear":
        NOTICE["text"] = ""
        await config.delete_one({"_id": "notice"})
        live_state["v"] += 1
        await safe_edit(cb, "✅ Notice hata diya gaya.", admin_back_kb())

    # ---------------------------------------------------------- free code drop
    elif action == "drop":
        await render_drop_menu(cb)

    elif action == "drop_new":
        if await active_drop():
            await safe_edit(cb, "⚠️ Ek drop pehle se active hai. Pehle use cancel/end karein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_drop_codes", ttl_min=30)
        await safe_edit(
            cb,
            "⚡ <b>New Free Code Drop</b>\n\n"
            "Step 1/4 — <b>Redeem codes</b> bhejein, <b>har line me ek code</b>.\n"
            f"Jitni lines, utne log jeet payenge (max {DROP_MAX_CODES}).",
            admin_cancel_kb(),
        )

    elif action.startswith("drop_t:"):
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_drop_time":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara New Drop try karein.", admin_back_kb())
            return
        try:
            minutes = int(action.split(":", 1)[1])
        except ValueError:
            return
        text, markup = await drop_mode_prompt(st["data"]["codes"], now_utc() + timedelta(minutes=minutes))
        await safe_edit(cb, text, markup)

    elif action.startswith("drop_m:"):
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_drop_mode":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara New Drop try karein.", admin_back_kb())
            return
        mode = "lucky" if action.endswith("lucky") else "fast"
        text, markup = await drop_label_prompt(st["data"], mode)
        await safe_edit(cb, text, markup)

    elif action == "drop_skip":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_drop_label":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara New Drop try karein.", admin_back_kb())
            return
        text, markup = await drop_confirm_card(st["data"], DEFAULT_DROP_LABEL)
        await safe_edit(cb, text, markup)

    elif action == "drop_go":
        st = await get_state(ADMIN_ID)
        if not st or st["name"] != "admin_drop_confirm":
            await safe_edit(cb, "⌛ Session expire ho gaya. Dobara New Drop try karein.", admin_back_kb())
            return
        data = st["data"]
        go_live_at = datetime.fromisoformat(data["go_live_at"])
        if (go_live_at - now_utc()).total_seconds() < 15:
            await safe_edit(cb, "⚠️ Live time nikal chuka hai. Dobara New Drop karke naya time dein.", admin_back_kb())
            return
        if await active_drop():
            await safe_edit(cb, "⚠️ Ek drop pehle se active hai.", admin_back_kb())
            return
        await clear_state(ADMIN_ID)
        no = await create_drop(list(data["codes"]), go_live_at, data["label"], data.get("mode", "fast"))
        if no is None:
            await safe_edit(
                cb,
                "❌ Teaser channel par post nahi ho paya. Bot ko task channel me <b>Admin</b> banayein "
                "(post + pin permission) aur dobara try karein.",
                admin_back_kb(),
            )
            return
        await safe_edit(
            cb,
            f"✅ <b>Drop #{no} scheduled!</b>\n\n"
            f"🕘 Live: <b>{fmt_ist(go_live_at)}</b>\n📦 Codes: <b>{len(data['codes'])}</b>\n\n"
            "Teaser channel par post + pin ho gaya. Time par LIVE post apne aap aayegi. "
            "Report yahin milegi.",
            kb([btn("⚡ Drop Status", "adm:drop")], [btn("⬅️ Admin Panel", "adm:home")]),
        )

    elif action.startswith("drop_cancel:"):
        try:
            no = int(action.split(":", 1)[1])
        except ValueError:
            return
        msg = await cancel_drop(no)
        await safe_edit(cb, msg, admin_back_kb())

    # ---------------------------------------------------------- sponsors
    elif action == "sponsors":
        await render_sponsors(cb)

    elif action == "sp_add":
        if await sponsors.count_documents({}) >= MAX_SPONSORS:
            await safe_edit(cb, f"⚠️ Max {MAX_SPONSORS} sponsors hi allowed hain. Pehle koi hatayein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_sp_id")
        await safe_edit(
            cb,
            "➕ <b>Add Sponsor</b>\n\n"
            "Step 1/2 — Sponsor <b>channel ki ID</b> bhejein (jaise <code>-1001234567890</code>).\n"
            "⚠️ Pehle bot ko us channel me <b>Admin</b> banayein.",
            admin_cancel_kb(),
        )

    elif action.startswith("sp_del:"):
        try:
            sid = int(action.split(":", 1)[1])
        except ValueError:
            return
        await sponsors.delete_one({"_id": sid})
        await sponsor_joins.delete_many({"sid": sid})
        await render_sponsors(cb)


# ======================================================================
#  ADMIN: STEP-BY-STEP INPUTS (state machine)
# ======================================================================
# ---------------------------------------------------------------- giveaway: constants
MAX_LINKS = 4
MAX_NOTE = 300
MAX_WINNERS = 5
URL_RE = re.compile(r"https?://\S+", re.I)
URL_OK_RE = re.compile(r"^https?://[^\s/]+\.[^\s/]+", re.I)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

ADD_LINKS_PROMPT = (
    "Step 2/5 — 📍 <b>Code kahan milega?</b>\n"
    "Link bhejein, <b>har line me: platform - link</b>\n\n"
    "<code>Instagram - https://instagram.com/reel/xxxx\n"
    "YouTube - https://youtu.be/xxxx</code>\n\n"
    "• 1 se 4 link tak\n"
    "• Dono platform par video hai to dono line bhejein — user kisi par bhi ja sakta hai\n"
    "• Link nahi hai (code kisi aur jagah hai) to <b>Skip</b> dabayein"
)
LINKS_ERR = (
    "⚠️ Link samajh nahi aaya. Is format me bhejein (har line me ek):\n\n"
    "<code>Instagram - https://instagram.com/reel/xxxx</code>\n"
    "<code>YouTube - https://youtu.be/xxxx</code>"
)
ADD_TIME_PROMPT = (
    "Step 4/5 — ⏰ <b>Winner kab chuna jayega?</b>\n"
    "Date aur time bhejein (IST):\n\n"
    "<code>12 nov 9pm</code>\n"
    "<code>kal 8:30pm</code>\n"
    "<code>15/11 21:00</code>\n\n"
    "ya neeche ka button dabayein. Nahi dena to <b>Skip</b>."
)
TIME_ERR = (
    "⚠️ Time samajh nahi aaya ya nikal chuka hai. Aise bhejein:\n\n"
    "<code>12 nov 9pm</code>  |  <code>kal 8:30pm</code>  |  <code>15/11 21:00</code>"
)
ADD_MSG_PROMPT = (
    "Step 5/5 — 📩 <b>Admin message</b> bhejein jo sahi code daalne par user ko DM me jayega "
    "(bold/italic/link formatting chalegi).\nNahi dena to <b>Skip</b> dabayein."
)
EDIT_PROMPTS = {
    "code": "🔑 <b>Naya giveaway code</b> bhejein.\n\n<i>Jo log pehle entry kar chuke hain unki entry safe rahegi.</i>",
    "links": (
        "📍 <b>Naye links</b> bhejein, har line me <code>platform - link</code>:\n\n"
        "<code>Instagram - https://...\nYouTube - https://...</code>\n\n"
        "<i>Purane saare links badal jayenge.</i>"
    ),
    "note": "📝 <b>Naya note</b> bhejein (code kahan / kaise milega), max 300 characters. Bold/italic chalega.",
    "time": (
        "⏰ <b>Winner ka naya date/time</b> bhejein (IST):\n\n"
        "<code>12 nov 9pm</code>  |  <code>kal 8:30pm</code>  |  <code>15/11 21:00</code>\n\n"
        "ya neeche button dabayein 👇"
    ),
    "msg": "📩 <b>Naya admin message</b> bhejein jo sahi code daalne par user ko DM me jayega.",
}


def add_note_prompt(has_links: bool) -> str:
    if has_links:
        return (
            "Step 3/5 — 📝 <b>Extra note</b> (optional): code kahan / kaise milega, jaise <i>video ke last me</i>.\n"
            f"Bold/italic chalega (max {MAX_NOTE} characters). Nahi dena to <b>Skip</b>."
        )
    return (
        "Step 3/5 — 📝 <b>Code kahan milega?</b> Likh kar batayein, jaise <i>Channel ke pinned post me</i>.\n"
        f"Bold/italic chalega (max {MAX_NOTE} characters). Nahi dena to <b>Skip</b>."
    )


# ---------------------------------------------------------------- giveaway: parsing
def parse_links(text: str) -> tuple:
    """'Instagram - https://..' (har line me) -> ([{'label','url'}], galat_links_ki_ginti)."""
    text = text or ""
    out, bad, pos = [], 0, 0
    for mt in URL_RE.finditer(text):
        seg = text[pos:mt.start()]
        pos = mt.end()
        url = mt.group(0).rstrip(".,;)>")
        if not URL_OK_RE.match(url) or len(url) > 300:
            bad += 1
            continue
        lines = [x for x in seg.splitlines() if x.strip()]
        label = lines[-1].strip() if lines else ""
        label = re.sub(r"[\s\-–—|:=>•*]+$", "", label)
        label = re.sub(r"^[\s\-–—|:=>•*]+", "", label)
        out.append({"label": label[:20], "url": url})
    return out[:MAX_LINKS], bad


def parse_winner_time(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """'12 nov 9pm', 'kal 8:30pm', '15/11 21:00', '3 din 9pm', '9pm' -> UTC datetime (time IST maana jata hai)."""
    now = now or now_utc()
    local_now = now.astimezone(IST)
    s = (text or "").strip().lower()
    if not s or len(s) > 40:
        return None
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= h <= 12 or mi > 59:
            return None
        hh, mm = h % 12 + (12 if m.group(3) == "pm" else 0), mi
    else:
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23 or mm > 59:
            return None
    s = (s[:m.start()] + " " + s[m.end():]).strip()

    mon = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
    d = mth = y = None
    mt = re.search(rf"(\d{{1,2}})\s*[-/ ]?\s*({mon})[a-z]*(?:[\s,/-]+(\d{{4}}))?", s)
    if mt:
        d, mth, y = int(mt.group(1)), MONTHS[mt.group(2)], mt.group(3)
    else:
        mt = re.search(rf"({mon})[a-z]*\s*[-/ ]?\s*(\d{{1,2}})(?:[\s,/-]+(\d{{4}}))?", s)
        if mt:
            mth, d, y = MONTHS[mt.group(1)], int(mt.group(2)), mt.group(3)
        else:
            mt = re.search(r"(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?", s)
            if mt:
                d, mth, y = int(mt.group(1)), int(mt.group(2)), mt.group(3)

    offset = None
    if d is None:
        if re.search(r"\b(aaj|today)\b", s):
            offset = 0
        elif re.search(r"\b(kal|tomorrow)\b", s):
            offset = 1
        elif re.search(r"\bparso\b", s):
            offset = 2
        else:
            mt = re.search(r"(\d{1,3})\s*(din|day|days)\b", s)
            if mt:
                offset = int(mt.group(1))
    try:
        if d is not None:
            if y:
                yy = int(y)
                yy = yy + 2000 if yy < 100 else yy
                dt = datetime(yy, mth, d, hh, mm, tzinfo=IST)
            else:
                dt = datetime(local_now.year, mth, d, hh, mm, tzinfo=IST)
                if dt < local_now - timedelta(days=30):
                    dt = datetime(local_now.year + 1, mth, d, hh, mm, tzinfo=IST)
        else:
            dt = (local_now + timedelta(days=offset or 0)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if offset is None and dt <= local_now:
                dt += timedelta(days=1)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def winner_at_days(days: int) -> datetime:
    """Aaj se `days` din baad, raat 9 baje (IST) -> UTC."""
    local = (datetime.now(IST) + timedelta(days=days)).replace(hour=21, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def winner_time_flags(wa: Optional[datetime]) -> dict:
    """Winner time badalne par reminder flags reset."""
    if not wa:
        return {"admin_pinged": False, "users_reminded": True}
    return {"admin_pinged": False, "users_reminded": (wa - now_utc()) < timedelta(hours=1)}


def entries_closed(gw: dict) -> bool:
    wa = (gw or {}).get("winner_at")
    if not (gw.get("close_entries") and wa):
        return False
    if wa.tzinfo is None:
        wa = wa.replace(tzinfo=timezone.utc)
    return wa <= now_utc()


# ---------------------------------------------------------------- giveaway: admin cards
def draft_gw(data: dict) -> dict:
    wa = data.get("winner_at")
    if isinstance(wa, str):
        wa = datetime.fromisoformat(wa)
    return {
        "code": data["code"],
        "links": data.get("links") or [],
        "note": data.get("note"),
        "winner_at": wa,
        "close_entries": bool(data.get("close_entries")),
        "admin_message": data.get("admin_message"),
    }


def giveaway_summary(gw: dict) -> str:
    links = gw_links(gw)
    names = ", ".join(esc(link_label(l.get("label"), l["url"])) for l in links) or "—"
    wa = gw.get("winner_at")
    lines = [
        f"🔑 Code: <code>{esc(gw.get('code'))}</code>",
        f"📍 Links: {names}",
        f"📝 Note: {gw['note']}" if gw.get("note") else "📝 Note: —",
        f"⏰ Winner time: <b>{esc(fmt_when(wa))}</b>" if wa else "⏰ Winner time: —",
        f"🔒 Winner time par entries band: {'✅ ON' if gw.get('close_entries') else 'OFF'}",
        f"📩 Admin message: {'✅ set' if gw.get('admin_message') else '—'}",
    ]
    return "\n".join(lines)


def add_skip_kb(skip_cb: str) -> InlineKeyboardMarkup:
    return kb([btn("⏭ Skip", f"adm:{skip_cb}")], [btn("❌ Cancel", "adm:home")])


def time_quick_rows() -> list:
    first = []
    if winner_at_days(0) > now_utc():
        first.append(btn("🌙 Aaj 9 PM", "adm:wt:0"))
    first.append(btn("🌅 Kal 9 PM", "adm:wt:1"))
    return [first, [btn("📅 3 din baad 9 PM", "adm:wt:3"), btn("📅 7 din baad 9 PM", "adm:wt:7")]]


def add_time_kb() -> InlineKeyboardMarkup:
    return kb(*time_quick_rows(), [btn("⏭ Skip", "adm:add_skiptime")], [btn("❌ Cancel", "adm:home")])


def add_confirm_card(data: dict) -> tuple:
    gw = draft_gw(data)
    text = "👀 <b>Preview — Giveaway publish karein?</b>\n\n" + giveaway_summary(gw)
    if data.get("reset"):
        text += "\n\n⚠️ Purana giveaway aur sabhi purani entries delete hongi."
    if gw["links"] or gw["note"]:
        text += "\n\n📣 Channel par post bhi jayegi."
    rows = [[btn("✅ Publish Giveaway", "adm:add_publish")]]
    if gw["winner_at"]:
        rows.append([btn("🔒 Entries band at winner time: " + ("ON ✅" if gw["close_entries"] else "OFF"), "adm:add_tgl")])
    rows.append([btn("❌ Cancel", "adm:home")])
    return text, kb(*rows)


async def start_add_flow(cb: CallbackQuery, reset: bool) -> None:
    await set_state(ADMIN_ID, "admin_add_code", {"reset": reset})
    await safe_edit(
        cb,
        "➕ <b>Add Giveaway Code</b>\n\n"
        "Step 1/5 — Naya <b>giveaway code</b> bhejein (jo users ko sahi jagah se milega):"
        + ("\n\n⚠️ <i>Purana giveaway aur purani entries delete hongi.</i>" if reset else ""),
        admin_cancel_kb(),
    )


async def edit_card(gw: dict, note: str = "") -> tuple:
    n = await entries.count_documents({})
    text = (
        (note + "\n\n" if note else "")
        + "✏️ <b>Edit Giveaway</b>\n\n"
        + giveaway_summary(gw)
        + f"\n🎟 Entries: <b>{n}</b>\n\nJo badalna hai wo button dabayein 👇"
    )
    ent = "🔒 Entries band: " + ("ON ✅" if gw.get("close_entries") else "OFF")
    markup = kb(
        [btn("🔑 Code", "adm:ed:code"), btn("📍 Links", "adm:ed:links")],
        [btn("📝 Note", "adm:ed:note"), btn("⏰ Winner Time", "adm:ed:time")],
        [btn("📩 Message", "adm:ed:msg"), btn(ent, "adm:ed_tgl")],
        [btn("📣 Repost Post", "adm:repost")],
        [btn("⬅️ Admin Panel", "adm:home")],
    )
    return text, markup


def win_pick_prompt(n_entries: int, k: int) -> str:
    who = "Winner ki" if k == 0 else f"Winner #{k + 1} ki"
    return (
        "🏆 <b>Select Winner</b>\n\n"
        f"Current entries: <b>{n_entries}</b>\n\n"
        f"Step 1/2 — {who} <b>Telegram ID</b> bhejein (sirf number),\n"
        "ya neeche <b>Random Pick</b> dabayein (tickets ke hisaab se weighted):"
    )


async def win_confirm_card(lst: list) -> tuple:
    rows = []
    for i, x in enumerate(lst, 1):
        u = await users.find_one({"_id": x["id"]}) or {}
        entry = await entries.find_one({"_id": x["id"]})
        ent = f"✅ tickets: {entry.get('tickets', 1)}" if entry else "❌ entry nahi daali"
        rnd = " 🎲" if x.get("random") else ""
        rows.append(
            f"{i}. {esc(u.get('name'))} (<code>{x['id']}</code>){rnd}\n"
            f"   🎟 {ent}\n"
            f"   🎁 Code: <code>{esc(x['code'])}</code>"
        )
    n_targets = len(await non_winner_ids({x["id"] for x in lst}))
    gw = await get_giveaway()
    text = (
        "🏆 <b>Confirm " + ("Winners" if len(lst) > 1 else "Winner") + "</b>\n\n"
        + "\n\n".join(rows)
        + f"\n\n📨 Non-winners ko message jayega: <b>{n_targets}</b>\n"
        f"🔑 Giveaway ka data delete hoga: {'✅' if gw else '— (set nahi hai)'}\n\n"
        "Confirm karne par:\n"
        "1️⃣ Har winner ke DM me uska code jayega\n"
        "2️⃣ Baaki sabko winner-announcement jayega\n"
        "3️⃣ Giveaway ka poora data (code, links, entries) delete ho jayega\n"
        "4️⃣ Channel par winner proof post hoga\n\n"
        "<b>Ye action undo nahi hota.</b>"
    )
    brows = [[btn("✅ Confirm & Declare", "adm:win_go")]]
    if len(lst) < MAX_WINNERS:
        brows.append([btn("➕ Ek aur winner", "adm:win_more")])
    brows.append([btn("❌ Cancel", "adm:home")])
    return text, kb(*brows)


# ---------------------------------------------------------------- giveaway: channel post helpers
async def send_giveaway_post(gw: dict) -> Optional[int]:
    res, msg = await deliver_result(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, giveaway_post_text(gw), reply_markup=giveaway_post_kb(gw)),
    )
    return msg.message_id if res == OK and msg else None


async def drop_channel_post(msg_id) -> bool:
    if not msg_id:
        return False
    try:
        await bot.delete_message(TASK_CHANNEL_ID, int(msg_id))
        return True
    except TelegramAPIError:
        return False


async def refresh_channel_post(gw: dict) -> str:
    mid = gw.get("post_msg_id")
    if not mid:
        return "— (channel post nahi hai, 📣 Repost karein)"
    try:
        await bot.edit_message_text(
            giveaway_post_text(gw), chat_id=TASK_CHANNEL_ID, message_id=int(mid), reply_markup=giveaway_post_kb(gw)
        )
        return "✅ update ho gayi"
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return "✅ (pehle jaisi hi hai)"
        return "⚠️ update nahi hui (📣 Repost use karein)"
    except TelegramAPIError:
        return "⚠️ update nahi hui (📣 Repost use karein)"


async def close_channel_post(gw: Optional[dict]) -> None:
    """Winner declare hone par purani giveaway post 'khatam' ho jati hai (links/buttons hat jate hain)."""
    mid = (gw or {}).get("post_msg_id")
    if not mid:
        return
    try:
        await bot.edit_message_text(
            "🏁 <b>Ye giveaway khatam ho gaya</b>\n\n"
            "🏆 Winner declare ho chuka hai — proof channel par post hua hai.\n\n"
            "🤖 Agle giveaway ke liye bot ke saath bane rahein 👇",
            chat_id=TASK_CHANNEL_ID,
            message_id=int(mid),
            reply_markup=kb([btn("🤖 Bot kholo", url=f"https://t.me/{BOT_USERNAME}")]),
        )
    except TelegramAPIError:
        pass


async def publish_giveaway(data: dict) -> str:
    d = draft_gw(data)
    links = d["links"]
    old = await get_giveaway() or {}
    if data.get("reset"):
        await drop_channel_post(old.get("post_msg_id"))
        await entries.delete_many({})
        await users.update_many({}, {"$set": {"wrong_count": 0, "locked_until": None}})
    doc = {
        "_id": "giveaway",
        "code": d["code"],
        "admin_message": d["admin_message"],
        "links": links,
        "video_url": links[0]["url"] if links else None,
        "note": d["note"],
        "winner_at": d["winner_at"],
        "close_entries": d["close_entries"],
        "created_at": now_utc(),
        "closing": False,
        "post_msg_id": None,
        **winner_time_flags(d["winner_at"]),
    }
    await config.replace_one({"_id": "giveaway"}, doc, upsert=True)
    live_state["v"] += 1
    post_line = ""
    if links or doc["note"]:
        mid = await send_giveaway_post(doc)
        if mid:
            await config.update_one({"_id": "giveaway"}, {"$set": {"post_msg_id": mid}})
        post_line = "\n📣 Channel post: " + ("✅ ho gayi" if mid else "⚠️ nahi gayi (bot ko channel me admin banayein)")
    n = await entries.count_documents({})
    return "✅ <b>Giveaway set ho gaya!</b>\n\n" + giveaway_summary(doc) + f"\n🎟 Maujooda entries: <b>{n}</b>" + post_line


# ======================================================================
#  ADMIN: STEP-BY-STEP INPUTS HANDLER (state machine)
# ======================================================================
async def handle_admin_state(m: Message, st: dict) -> None:
    name, data = st["name"], st.get("data", {})

    # ---- Add Giveaway: step 1 (code)
    if name == "admin_add_code":
        if not m.text or not m.text.strip():
            await m.answer("⚠️ Code text me bhejein.")
            return
        code = m.text.strip()
        await set_state(ADMIN_ID, "admin_add_links", {**data, "code": code})
        await m.answer(
            f"✅ Code mil gaya: <code>{esc(code)}</code>\n\n" + ADD_LINKS_PROMPT,
            reply_markup=add_skip_kb("add_skiplinks"),
        )

    # ---- Add Giveaway: step 2 (links)
    elif name == "admin_add_links":
        links, bad = parse_links(m.text or "")
        if not links:
            await m.answer(LINKS_ERR, reply_markup=add_skip_kb("add_skiplinks"))
            return
        await set_state(ADMIN_ID, "admin_add_note", {**data, "links": links})
        names = ", ".join(esc(link_label(l.get("label"), l["url"])) for l in links)
        extra = f"\n⚠️ {bad} link galat tha, hata diya." if bad else ""
        await m.answer(
            f"✅ {len(links)} link mil gaye: <b>{names}</b>{extra}\n\n" + add_note_prompt(True),
            reply_markup=add_skip_kb("add_skipnote"),
        )

    # ---- Add Giveaway: step 3 (note)
    elif name == "admin_add_note":
        if not m.text or not m.text.strip():
            await m.answer("⚠️ Note text me bhejein, ya Skip dabayein.", reply_markup=add_skip_kb("add_skipnote"))
            return
        if len(m.text) > MAX_NOTE:
            await m.answer(f"⚠️ Note bahut lamba hai (max {MAX_NOTE} characters). Chhota karke bhejein.")
            return
        await set_state(ADMIN_ID, "admin_add_time", {**data, "note": m.html_text})
        await m.answer("✅ Note mil gaya.\n\n" + ADD_TIME_PROMPT, reply_markup=add_time_kb())

    # ---- Add Giveaway: step 4 (winner time)
    elif name == "admin_add_time":
        wa = parse_winner_time(m.text or "")
        if not wa or wa <= now_utc():
            await m.answer(TIME_ERR, reply_markup=add_time_kb())
            return
        await set_state(ADMIN_ID, "admin_add_msg", {**data, "winner_at": wa.isoformat()})
        await m.answer(
            f"✅ Winner time: <b>{esc(fmt_when(wa))}</b>\n\n" + ADD_MSG_PROMPT,
            reply_markup=add_skip_kb("add_skipmsg"),
        )

    # ---- Add Giveaway: step 5 (admin message) -> preview
    elif name == "admin_add_msg":
        if not m.text:
            await m.answer("⚠️ Message text me bhejein, ya Skip dabayein.", reply_markup=add_skip_kb("add_skipmsg"))
            return
        nd = {**data, "admin_message": m.html_text}
        await set_state(ADMIN_ID, "admin_add_confirm", nd)
        text, markup = add_confirm_card(nd)
        await m.answer(text, reply_markup=markup)

    # ---- Edit Giveaway: ek field
    elif name.startswith("admin_edit_"):
        field = name[len("admin_edit_"):]
        gw = await get_giveaway()
        if not gw or gw.get("closing"):
            await clear_state(ADMIN_ID)
            await m.answer("⚠️ Abhi koi active giveaway nahi hai.", reply_markup=admin_back_kb())
            return
        txt = (m.text or "").strip()
        if not txt:
            await m.answer("⚠️ Text me bhejein.")
            return
        upd, refresh = {}, False
        if field == "code":
            upd = {"code": txt}
        elif field == "links":
            links, bad = parse_links(txt)
            if not links:
                await m.answer(LINKS_ERR)
                return
            upd, refresh = {"links": links, "video_url": links[0]["url"]}, True
        elif field == "note":
            if len(txt) > MAX_NOTE:
                await m.answer(f"⚠️ Note bahut lamba hai (max {MAX_NOTE} characters).")
                return
            upd, refresh = {"note": m.html_text}, True
        elif field == "time":
            wa = parse_winner_time(txt)
            if not wa or wa <= now_utc():
                await m.answer(TIME_ERR, reply_markup=kb(*time_quick_rows(), [btn("↩️ Wapas", "adm:edit")]))
                return
            upd, refresh = {"winner_at": wa, **winner_time_flags(wa)}, True
        elif field == "msg":
            upd = {"admin_message": m.html_text}
        else:
            await clear_state(ADMIN_ID)
            return
        await clear_state(ADMIN_ID)
        await config.update_one({"_id": "giveaway"}, {"$set": upd})
        live_state["v"] += 1
        gw.update(upd)
        note = "✅ <b>Update ho gaya!</b>"
        if refresh:
            note += "\n📣 Channel post: " + await refresh_channel_post(gw)
        text, markup = await edit_card(gw, note)
        await m.answer(text, reply_markup=markup)

    # ---- Select Winner: step 1 (ID)
    elif name == "admin_win_id":
        try:
            wid = int((m.text or "").strip())
        except ValueError:
            await m.answer("⚠️ Sirf number wali Telegram ID bhejein.")
            return
        lst = list(data.get("list", []))
        if any(x["id"] == wid for x in lst):
            await m.answer("⚠️ Ye winner pehle hi chuna ja chuka hai. Dusri ID bhejein:")
            return
        u = await users.find_one({"_id": wid})
        if not u:
            await m.answer(
                "⚠️ Ye ID bot ke database me nahi mili. User ko pehle bot par /start karna hoga.\n"
                "Sahi ID bhejein:"
            )
            return
        await set_state(ADMIN_ID, "admin_win_code", {"winner_id": wid, "list": lst})
        await m.answer(
            f"👤 Winner: <b>{esc(u.get('name'))}</b> (<code>{wid}</code>)\n\n"
            "Step 2/2 — Ab <b>Redeem Code</b> bhejein jo winner ko DM me jayega:",
            reply_markup=admin_cancel_kb(),
        )

    # ---- Select Winner: step 2 (redeem code) -> confirm card
    elif name == "admin_win_code":
        if not m.text or not m.text.strip():
            await m.answer("⚠️ Redeem code text me bhejein.")
            return
        code = m.text.strip()
        lst = list(data.get("list", [])) + [
            {"id": int(data["winner_id"]), "code": code, "random": bool(data.get("random"))}
        ]
        await set_state(ADMIN_ID, "admin_win_confirm", {"list": lst})
        text, markup = await win_confirm_card(lst)
        await m.answer(text, reply_markup=markup)

    # ---- Broadcast: message mil gaya -> optional button
    elif name == "admin_bc_msg":
        await set_state(ADMIN_ID, "admin_bc_btn", {"chat_id": m.chat.id, "message_id": m.message_id})
        await m.reply(
            "🔘 <b>Button chahiye?</b> (sponsor promo ke liye link button)\n\n"
            "Is format me bhejein:\n<code>Button Text | https://link.com</code>\n\n"
            "ya neeche <b>Skip</b> dabayein.",
            reply_markup=kb([btn("⏭ Skip (bina button)", "adm:bc_skip")], [btn("❌ Cancel", "adm:home")]),
        )

    elif name == "admin_bc_btn":
        raw = (m.text or "").strip()
        if "|" not in raw:
            await m.answer("⚠️ Format galat hai. Aise bhejein: <code>Text | https://link.com</code>")
            return
        text_part, url_part = (p.strip() for p in raw.split("|", 1))
        if not text_part or not url_part.lower().startswith(("http://", "https://")) or len(text_part) > 40:
            await m.answer("⚠️ Button text (max 40 chars) aur valid http(s) link dein.")
            return
        data = {**data, "btn_text": text_part, "btn_url": url_part}
        n = await users.count_documents({"junk": {"$ne": True}})
        await set_state(ADMIN_ID, "admin_bc_confirm", data)
        text, markup = bc_confirm_card(n, data)
        await m.reply(text, reply_markup=markup)

    # ---- Free Code Drop: step 1 (codes)
    elif name == "admin_drop_codes":
        codes, seen = [], set()
        for line in (m.text or "").splitlines():
            c = line.strip()
            if c and c not in seen:
                seen.add(c)
                codes.append(c)
        if not codes:
            await m.answer("⚠️ Kam se kam ek code bhejein (har line me ek).")
            return
        if len(codes) > DROP_MAX_CODES:
            await m.answer(f"⚠️ Ek drop me max {DROP_MAX_CODES} codes allowed hain. Kam codes bhejein.")
            return
        if any(len(c) > 60 for c in codes):
            await m.answer("⚠️ Koi code 60 characters se lamba hai — check karke dobara bhejein.")
            return
        await set_state(ADMIN_ID, "admin_drop_time", {"codes": codes}, ttl_min=30)
        await m.answer(
            f"✅ <b>{len(codes)}</b> code(s) mil gaye.\n\n"
            "Step 2/4 — Drop <b>kab live</b> hoga? Button dabayein ya type karein:\n"
            "<code>10m</code> · <code>2h</code> · <code>9:30 PM</code> · <code>21:30</code>",
            reply_markup=kb(
                [btn("1 min", "adm:drop_t:1"), btn("5 min", "adm:drop_t:5")],
                [btn("10 min", "adm:drop_t:10"), btn("30 min", "adm:drop_t:30")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

    # ---- Free Code Drop: step 2 (time)
    elif name == "admin_drop_time":
        t = parse_drop_time(m.text or "")
        if t is None:
            await m.answer("⚠️ Time samajh nahi aaya. Aise bhejein: <code>10m</code>, <code>2h</code>, <code>9:30 PM</code>, <code>21:30</code>")
            return
        lead = (t - now_utc()).total_seconds()
        if lead < 45:
            await m.answer("⚠️ Kam se kam 1 minute baad ka time dein (teaser ke liye).")
            return
        if lead > 86400:
            await m.answer("⚠️ 24 ghante se zyada door ka time nahi de sakte.")
            return
        text, markup = await drop_mode_prompt(data["codes"], t)
        await m.answer(text, reply_markup=markup)

    # ---- Free Code Drop: step 4 (label)
    elif name == "admin_drop_label":
        label = (m.text or "").strip()
        if not label or len(label) > 60:
            await m.answer("⚠️ Label 1-60 characters ka text hona chahiye, ya Skip dabayein.")
            return
        text, markup = await drop_confirm_card(data, label)
        await m.answer(text, reply_markup=markup)

    # ---- Reward: admin code bhejta hai
    elif name == "admin_rw_code":
        code = (m.text or "").strip()
        if not code or len(code) > 200:
            await m.answer("⚠️ Redeem code text me bhejein (max 200 chars).")
            return
        rid = data["rid"]
        r = await rewards.find_one_and_update(
            {"_id": rid, "status": "requested"},
            {"$set": {"status": "sent", "sent_at": now_utc(), "code": code}},
            return_document=ReturnDocument.AFTER,
        )
        await clear_state(ADMIN_ID)
        if not r:
            await m.answer("ℹ️ Ye request ab pending nahi hai (shayad pehle hi handle ho gayi).", reply_markup=admin_back_kb())
            return
        label, unit = TRACKS[r["track"]]
        stt = await deliver(
            r["uid"],
            lambda cid: bot.send_message(
                cid,
                f"🎁 <b>Aapka ₹{r['amount']} Redeem Code aa gaya!</b>\n\n<code>{esc(code)}</code>\n\n"
                f"({label}: {r['target']} {unit} card)\n"
                "👆 Tap karke copy karein aur Google Play Store me redeem karein. Mubarak ho! 🎉",
                reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)]),
            ),
        )
        if stt != OK:  # DM nahi gaya -> wapas pending
            await rewards.update_one({"_id": rid}, {"$set": {"status": "requested"}, "$unset": {"code": ""}})
            await m.answer("❌ User ko DM nahi ja paya (bot block/delete). Request pending hi hai.", reply_markup=admin_back_kb())
            return
        site_invalidate(r["uid"])
        await m.answer(f"✅ ₹{r['amount']} code bhej diya aur card 'Redeemed' ho gaya.", reply_markup=admin_back_kb())
        await safe_log(f"🎁 <b>Reward Sent</b> — ₹{r['amount']} ({label} {r['target']}) → <code>{r['uid']}</code>")

    # ---- Reward cards config
    elif name in ("admin_rwcfg_streak", "admin_rwcfg_refer"):
        track = name.rsplit("_", 1)[1]
        cards = parse_cards(m.text or "")
        if not cards:
            await m.answer("⚠️ Format galat. Aise bhejein: <code>20:10, 50:20, 100:40</code> (targets badhte hue, max 8).")
            return
        REWARD_CFG[track] = cards
        cfg_doc = {k: REWARD_CFG[k] for k in ("streak", "refer")}
        await config.replace_one({"_id": "reward_cfg"}, {"_id": "reward_cfg", **cfg_doc}, upsert=True)
        live_state["v"] += 1
        await clear_state(ADMIN_ID)
        await m.answer(f"✅ {TRACKS[track][0]} cards update ho gaye:\n{cards_text(track)}", reply_markup=admin_back_kb())

    # ---- Notice
    elif name == "admin_notice":
        text = (m.text or "").strip()
        if not text or len(text) > 200:
            await m.answer("⚠️ Notice 1-200 characters ka text hona chahiye.")
            return
        NOTICE["text"] = text
        await config.replace_one({"_id": "notice"}, {"_id": "notice", "text": text, "at": now_utc()}, upsert=True)
        live_state["v"] += 1
        await clear_state(ADMIN_ID)
        await m.answer("✅ Notice Mini App me live ho gaya.", reply_markup=admin_back_kb())

    # ---- Add Sponsor: step 1 (channel id)
    elif name == "admin_sp_id":
        try:
            cid = int((m.text or "").strip())
        except ValueError:
            await m.answer("⚠️ Channel ID number me bhejein (jaise -1001234567890).")
            return
        try:
            chat = await bot.get_chat(cid)
            me = await bot.get_chat_member(cid, bot.id)
        except TelegramAPIError:
            await m.answer("⚠️ Bot is channel me nahi hai. Pehle bot ko channel me <b>Admin</b> banayein, phir ID bhejein.")
            return
        if me.status not in ("administrator", "creator"):
            await m.answer("⚠️ Bot channel me Admin nahi hai. Admin banakar dobara ID bhejein.")
            return
        title = chat.title or "Sponsor"
        await set_state(ADMIN_ID, "admin_sp_link", {"chat_id": cid, "title": title})
        await m.answer(
            f"✅ Channel mil gaya: <b>{esc(title)}</b>\n\n"
            "Step 2/2 — Ab is channel ka <b>join link</b> bhejein (https://t.me/...):",
            reply_markup=admin_cancel_kb(),
        )

    # ---- Add Sponsor: step 2 (invite link)
    elif name == "admin_sp_link":
        link = (m.text or "").strip()
        if not link.lower().startswith(("https://t.me/", "http://t.me/", "https://telegram.me/")):
            await m.answer("⚠️ Valid Telegram link bhejein (https://t.me/...).")
            return
        await sponsors.replace_one(
            {"_id": int(data["chat_id"])},
            {
                "_id": int(data["chat_id"]),
                "title": data["title"],
                "link": link,
                "active": True,
                "added_at": now_utc(),
            },
            upsert=True,
        )
        await clear_state(ADMIN_ID)
        await m.answer(
            f"✅ Sponsor add ho gaya: <b>{esc(data['title'])}</b>\n\n"
            "Ab users ko code dene se pehle ye channel join karna hoga. "
            "Website par bhi ye sponsor dikhega 🌐",
            reply_markup=admin_back_kb(),
        )


# ======================================================================
#  CATCH-ALL MESSAGE ROUTER  (state ke hisaab se)
# ======================================================================
@router.message()
async def on_message(m: Message):
    if m.from_user is None or (m.text and m.text.startswith("/")):
        return
    uid = m.from_user.id
    st = await get_state(uid)
    if st:
        if st["name"] == "await_code":
            await handle_code(m)
            return
        if is_admin(uid) and st["name"].startswith("admin_"):
            await handle_admin_state(m, st)
            return
    await m.answer(
        "👋 Menu ke liye neeche ke buttons use karein ya /start dabayein.",
        reply_markup=await user_menu(uid),
    )


# ======================================================================
#  BACKGROUND JOBS: WINNER + BROADCAST
# ======================================================================
async def declare_winner(winners_list: list) -> None:
    async with broadcast_lock:
        try:
            await _declare_winner(winners_list)
        except Exception:
            logger.exception("declare_winner failed")
            await config.update_one({"_id": "giveaway"}, {"$set": {"closing": False}})
            await notify_admin(
                "❌ Winner process me error aaya. Giveaway wapas khol diya gaya hai.\n"
                "Agar winner ko code mil chuka ho to dobara declare karne se pehle check kar lein."
            )


def _wlabel(x: dict) -> str:
    return esc(x["name"]) + (f" (@{esc(x['username'])})" if x.get("username") else "")


async def _declare_winner(wl: list) -> None:
    gw = await get_giveaway() or {}
    paid = list(gw.get("paid_winners") or [])  # pehle ke attempt me jinko code ja chuka hai
    infos = []
    for w in wl:
        wu = await users.find_one({"_id": w["id"]}) or {}
        infos.append(
            {
                "id": w["id"],
                "name": wu.get("name") or "Ek user",
                "username": wu.get("username"),
                "code": w["code"],
                "random": bool(w.get("random")),
            }
        )

    # giveaway band karo (naye entries na aayein)
    await config.update_one({"_id": "giveaway"}, {"$set": {"closing": True}})

    # 1) redeem code -> har winner ke DM
    ok, failed = [], []
    for i in infos:
        res = await deliver(
            i["id"],
            lambda uid, c=i["code"]: bot.send_message(uid, winner_dm_text(c), reply_markup=channel_kb()),
        )
        if res == OK:
            ok.append(i)
        else:
            failed.append(i)
            if res == JUNK:
                await mark_junk(i["id"])
    if failed:
        upd: dict = {"$set": {"closing": False}}
        if ok:  # jinko code chala gaya unki entry hata do, taaki dobara pick na ho
            await entries.delete_many({"_id": {"$in": [i["id"] for i in ok]}})
            upd["$push"] = {
                "paid_winners": {
                    "$each": [
                        {"id": i["id"], "name": i["name"], "username": i.get("username"), "random": i["random"]}
                        for i in ok
                    ]
                }
            }
        await config.update_one({"_id": "giveaway"}, upd)
        msg = "❌ <b>Ye winner(s) ko DM nahi ja paya</b> (bot block kiya ya start nahi kiya):\n"
        msg += "\n".join(f"• {_wlabel(i)} (<code>{i['id']}</code>)" for i in failed)
        if ok:
            msg += (
                "\n\n✅ In winner(s) ko code mil chuka hai:\n"
                + "\n".join(f"• {_wlabel(i)}" for i in ok)
                + "\n\nUnki entry hata di gayi hai. Giveaway wapas khul gaya — "
                "<b>baaki winner(s)</b> dobara chunke declare karein."
            )
        else:
            msg += "\n\nKuch bhi delete nahi hua. Dusra winner chunein."
        await notify_admin(msg, admin_back_kb())
        return

    all_w = paid + [
        {"id": i["id"], "name": i["name"], "username": i.get("username"), "random": i["random"]} for i in infos
    ]
    ids = [x["id"] for x in all_w]
    winner_label = ", ".join(_wlabel(x) for x in all_w)
    all_random = all(x.get("random") for x in all_w)

    # 2) baaki sabko (non-winners) announcement
    entries_count = await entries.count_documents({}) + len(paid)
    targets = await non_winner_ids(set(ids))
    status = await bot.send_message(ADMIN_ID, f"📨 Non-winners ko message bhej raha hoon… 0/{len(targets)}")
    stats = await run_broadcast(
        targets,
        lambda uid: bot.send_message(uid, non_winner_text(winner_label, len(all_w)), reply_markup=channel_kb()),
        make_progress(status, "📨 Non-winners broadcast"),
    )

    # 3) cleanup: giveaway ka poora data (code, links, entries) delete — naye giveaway ke liye reset
    giveaway_no = await winners.count_documents({}) + 1
    declared_at = now_utc()
    await config.delete_one({"_id": "giveaway"})
    deleted = (await entries.delete_many({})).deleted_count
    await users.update_many({}, {"$set": {"wrong_count": 0, "locked_until": None}})
    first = all_w[0]
    ins = await winners.insert_one(
        {
            "winner_id": first["id"],
            "name": first["name"],
            "username": first.get("username"),
            "winners_all": [{"id": x["id"], "name": x["name"], "username": x.get("username")} for x in all_w],
            "random": all_random,
            "giveaway_no": giveaway_no,
            "declared_at": declared_at,
            "entries_count": entries_count,
            "entries_deleted": deleted,
            "notified": stats,
        }
    )
    live_state["v"] += 1
    await close_channel_post(gw)  # purani giveaway post "khatam" ho jati hai

    # 4) winner proof -> task channel par
    proof = "— (off)"
    if POST_WINNER_TO_CHANNEL:
        names = ", ".join(esc(mask_name(x["name"])) for x in all_w)
        single = len(all_w) == 1
        pres, pmsg = await deliver_result(
            TASK_CHANNEL_ID,
            lambda cid: bot.send_message(
                cid,
                f"🏆 <b>Giveaway #{giveaway_no} — {'Winner' if single else 'Winners'} Declared!</b>\n\n"
                f"👤 {'Winner' if single else f'Winners ({len(all_w)})'}: <b>{names}</b>\n"
                f"🎟 Total entries: <b>{entries_count}</b>\n"
                f"🕒 {fmt_ist(declared_at)}\n"
                + ("🎲 Method: Random Pick (tickets ke hisaab se)\n" if all_random else "")
                + "\n✅ Redeem code winner ke DM me bhej diya gaya hai.\n"
                f"🤖 Agle giveaway ke liye: https://t.me/{BOT_USERNAME}",
            ),
        )
        if pres == OK and pmsg:
            await winners.update_one({"_id": ins.inserted_id}, {"$set": {"proof_url": post_link(pmsg.message_id)}})
            proof = "✅ Post ho gaya"
        else:
            proof = "⚠️ Post nahi hua (bot ko channel me admin banayein)"

    # 5) reports
    report = (
        "✅ <b>Winner declare ho gaya!</b>\n\n"
        + "\n".join(f"🏆 {_wlabel(x)}  (<code>{x['id']}</code>)" for x in all_w)
        + f"\n🎁 Giveaway #: <b>{giveaway_no}</b>\n"
        f"📨 Notified: <b>{stats['sent']}</b> / {stats['total']}\n"
        f"🚫 Blocked (Junk me gaye): <b>{stats['junk']}</b>\n"
        f"⚠️ Failed: <b>{stats['failed']}</b>\n"
        f"📣 Channel proof post: {proof}\n"
        f"🧹 Giveaway ka data + <b>{deleted}</b> entries delete ho gayi.\n\n"
        "Naye giveaway ke liye <b>Add Giveaway Code</b> use karein."
    )
    await notify_admin(report, admin_back_kb())
    await safe_log(
        "🏆 <b>Winner Declared</b>\n\n"
        + "\n".join(f"👤 {_wlabel(x)}  🆔 <code>{x['id']}</code>" for x in all_w)
        + f"\n🎁 Giveaway #{giveaway_no}  |  🎟 Entries: {entries_count}\n"
        f"📨 Notified: {stats['sent']}/{stats['total']}  |  🚫 Junk: {stats['junk']}\n"
        f"🕒 {fmt_ist(declared_at)}"
    )


# ======================================================================
#  WINNER TIME WATCHER  (admin ko time par ping + 1 ghante pehle entry walon ko reminder)
# ======================================================================
async def remind_entrants(wa: datetime) -> None:
    async with broadcast_lock:
        try:
            ids = [d["_id"] async for d in entries.find({}, {"_id": 1})]
            if not ids:
                return
            text = (
                "⏰ <b>Winner 1 ghante me chuna jayega!</b>\n\n"
                f"🎟 Aapki entry confirm hai. Winner: <b>{esc(fmt_when(wa))}</b>\n"
                "📢 Result aur proof channel par post hoga — bane rahein 👇"
            )
            await run_broadcast(ids, lambda uid: bot.send_message(uid, text, reply_markup=channel_kb()))
        except Exception:
            logger.exception("remind_entrants failed")


async def giveaway_watch_once() -> None:
    gw = await get_giveaway()
    if not gw or gw.get("closing") or not gw.get("winner_at"):
        return
    wa, now = gw["winner_at"], now_utc()
    if wa.tzinfo is None:
        wa = wa.replace(tzinfo=timezone.utc)

    if not gw.get("users_reminded") and now >= wa - timedelta(hours=1):
        res = await config.update_one(
            {"_id": "giveaway", "users_reminded": {"$ne": True}}, {"$set": {"users_reminded": True}}
        )
        if res.modified_count and now < wa:
            spawn(remind_entrants(wa))

    if not gw.get("admin_pinged") and now >= wa:
        res = await config.update_one(
            {"_id": "giveaway", "admin_pinged": {"$ne": True}}, {"$set": {"admin_pinged": True}}
        )
        if res.modified_count:
            n = await entries.count_documents({})
            await notify_admin(
                "⏰ <b>Winner ka time ho gaya!</b>\n\n"
                f"🔑 Code: <code>{esc(gw['code'])}</code>\n"
                f"🎟 Entries: <b>{n}</b>\n\n"
                "Winner chunne ke liye neeche dabayein 👇",
                kb(
                    [btn("🎲 Random Pick", "adm:win_rand")],
                    [btn("🏆 Select Winner (ID se)", "adm:winner")],
                    [btn("✏️ Edit Giveaway", "adm:edit")],
                ),
            )


async def giveaway_watch_loop() -> None:
    while True:
        await asyncio.sleep(45)
        try:
            await giveaway_watch_once()
        except Exception:
            logger.exception("giveaway_watch_loop")


async def run_admin_broadcast(
    src_chat_id: int, src_message_id: int, btn_text: Optional[str], btn_url: Optional[str]
) -> None:
    async with broadcast_lock:
        try:
            markup = kb([btn(btn_text, url=btn_url)]) if btn_text and btn_url else None
            uids = [d["_id"] async for d in users.find({"junk": {"$ne": True}}, {"_id": 1})]
            status = await bot.send_message(ADMIN_ID, f"📢 Broadcast shuru… 0/{len(uids)}")
            stats = await run_broadcast(
                uids,
                lambda uid: bot.copy_message(uid, src_chat_id, src_message_id, reply_markup=markup),
                make_progress(status, "📢 Broadcast"),
            )
            await notify_admin(
                "✅ <b>Broadcast complete!</b>\n\n"
                f"👥 Total: <b>{stats['total']}</b>\n"
                f"✅ Sent: <b>{stats['sent']}</b>\n"
                f"🚫 Blocked (Junk me gaye): <b>{stats['junk']}</b>\n"
                f"⚠️ Failed: <b>{stats['failed']}</b>\n\n"
                "Junk users hatane ke liye <b>Clear Junk</b> use karein.",
                admin_back_kb(),
            )
            await safe_log(
                f"📢 <b>Broadcast Done</b> — ✅ {stats['sent']} / {stats['total']}  |  🚫 Junk: {stats['junk']}"
            )
        except Exception:
            logger.exception("broadcast failed")
            await notify_admin("❌ Broadcast me error aaya. Logs check karein.")


# ======================================================================
#  🎯 REWARD CARDS  (streak / refer milestone -> ₹ redeem code, admin deta hai)
# ======================================================================
TRACKS = {"streak": ("🔥 Streak", "din"), "refer": ("👥 Refer", "refer")}


def mention(uid: int, name: Optional[str]) -> str:
    """Blue clickable naam (profile khulti hai)."""
    return f'<a href="tg://user?id={uid}">{esc((name or "User")[:30])}</a>'


def site_invalidate(uid: int) -> None:
    fn = site_ctx.get("hooks", {}).get("invalidate")
    if fn:
        fn(uid)


def parse_cards(text: str) -> Optional[list]:
    """'20:10, 50:20' -> [[20,10],[50,20]]  (targets badhte hue, max 8 cards)."""
    out = []
    for part in re.split(r"[,\n;]+", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,4})\s*[:=\-]\s*(\d{1,5})", part)
        if not m:
            return None
        out.append([int(m.group(1)), int(m.group(2))])
    if not out or len(out) > 8:
        return None
    targets = [t for t, _ in out]
    if targets != sorted(set(targets)) or min(targets) < 1 or any(a < 1 for _, a in out):
        return None
    return out


def cards_text(track: str) -> str:
    label, unit = TRACKS[track]
    return ", ".join(f"{t} {unit} → ₹{a}" for t, a in REWARD_CFG[track])


async def grant_card(uid: int, track: str, cycle: int, value: int) -> Optional[dict]:
    """Value kisi target ke barabar ho to card 'earned' (idempotent)."""
    for target, amount in REWARD_CFG[track]:
        if value == target:
            rid = f"{uid}:{track}:{cycle}:{target}"
            try:
                await rewards.insert_one(
                    {"_id": rid, "uid": uid, "track": track, "cycle": cycle, "target": target,
                     "amount": amount, "status": "earned", "earned_at": now_utc()}
                )
            except DuplicateKeyError:
                return None
            site_invalidate(uid)
            return {"id": rid, "track": track, "target": target, "amount": amount}
    return None


async def notify_card_earned(uid: int, card: dict) -> None:
    label, unit = TRACKS[card["track"]]
    await deliver(
        uid,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>Reward Card Unlock!</b>\n\n{label}: <b>{card['target']} {unit}</b> poora hua!\n"
            f"🎁 Aapka <b>₹{card['amount']} Redeem Code</b> card ready hai.\n\n"
            "📱 App → <b>Rewards</b> tab → <b>Redeem Now</b> dabayein. Admin 24 ghante me code bhejega.",
            reply_markup=kb([btn("🎁 Rewards kholo", web_app=WEBSITE_URL)]),
        ),
    )


async def redeem_reward_core(uid: int, rid: str) -> dict:
    u = await get_user_cached(uid)
    if not u:
        return {"status": "unregistered"}
    if u.get("banned"):
        return {"status": "banned"}
    now = now_utc()
    r = await rewards.find_one_and_update(
        {"_id": str(rid), "uid": uid, "status": "earned"},
        {"$set": {"status": "requested", "requested_at": now, "deadline": now + timedelta(hours=24),
                  "remind_at": now + timedelta(hours=12)}},
        return_document=ReturnDocument.AFTER,
    )
    if not r:
        cur = await rewards.find_one({"_id": str(rid), "uid": uid})
        return {"status": "already" if cur else "not_found", "state": cur.get("status") if cur else None}
    site_invalidate(uid)
    spawn(send_reward_card(r))
    return {"status": "ok", "deadline": r["deadline"].isoformat()}


async def send_reward_card(r: dict, reminder: bool = False) -> None:
    uid = r["uid"]
    u = await users.find_one({"_id": uid}) or {}
    junk_friends = await users.count_documents({"ref_by": uid, "junk": True})
    label, unit = TRACKS[r["track"]]
    left = r["deadline"] - now_utc()
    left_txt = fmt_td(left) if left.total_seconds() > 0 else "⚠️ time nikal chuka"
    flag = "\n⚠️ <b>Fraud flag</b> — pehle check kar lein!" if u.get("ref_flag") else ""
    head = "⏰ <b>REMINDER — Reward pending</b>" if reminder else "🎁 <b>Reward Redeem Request</b>"
    text = (
        f"{head}\n\n"
        f"👤 {mention(uid, u.get('name'))}  (<code>{uid}</code>)\n"
        f"🏷 {label}: <b>{r['target']} {unit}</b> → <b>₹{r['amount']}</b> code\n"
        f"📊 Streak: {u.get('streak', 0)} (best {u.get('best_streak', 0)}) · "
        f"Refers: {u.get('ref_count', 0)} (blocked friends: {junk_friends})\n"
        f"⏳ Deadline: <b>{fmt_ist(r['deadline'])}</b> ({left_txt}){flag}"
    )
    await notify_admin(text, kb([btn("📤 Send Code", f"rw:send:{r['_id']}"), btn("❌ Reject", f"rw:rej:{r['_id']}")]))


@router.callback_query(F.data.startswith("rw:"))
async def cb_reward_admin(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Sirf admin ke liye", show_alert=True)
        return
    await cb.answer()
    try:
        _, action, rid = cb.data.split(":", 2)
    except ValueError:
        return
    r = await rewards.find_one({"_id": rid})
    if not r:
        await bot.send_message(ADMIN_ID, "⚠️ Ye reward nahi mila.")
        return
    u = await users.find_one({"_id": r["uid"]}) or {}
    who = f"{mention(r['uid'], u.get('name'))} (<code>{r['uid']}</code>)"
    if action == "view":
        await send_reward_card(r)
    elif r["status"] != "requested":
        await bot.send_message(ADMIN_ID, f"ℹ️ Ye request ab <b>{esc(r['status'])}</b> hai.")
    elif action == "send":
        await set_state(ADMIN_ID, "admin_rw_code", {"rid": rid}, ttl_min=120)
        await bot.send_message(
            ADMIN_ID, f"📤 {who} ke liye <b>₹{r['amount']}</b> redeem code bhejein (text):", reply_markup=admin_cancel_kb()
        )
    elif action == "rej":
        await bot.send_message(
            ADMIN_ID,
            f"❌ {who} ki ₹{r['amount']} request <b>reject</b> karein?",
            reply_markup=kb([btn("✅ Haan, Reject", f"rw:rejy:{rid}")], [btn("↩️ Wapas", "adm:home")]),
        )
    elif action == "rejy":
        res = await rewards.find_one_and_update(
            {"_id": rid, "status": "requested"}, {"$set": {"status": "rejected", "rejected_at": now_utc()}}
        )
        if res:
            site_invalidate(r["uid"])
            await deliver(
                r["uid"],
                lambda cid: bot.send_message(
                    cid,
                    f"❌ Aapki ₹{r['amount']} reward request verify nahi ho paayi.\n"
                    f"Madad ke liye contact karein: {esc(SUPPORT_USERNAME)}",
                ),
            )
            await bot.send_message(ADMIN_ID, "✅ Request reject ho gayi aur user ko bata diya.", reply_markup=admin_back_kb())


async def rewards_watch_once() -> int:
    now = now_utc()
    due = [r async for r in rewards.find({"status": "requested", "remind_at": {"$lte": now}}).limit(10)]
    for r in due:
        dl = r["deadline"]
        if now < dl - timedelta(hours=4):
            nxt = dl - timedelta(hours=4)
        elif now < dl:
            nxt = dl
        else:
            nxt = now + timedelta(hours=6)
        await rewards.update_one({"_id": r["_id"]}, {"$set": {"remind_at": nxt}})
        await send_reward_card(r, reminder=True)
    return len(due)


async def rewards_watch_loop() -> None:
    """Pending reward requests ka reminder admin ko (12h, deadline-4h, deadline, phir har 6h)."""
    while True:
        await asyncio.sleep(60)
        try:
            await rewards_watch_once()
        except Exception:
            logger.exception("rewards_watch_loop")


async def settings_core(uid: int, streak_remind: bool) -> dict:
    await users.update_one({"_id": uid}, {"$set": {"streak_remind": bool(streak_remind)}})
    site_invalidate(uid)
    return {"status": "ok", "streak_remind": bool(streak_remind)}


async def streak_remind_once() -> dict:
    """Din me ek baar (atomic lock) un users ko DM jinki streak aaj claim nahi hui."""
    today = today_ist()
    try:
        await config.update_one({"_id": "streak_remind", "date": {"$ne": today}}, {"$set": {"date": today}}, upsert=True)
    except DuplicateKeyError:
        return {"skipped": True}
    cur = users.find(
        {"streak": {"$gte": STREAK_REMIND_MIN}, "last_claim": {"$ne": today}, "streak_remind": {"$ne": False},
         "junk": {"$ne": True}, "banned": {"$ne": True}},
        {"streak": 1},
    ).limit(STREAK_REMIND_MAX)
    streaks = {d["_id"]: d.get("streak", 0) async for d in cur}
    if not streaks:
        return {"total": 0}
    markup = kb([btn("🎁 Claim karo", web_app=WEBSITE_URL)], [btn("🔕 Reminder band karo", "sr:off")])
    return await run_broadcast(
        list(streaks),
        lambda uid: bot.send_message(
            uid,
            f"🔥 <b>Streak bachao!</b>\n\nAapki <b>{streaks[uid]} din</b> ki streak hai — aaj ka Daily Bonus claim nahi hua.\n"
            "Raat 12 baje se pehle claim karein, warna streak toot jayegi!",
            reply_markup=markup,
        ),
    )


async def streak_remind_loop() -> None:
    """Roz STREAK_REMIND_HOUR (IST) par streak-reminder chalata hai."""
    while True:
        await asyncio.sleep(60)
        try:
            if datetime.now(IST).hour == STREAK_REMIND_HOUR:
                stats = await streak_remind_once()
                if not stats.get("skipped"):
                    logger.info("streak reminders: %s", stats)
        except Exception:
            logger.exception("streak_remind_loop")


@router.callback_query(F.data == "sr:off")
async def cb_streak_off(cb: CallbackQuery):
    await settings_core(cb.from_user.id, False)
    await cb.answer("🔕 Streak reminder band ho gaya (Profile me dobara ON kar sakte ho)", show_alert=True)


@router.callback_query(F.data == "refcheck")
async def cb_refcheck(cb: CallbackQuery):
    res = await maybe_credit_referral(cb.from_user.id)
    if res == "need_join":
        await cb.answer("📢 Pehle channel join karein, fir ye button dabayein.", show_alert=True)
    elif res == "credited":
        await cb.answer("✅ Verified! Aapke dost ko reward mil gaya. Shukriya 🙏", show_alert=True)
    else:
        await cb.answer("✅ Sab theek hai!", show_alert=True)


# ======================================================================
#  ⚡ FREE CODE DROPS  (channel post edit nahi hoti — countdown/claims sirf Mini App me)
# ======================================================================
DEFAULT_DROP_LABEL = "Google Play Redeem Code"
MEDALS = ["🥇", "🥈", "🥉"]
drop_events: dict = {}


def mem_set(d: dict) -> None:
    """Active drop ki in-memory state (DB ke bina fast reject + /api/state ke liye)."""
    old = live_state["drop"]
    keep = old["users"] if old and old["no"] == d["_id"] else set()
    live_state["drop"] = {
        "no": d["_id"], "status": d["status"], "mode": d.get("mode", "fast"), "label": d.get("label"),
        "total": d["total"], "claimed": d.get("claimed_count", 0), "queued": 0,
        "go_live_at": d["go_live_at"], "live_at": d.get("live_at"), "window_ends": None,
        "lucky_closed": bool(d.get("lucky_closed")), "users": keep,
    }
    live_state["v"] += 1


def mem_patch(**kw) -> None:
    ld = live_state["drop"]
    if ld:
        ld.update(kw)
        live_state["v"] += 1


def post_link(msg_id: int) -> str:
    """Channel post ka link (public username ho to wahi, warna private /c/ link)."""
    m = re.match(r"^https?://t\.me/([A-Za-z0-9_]{4,})/?$", TASK_CHANNEL_LINK)
    if m:
        return f"https://t.me/{m.group(1)}/{msg_id}"
    return f"https://t.me/c/{str(TASK_CHANNEL_ID)[4:]}/{msg_id}"


def parse_drop_time(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """'10m', '2h', '9:30 PM', '21:30'  ->  UTC datetime (clock time IST maana jata hai)."""
    now = now or now_utc()
    s = (text or "").strip().lower().replace(".", ":")
    m = re.fullmatch(r"(\d{1,4})\s*(m|min|mins|minute|minutes)", s)
    if m:
        return now + timedelta(minutes=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,3})\s*(h|hr|hrs|hour|hours)", s)
    if m:
        return now + timedelta(hours=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap:
            if not 1 <= hh <= 12:
                return None
            hh = hh % 12 + (12 if ap == "pm" else 0)
        if hh > 23 or mm > 59:
            return None
        local_now = now.astimezone(IST)
        local = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if local <= local_now + timedelta(seconds=30):
            local += timedelta(days=1)
        return local.astimezone(timezone.utc)
    return None


def fmt_countdown(sec: float) -> str:
    sec = max(int(sec), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def sec_text(ms: float) -> str:
    return f"{ms / 1000:.1f} sec"


def fmt_drop_time(dt: datetime) -> str:
    local = dt.astimezone(IST)
    same_day = local.date() == datetime.now(IST).date()
    return local.strftime("%I:%M %p") if same_day else local.strftime("%d %b, %I:%M %p")


def wall_lines(wall: list, limit: int = 30, links: bool = False) -> str:
    lines = []
    for w in wall[:limit]:
        r = w.get("rank", 0)
        tag = MEDALS[r - 1] if 1 <= r <= 3 else f"{r}."
        nm = mention(w["uid"], short_name(w.get("name"))) if links else f"<b>{esc(short_name(w.get('name')))}</b>"
        lines.append(f"{tag} {nm} — {sec_text(w.get('ms', 0))}")
    return "\n".join(lines)


def render_teaser(drop: dict) -> str:
    lucky = drop.get("mode") == "lucky"
    mode_line = (
        f"🎲 <b>Lucky Draw:</b> live hone ke {LUCKY_WINDOW} sec me jo bhi JOIN karega unme se <b>random {drop['total']}</b> winners!\n"
        if lucky else ""
    )
    return (
        "⚡ <b>FREE REDEEM CODE DROP</b> ⚡\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"👥 Sirf <b>{drop['total']}</b> logon ke liye!\n"
        f"🕘 Live hoga: <b>{fmt_drop_time(drop['go_live_at'])}</b> (IST)\n"
        f"{mode_line}\n"
        "📲 <b>Abhi Google Play Store kholkar Redeem screen par ready baith jao!</b>\n"
        "⏳ Live countdown aur claim <b>Mini App</b> me dekho 👇"
    )


def render_live(drop: dict) -> str:
    if drop.get("mode") == "lucky":
        return (
            "🎲 <b>LUCKY DROP LIVE!</b> 🎲\n\n"
            f"🎁 <b>{esc(drop['label'])}</b>\n"
            f"⏱ Sirf <b>{LUCKY_WINDOW} second</b> — abhi <b>JOIN</b> dabao!\n"
            f"👥 Random <b>{drop['total']}</b> winners chune jayenge (tez ya dheere phone — sabko barabar mauka)."
        )
    return (
        "🔥 <b>DROP LIVE — CLAIM NOW!</b> 🔥\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"📦 Sirf <b>{drop['total']}</b> codes!\n\n"
        "👇 <b>CLAIM NOW</b> dabao — sabse pehle wale ko code milega!\n"
        "📱 Live claim wall Mini App me dekho."
    )


def render_done(drop: dict, wall: list, reason: str) -> str:
    lucky = drop.get("mode") == "lucky"
    title = {
        "sold_out": "✅ <b>DROP COMPLETE</b> ✅",
        "lucky_done": "🎲 <b>LUCKY DRAW COMPLETE</b> 🎲",
        "timeout": "⏰ <b>DROP KHATAM</b> ⏰",
    }.get(reason, "🛑 <b>DROP KHATAM</b> 🛑")
    extra = ""
    if reason == "sold_out" and wall:
        extra = f"\n⚡ Saare codes sirf <b>{sec_text(wall[-1].get('ms', 0))}</b> me claim ho gaye!"
    body = wall_lines(wall, links=True) if wall else "Kisi ne claim nahi kiya 😔"
    return (
        f"{title}\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"📦 {'Winners' if lucky else 'Claimed'}: <b>{drop.get('claimed_count', 0)}/{drop['total']}</b>{extra}\n\n"
        f"🏁 <b>{'Lucky Winners' if lucky else 'Claim Wall'}</b>\n{body}\n\n"
        "🔔 Agla drop miss mat karna — channel notification ON rakho!"
    )


def teaser_kb(no: int) -> InlineKeyboardMarkup:
    return kb([btn("🔔 Remind Me", f"drop:remind:{no}")], [btn("📱 Open App", url=app_link())])


def live_kb(no: int, lucky: bool = False) -> InlineKeyboardMarkup:
    return kb([btn("🎲 JOIN LUCKY DRAW" if lucky else "🎁 CLAIM NOW", f"drop:claim:{no}")], [btn("📱 Open App", url=app_link())])


def done_kb() -> InlineKeyboardMarkup:
    return kb([btn("📱 Open App", url=app_link())])


# ---------------------------------------------------------------- channel helpers
async def pin_post(msg_id: int) -> None:
    try:
        await bot.pin_chat_message(chat_id=TASK_CHANNEL_ID, message_id=msg_id, disable_notification=True)
    except Exception as e:  # pin fail hone se drop nahi rukna chahiye
        logger.warning("Pin nahi hua (bot ko 'Pin messages' permission chahiye): %s", e)


async def unpin_post(msg_id: int) -> None:
    try:
        await bot.unpin_chat_message(chat_id=TASK_CHANNEL_ID, message_id=msg_id)
    except Exception as e:
        logger.warning("Unpin nahi hua: %s", e)


async def get_wall(no: int, limit: int = 50) -> list:
    cur = drop_claims.find({"drop": no, "rank": {"$ne": None}}).sort("rank", 1).limit(limit)
    return [d async for d in cur]


async def active_drop() -> Optional[dict]:
    return await drops.find_one({"status": {"$in": ["scheduled", "live"]}})


# ---------------------------------------------------------------- create / run / finish
async def create_drop(codes: list, go_live_at: datetime, label: str, mode: str = "fast") -> Optional[int]:
    ctr = await config.find_one_and_update(
        {"_id": "drop_counter"}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    no = int(ctr["n"])
    drop = {
        "_id": no, "status": "scheduled", "mode": mode, "label": label, "total": len(codes), "claimed_count": 0,
        "go_live_at": go_live_at, "created_at": now_utc(), "reminders": [], "reminded": False,
        "teaser_msg_id": None, "live_msg_id": None,
    }
    await drops.insert_one(drop)
    for c in codes:
        await drop_codes.insert_one({"drop": no, "code": c, "claimed_by": None})

    status, msg = await deliver_result(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, render_teaser(drop), reply_markup=teaser_kb(no)),
    )
    if status != OK:  # channel post nahi gayi -> sab rollback
        await drops.delete_one({"_id": no})
        await drop_codes.delete_many({"drop": no})
        return None
    await drops.update_one({"_id": no}, {"$set": {"teaser_msg_id": msg.message_id}})
    drop["teaser_msg_id"] = msg.message_id
    mem_set(drop)
    await pin_post(msg.message_id)
    start_drop_runner(no)
    return no


def start_drop_runner(no: int) -> None:
    if no in drop_tasks and not drop_tasks[no].done():
        return
    drop_events[no] = asyncio.Event()
    task = asyncio.create_task(run_drop(no))
    drop_tasks[no] = task

    def _done(_t, n=no):
        drop_tasks.pop(n, None)
        drop_events.pop(n, None)

    task.add_done_callback(_done)


async def resume_drops() -> None:
    """Restart ke baad scheduled/live drops dobara chalu."""
    async for d in drops.find({"status": {"$in": ["scheduled", "live"]}}):
        logger.info("Resuming drop #%s (%s)", d["_id"], d["status"])
        mem_set(d)
        start_drop_runner(d["_id"])


async def run_drop(no: int) -> None:
    try:
        await _run_drop(no)
    except Exception:
        logger.exception("drop %s runner crashed", no)
        await notify_admin(f"❌ Drop #{no} runner me error aaya. Logs check karein.")


async def dm_subscribers(no: int, text: str, markup: Optional[InlineKeyboardMarkup]) -> None:
    d = await drops.find_one({"_id": no})
    ids = list((d or {}).get("reminders", []))
    if ids:
        await run_broadcast(ids, lambda uid: bot.send_message(uid, text, reply_markup=markup))


async def go_live(no: int, drop: dict) -> bool:
    now = now_utc()
    lucky = drop.get("mode") == "lucky"
    await drops.update_one({"_id": no}, {"$set": {"status": "live", "live_at": now}})
    mem_patch(status="live", live_at=now, window_ends=now + timedelta(seconds=LUCKY_WINDOW))
    status, msg = await deliver_result(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, render_live(drop), reply_markup=live_kb(no, lucky)),
    )
    if status != OK:
        await drops.update_one({"_id": no}, {"$set": {"status": "cancelled"}})
        mem_patch(status="cancelled")
        await notify_admin(
            f"❌ Drop #{no}: live post channel par nahi ja payi (bot ko channel me admin banayein).\n"
            "Drop cancel ho gaya — codes DB me safe hain."
        )
        return False
    live_at = now_utc()  # claim timing post jaane ke baad se
    await drops.update_one({"_id": no}, {"$set": {"live_msg_id": msg.message_id, "live_at": live_at}})
    mem_patch(live_at=live_at, window_ends=live_at + timedelta(seconds=LUCKY_WINDOW))
    if drop.get("teaser_msg_id"):
        await unpin_post(drop["teaser_msg_id"])
    await pin_post(msg.message_id)
    spawn(
        dm_subscribers(
            no,
            f"🔥 <b>DROP #{no} LIVE HO GAYA!</b>\n\nAbhi {'JOIN' if lucky else 'CLAIM'} karo!",
            kb([btn("🎁 App me kholo", web_app=WEBSITE_URL)], [btn("📢 Channel Post", url=post_link(msg.message_id))]),
        )
    )
    return True


async def _run_drop(no: int) -> None:
    drop = await drops.find_one({"_id": no})
    if not drop:
        return
    ev = drop_events.setdefault(no, asyncio.Event())

    # ---- phase 1: wait (koi DB polling nahi; admin cancel event se)
    if drop["status"] == "scheduled":
        reminded = bool(drop.get("reminded"))
        while True:
            remaining = (drop["go_live_at"] - now_utc()).total_seconds()
            if remaining <= 0:
                break
            if remaining <= 60 and not reminded:
                reminded = True
                await drops.update_one({"_id": no}, {"$set": {"reminded": True}})
                tl = post_link(drop["teaser_msg_id"]) if drop.get("teaser_msg_id") else TASK_CHANNEL_LINK
                spawn(
                    dm_subscribers(
                        no,
                        f"⏰ <b>Drop #{no} sirf 1 minute me live hoga!</b>\n\n"
                        "📲 Abhi Google Play Store ka <b>Redeem screen</b> kholkar ready ho jao!",
                        kb([btn("📱 App kholo", web_app=WEBSITE_URL)], [btn("📢 Channel Post", url=tl)]),
                    )
                )
            wait = min(remaining, 30.0 if remaining > 70 else 1.0)
            try:
                await asyncio.wait_for(ev.wait(), timeout=max(wait, 0.02))
                return  # cancel hua
            except asyncio.TimeoutError:
                pass
        cur = await drops.find_one({"_id": no})
        if not cur or cur["status"] != "scheduled":
            return
        if not await go_live(no, cur):
            return

    # ---- phase 2: live
    d = await drops.find_one({"_id": no})
    if not d or d["status"] != "live":
        return
    if d.get("mode") == "lucky":
        end = d["live_at"] + timedelta(seconds=LUCKY_WINDOW)
        try:
            await asyncio.wait_for(ev.wait(), timeout=max((end - now_utc()).total_seconds(), 0.02))
            return
        except asyncio.TimeoutError:
            pass
        mem_patch(lucky_closed=True)
        await drops.update_one({"_id": no}, {"$set": {"lucky_closed": True}})
        await asyncio.sleep(0.8)  # in-flight joins settle
        await resolve_lucky(no)
        await finish_drop(no, "lucky_done")
        return
    while True:
        try:
            await asyncio.wait_for(ev.wait(), timeout=0.25)
            return
        except asyncio.TimeoutError:
            pass
        ls = live_state["drop"]
        if not ls or ls["no"] != no or ls["status"] != "live":
            return
        if ls["claimed"] >= ls["total"]:
            await finish_drop(no, "sold_out")
            return
        if ls.get("live_at") and (now_utc() - ls["live_at"]).total_seconds() > DROP_TIMEOUT_MIN * 60:
            await finish_drop(no, "timeout")
            return


async def resolve_lucky(no: int) -> None:
    d = await drops.find_one({"_id": no})
    docs = [c async for c in drop_claims.find({"drop": no, "lucky": True})]
    n = min(d["total"], len(docs))
    picks = random.SystemRandom().sample(docs, n) if n else []
    picks.sort(key=lambda c: c.get("ms", 0))
    won = 0
    for rank, c in enumerate(picks, 1):
        code_doc = await drop_codes.find_one_and_update(
            {"drop": no, "claimed_by": None}, {"$set": {"claimed_by": c["uid"], "claimed_at": now_utc()}}
        )
        if not code_doc:
            break
        won += 1
        await drop_claims.update_one({"_id": c["_id"]}, {"$set": {"rank": rank, "code": code_doc["code"]}})
        spawn(after_claim(c["uid"], c.get("name"), no, rank, c.get("ms", 0), code_doc["code"], lucky=True))
        site_invalidate(c["uid"])
    await drop_claims.update_many({"drop": no, "lucky": True, "rank": None}, {"$set": {"lost": True}})
    await drops.update_one({"_id": no}, {"$set": {"claimed_count": won, "lucky_entries": len(docs)}})
    mem_patch(claimed=won)


async def finish_drop(no: int, reason: str) -> None:
    d = await drops.find_one_and_update(
        {"_id": no, "status": "live"},
        {"$set": {"status": "ended", "ended_at": now_utc(), "end_reason": reason}},
        return_document=ReturnDocument.AFTER,
    )
    if not d:
        return
    mem_patch(status="ended")
    ev = drop_events.get(no)
    if ev:
        ev.set()
    await asyncio.sleep(1.0)  # in-flight claims settle ho jayein
    d = await drops.find_one({"_id": no}) or d
    wall = await get_wall(no)
    left = [c["code"] async for c in drop_codes.find({"drop": no, "claimed_by": None})]

    # channel par EK nayi final post (edit nahi) + live post unpin
    await deliver(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, render_done(d, wall, reason), reply_markup=done_kb()),
    )
    if d.get("live_msg_id"):
        await unpin_post(d["live_msg_id"])

    reason_txt = {"sold_out": "sab codes claim ho gaye ✅", "lucky_done": "lucky draw complete 🎲",
                  "timeout": "time khatam ⏰"}.get(reason, "admin ne end kiya 🛑")
    lines = "\n".join(
        f"{w['rank']}. {mention(w['uid'], w.get('name'))} (<code>{w['uid']}</code>) — {sec_text(w.get('ms', 0))}"
        for w in wall[:15]
    ) or "— koi claim nahi"
    more = f"\n… aur {len(wall) - 15}" if len(wall) > 15 else ""
    left_txt = ""
    if left:
        shown = "\n".join(f"<code>{esc(c)}</code>" for c in left[:20])
        left_txt = f"\n\n🔓 <b>Bache hue codes</b> ({len(left)}) — dobara use kar sakte ho:\n{shown}"
    await notify_admin(
        f"🏁 <b>Drop #{no} khatam</b> — {reason_txt}\n\n"
        f"📦 {'Winners' if d.get('mode') == 'lucky' else 'Claimed'}: <b>{d.get('claimed_count', 0)}/{d['total']}</b>"
        + (f" (joined: {d.get('lucky_entries', 0)})" if d.get("mode") == "lucky" else "")
        + f"\n\n<b>List</b>\n{lines}{more}{left_txt}",
        admin_back_kb(),
    )
    await safe_log(f"⚡ <b>Drop #{no} Ended</b> — {d.get('claimed_count', 0)}/{d['total']} ({reason})")


async def cancel_drop(no: int) -> str:
    d = await drops.find_one({"_id": no})
    if not d:
        return "Drop nahi mila."
    if d["status"] == "scheduled":
        res = await drops.find_one_and_update(
            {"_id": no, "status": "scheduled"}, {"$set": {"status": "cancelled", "ended_at": now_utc()}}
        )
        if not res:
            return "Drop pehle hi badal chuka hai."
        mem_patch(status="cancelled")
        ev = drop_events.get(no)
        if ev:
            ev.set()
        if d.get("teaser_msg_id"):
            await unpin_post(d["teaser_msg_id"])
            await deliver(
                TASK_CHANNEL_ID,
                lambda cid: bot.send_message(cid, "❌ <b>Pehle announce kiya gaya drop cancel ho gaya.</b>\n\nAgle drop ke liye bane rahein 🔔", reply_markup=done_kb()),
            )
        return f"✅ Drop #{no} cancel ho gaya. Codes DB me safe hain (naya drop banakar use kar sakte ho)."
    if d["status"] == "live":
        await finish_drop(no, "admin")
        return f"✅ Drop #{no} end kar diya. Report neeche aayegi."
    return "Ye drop pehle hi khatam ho chuka hai."


# ---------------------------------------------------------------- claim / remind (bot + Mini App)
async def claim_drop_core(uid: int, no: int) -> dict:
    ls = live_state["drop"]
    mode = "fast"
    if ls and ls["no"] == no:  # fast path: DB ke bina reject
        st = ls["status"]
        if st == "scheduled":
            return {"status": "not_live"}
        if st != "live":
            return {"status": "ended"}
        mode = ls["mode"]
        if mode == "lucky" and ls["lucky_closed"]:
            return {"status": "late"}
        if mode != "lucky" and ls["claimed"] >= ls["total"]:
            return {"status": "sold_out"}
        live_at = ls.get("live_at") or now_utc()
    else:
        drop = await drops.find_one({"_id": no})
        if not drop:
            return {"status": "not_found"}
        if drop["status"] == "scheduled":
            return {"status": "not_live"}
        if drop["status"] != "live":
            return {"status": "ended"}
        mode = drop.get("mode", "fast")
        live_at = drop.get("live_at") or now_utc()
        if mode == "lucky" and drop.get("lucky_closed"):
            return {"status": "late"}

    u = await get_user_cached(uid)
    if not u or not u.get("verified"):
        return {"status": "unverified"}
    if u.get("banned"):
        return {"status": "banned"}

    now = now_utc()
    ms = max(int((now - live_at).total_seconds() * 1000), 1)
    claim_id = f"{no}:{uid}"
    doc = {"_id": claim_id, "drop": no, "uid": uid, "name": u.get("name"), "username": u.get("username"),
           "rank": None, "ms": ms, "at": now}
    if mode == "lucky":
        doc["lucky"] = True
    try:
        await drop_claims.insert_one(doc)
    except DuplicateKeyError:
        prev = await drop_claims.find_one({"_id": claim_id}) or {}
        if prev.get("lucky") and prev.get("rank") is None:
            return {"status": "queued", "dup": True}
        return {"status": "duplicate", "rank": prev.get("rank"), "ms": prev.get("ms", 0), "code": prev.get("code")}

    if mode == "lucky":
        if ls and ls["no"] == no:
            ls["queued"] += 1
            live_state["v"] += 1
        site_invalidate(uid)
        return {"status": "queued"}

    # atomic: ek code ek hi user ko
    code_doc = await drop_codes.find_one_and_update(
        {"drop": no, "claimed_by": None}, {"$set": {"claimed_by": uid, "claimed_at": now}}
    )
    if not code_doc:
        await drop_claims.delete_one({"_id": claim_id})
        mem_patch(claimed=ls["total"] if ls and ls["no"] == no else 0)
        return {"status": "sold_out"}

    d = await drops.find_one_and_update({"_id": no}, {"$inc": {"claimed_count": 1}}, return_document=ReturnDocument.AFTER)
    rank = int(d["claimed_count"])
    code = code_doc["code"]
    await drop_claims.update_one({"_id": claim_id}, {"$set": {"rank": rank, "code": code}})
    if ls and ls["no"] == no:
        ls["claimed"] = max(ls["claimed"], rank)
        ls["users"].add(uid)
        live_state["v"] += 1
    site_invalidate(uid)
    spawn(after_claim(uid, u.get("name"), no, rank, ms, code))
    return {"status": "ok", "rank": rank, "ms": ms, "code": code}


async def after_claim(uid: int, name: Optional[str], no: int, rank: int, ms: int, code: str, lucky: bool = False) -> None:
    await deliver(
        uid,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>Mubarak ho! Drop #{no} {'jeet liya' if lucky else 'claim ho gaya'}!</b>\n\n"
            f"🏅 Rank: <b>#{rank}</b>   ⚡ {sec_text(ms)}\n\n"
            f"🎁 Aapka Redeem Code:\n<code>{esc(code)}</code>\n\n"
            "👆 Tap karke copy karein aur <b>turant Google Play Store me redeem</b> karein!",
            reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)]),
        ),
    )
    await safe_log(
        f"⚡ <b>Drop #{no} Winner</b>\n\n{mention(uid, name)}  (<code>{uid}</code>)\n"
        f"🏅 Rank #{rank}  ⚡ {sec_text(ms)}\n🎁 Code: <code>{esc(code)}</code>"
    )


async def remind_core(uid: int, no: int) -> dict:
    if not await users.find_one({"_id": uid}, {"_id": 1}):
        return {"status": "unregistered"}
    d = await drops.find_one({"_id": no})
    if not d or d["status"] != "scheduled":
        return {"status": "closed"}
    res = await drops.update_one({"_id": no}, {"$addToSet": {"reminders": uid}})
    site_invalidate(uid)
    return {"status": "ok" if res.modified_count else "already"}


@router.callback_query(F.data.startswith("drop:"))
async def cb_drop(cb: CallbackQuery):
    try:
        _, action, no_s = cb.data.split(":")
        no = int(no_s)
    except ValueError:
        await cb.answer()
        return
    uid = cb.from_user.id
    start_url = f"https://t.me/{BOT_USERNAME}?start=drop"
    try:
        if action == "claim":
            r = await claim_drop_core(uid, no)
            st = r["status"]
            if st == "ok":
                await cb.answer(
                    f"🎉 Mubarak! Rank #{r['rank']} ({r['ms'] / 1000:.1f}s)\n\n🎁 Code: {r['code']}\n\n(DM me bhi bheja gaya)",
                    show_alert=True,
                )
            elif st == "queued":
                await cb.answer(f"✅ Entry mil gayi! {LUCKY_WINDOW} sec baad random winners chune jayenge — winner ko DM aayega 🎲", show_alert=True)
            elif st == "duplicate":
                extra = f"\n\n🎁 Code: {r['code']}" if r.get("code") else ""
                await cb.answer("✅ Aap pehle hi claim kar chuke ho!" + extra, show_alert=True)
            elif st == "unverified":
                await cb.answer("Pehle bot start karke Verify karein", url=start_url)
            elif st == "banned":
                await cb.answer("🚫 Aapka account restricted hai.", show_alert=True)
            elif st == "sold_out":
                await cb.answer("😔 Saare codes claim ho chuke hain!", show_alert=True)
            elif st == "late":
                await cb.answer("⏳ Lucky window band ho chuki hai.", show_alert=True)
            elif st == "not_live":
                await cb.answer("⏳ Drop abhi live nahi hua — thoda ruko!", show_alert=True)
            else:
                await cb.answer("❌ Ye drop khatam ho chuka hai.", show_alert=True)
        elif action == "remind":
            r = await remind_core(uid, no)
            st = r["status"]
            if st == "ok":
                await cb.answer("🔔 Reminder set! Drop se pehle aapko DM aayega.", show_alert=True)
            elif st == "already":
                await cb.answer("✅ Reminder pehle se ON hai.", show_alert=True)
            elif st == "unregistered":
                await cb.answer("Pehle bot start karein", url=start_url)
            else:
                await cb.answer("Ye drop ab scheduled nahi hai.", show_alert=True)
        else:
            await cb.answer()
    except TelegramAPIError as e:
        logger.warning("drop callback answer fail: %s", e)


# ---------------------------------------------------------------- admin UI helpers
async def render_drop_menu(cb: CallbackQuery) -> None:
    d = await active_drop()
    if d:
        mode = "🎲 Lucky" if d.get("mode") == "lucky" else "⚡ Fast"
        if d["status"] == "scheduled":
            rem = (d["go_live_at"] - now_utc()).total_seconds()
            info = f"🟡 <b>Scheduled</b> — live hone me <b>{fmt_countdown(rem)}</b>\n🕘 {fmt_ist(d['go_live_at'])}"
            action_btn = btn("🛑 Cancel Drop", f"adm:drop_cancel:{d['_id']}")
        else:
            info = f"🔴 <b>LIVE</b> — claimed <b>{d.get('claimed_count', 0)}/{d['total']}</b>"
            action_btn = btn("🛑 End Now", f"adm:drop_cancel:{d['_id']}")
        text = f"⚡ <b>Free Code Drop #{d['_id']}</b> ({mode})\n\n🎁 {esc(d['label'])}\n📦 Codes: {d['total']}\n{info}"
        rows = [[action_btn], [btn("⬅️ Admin Panel", "adm:home")]]
    else:
        text = (
            "⚡ <b>Free Code Drop</b>\n\nAbhi koi active drop nahi hai.\n\n"
            "<b>Flow:</b> codes → time → mode → (label) → confirm.\n"
            "Bot channel par teaser post karega (pin hoga), time par <b>LIVE post</b> aayega. "
            "Countdown aur claim wall <b>Mini App</b> me chalte hain (channel post edit nahi hoti)."
        )
        rows = [[btn("➕ New Drop", "adm:drop_new")], [btn("⬅️ Admin Panel", "adm:home")]]
    await safe_edit(cb, text, kb(*rows))


async def drop_mode_prompt(codes: list, go_live_at: datetime) -> tuple:
    await set_state(ADMIN_ID, "admin_drop_mode", {"codes": codes, "go_live_at": go_live_at.isoformat()}, ttl_min=30)
    text = (
        f"⏰ Live time: <b>{fmt_ist(go_live_at)}</b>\n\n"
        "Step 3/4 — <b>Mode</b> chunein:\n\n"
        "⚡ <b>Fast</b> — sabse pehle tap karne wale ko code.\n"
        f"🎲 <b>Lucky</b> — {LUCKY_WINDOW} sec me jo JOIN kare unme se random winners (slow phone wale bhi jeet sakte hain)."
    )
    return text, kb(
        [btn("⚡ Fast", "adm:drop_m:fast"), btn("🎲 Lucky", "adm:drop_m:lucky")],
        [btn("❌ Cancel", "adm:home")],
    )


async def drop_label_prompt(data: dict, mode: str) -> tuple:
    await set_state(ADMIN_ID, "admin_drop_label", {**data, "mode": mode}, ttl_min=30)
    text = (
        f"Mode: <b>{'🎲 Lucky' if mode == 'lucky' else '⚡ Fast'}</b>\n\n"
        "Step 4/4 — <b>Prize label</b> bhejein (jaise <code>Google Play ₹50 Redeem Code</code>) ya Skip dabayein:"
    )
    return text, kb([btn("⏭ Skip", "adm:drop_skip")], [btn("❌ Cancel", "adm:home")])


async def drop_confirm_card(data: dict, label: str) -> tuple:
    go_live_at = datetime.fromisoformat(data["go_live_at"])
    mode = data.get("mode", "fast")
    await set_state(
        ADMIN_ID, "admin_drop_confirm",
        {"codes": data["codes"], "go_live_at": data["go_live_at"], "label": label, "mode": mode}, ttl_min=30,
    )
    text = (
        "⚡ <b>Confirm Drop</b>\n\n"
        f"🎁 Label: <b>{esc(label)}</b>\n"
        f"🎮 Mode: <b>{'🎲 Lucky' if mode == 'lucky' else '⚡ Fast'}</b>\n"
        f"📦 Codes (= winners): <b>{len(data['codes'])}</b>\n"
        f"🕘 Live time: <b>{fmt_ist(go_live_at)}</b>\n"
        f"⏳ Live hone me: <b>{fmt_countdown((go_live_at - now_utc()).total_seconds())}</b>\n\n"
        "Confirm karte hi:\n"
        "1️⃣ Channel par <b>teaser post</b> (pin) — notification jayega\n"
        "2️⃣ Time par <b>LIVE post</b> + button aayega\n"
        "3️⃣ Winner ko code (popup + DM)\n"
        "4️⃣ End par ek <b>final post</b> (claim wall). Beech me koi post edit nahi hogi."
    )
    return text, kb([btn("✅ Schedule Drop", "adm:drop_go")], [btn("❌ Cancel", "adm:home")])


# ======================================================================
#  MAIN
# ======================================================================
async def main() -> None:
    global bot
    if not BOT_TOKEN or not MONGO_URI:
        raise SystemExit("❌ BOT_TOKEN aur MONGO_URI environment variables set karna zaroori hai.")

    site_ctx["actions"] = {
        "claim": claim_drop_core, "daily": daily_core, "remind": remind_core,
        "redeem": redeem_reward_core, "settings": settings_core,
    }

    # Mini App + health server pehle start (Koyeb health check pass ho)
    runner = await site_app.start_server(site_ctx, PORT)
    await init_db()

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher()
    dp.include_router(router)
    bot.session.middleware(PacedRequests())   # global pacing + FloodWait retry
    dp.update.outer_middleware(LoadGuard())   # concurrency cap + spam throttle + load shedding

    me = await bot.get_me()
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Bot started: @%s", me.username)
    await resume_drops()
    spawn(monitor_loop())
    spawn(rewards_watch_loop())
    spawn(streak_remind_loop())
    spawn(giveaway_watch_loop())
    spawn(alert_admin("startup", "🔄 <b>Bot start/restart hua</b> ✅\nAgar ye baar-baar aaye to Koyeb logs check karein.", cooldown=120))

    try:  # chat ke menu button se website (Mini App) khulegi
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="📱 App", web_app=WebAppInfo(url=WEBSITE_URL))
        )
    except TelegramAPIError as e:
        logger.warning("Menu button set nahi hua: %s", e)

    try:  # log channel access check
        await bot.get_chat(LOG_CHANNEL_ID)
    except TelegramAPIError as e:
        logger.warning("Log channel access nahi hai — bot ko channel me admin banayein: %s", e)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()
        await mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
