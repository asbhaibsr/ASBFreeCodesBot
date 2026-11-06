"""
ASB FreeCodes Bot  —  Telegram Giveaway Bot  (v2)
Stack : Python 3.12 + aiogram 3 + MongoDB Atlas (PyMongo Async) + aiohttp website
Deploy: Koyeb (free web service)  ->  website + health server on $PORT
Bot   : http://t.me/ASBFreeCodesBot

Features: Giveaway codes, lock system, referral tickets, daily streak bonus,
human verification (captcha), sponsor channels, leaderboard, random winner,
promo broadcast (with button), winner proof post, website + Telegram Mini App.
"""

import asyncio
import html
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    User,
    WebAppInfo,
)
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

import site_app
from site_app import mask_name, short_name

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
SEND_RATE = float(os.getenv("SEND_RATE", "20"))                  # messages / second (limit ~30)
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
MINIAPP_LINK = os.getenv("MINIAPP_LINK", "").strip()              # optional: https://t.me/ASBFreeCodesBot/app (BotFather /newapp)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("asb-bot")

IST = timezone(timedelta(hours=5, minutes=30))

# website ke liye shared context (db collections bot start hone par bharte hain)
site_ctx = {
    "db": {},
    "actions": {},
    "bot_token": BOT_TOKEN,
    "public": {
        "bot_username": BOT_USERNAME,
        "bot_link": f"https://t.me/{BOT_USERNAME}",
        "channel_link": TASK_CHANNEL_LINK,
        "support_username": SUPPORT_USERNAME,
        "support_link": SUPPORT_LINK,
    },
}

# ======================================================================
#  GLOBALS (main() me set hote hain)
# ======================================================================
bot: Bot = None  # type: ignore
mongo: AsyncMongoClient = None  # type: ignore
users = entries = states = config = winners = sponsors = sponsor_joins = None
drops = drop_codes = drop_claims = None
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


def app_link() -> str:
    """Channel posts ke liye Mini App link (BotFather direct link ho to wahi, warna bot deep-link)."""
    return MINIAPP_LINK or f"https://t.me/{BOT_USERNAME}?start=drop"


# ---------------------------------------------------------------- keyboards
def main_menu_kb(verified: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if not verified:
        rows.append([btn("🛡 Verify Now (1 tap)", "verify")])
    rows += [
        [btn("📢 Join Channel", url=TASK_CHANNEL_LINK)],
        [btn("❓ Help", "help")],
        [btn("🔑 Enter Code", "enter_code")],
        [btn("📱 Open App", web_app=WEBSITE_URL)],
    ]
    return kb(*rows)


async def user_menu(uid: int) -> InlineKeyboardMarkup:
    return main_menu_kb(await is_verified(uid))


def channel_kb() -> InlineKeyboardMarkup:
    return kb([btn("📢 Join Channel", url=TASK_CHANNEL_LINK)])


def retry_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("📢 Join Channel", url=TASK_CHANNEL_LINK)],
        [btn("🔑 Enter Code", "enter_code")],
    )


def back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Menu", "menu")])


def admin_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("📊 Stats", "adm:stats")],
        [btn("➕ Add Giveaway Code", "adm:add")],
        [btn("🏆 Select Winner", "adm:winner")],
        [btn("📢 Broadcast", "adm:bc")],
        [btn("🧹 Clear Junk", "adm:junk")],
        [btn("⚡ Free Code Drop", "adm:drop")],
        [btn("🤝 Sponsors", "adm:sponsors")],
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
        f"Welcome to <b>{BOT_NAME}</b> 🎁\n\n"
        "💯 Ye bot <b>100% FREE</b> hai — yahan <b>koi paise nahi maange jaate</b>, "
        "aur kabhi maange bhi nahi jayenge.\n\n"
        "📢 Bas hamara channel join karo, task poora karo aur "
        "<b>Redeem Codes jeeto</b> 🎉\n"
        "📱 <b>Open App</b> me Daily Bonus, Refer & Earn, Leaderboard aur ⚡ <b>Free Code Drops</b> milte hain!\n\n"
        "👇 Neeche ke buttons se shuru karein:"
    )


def help_text() -> str:
    return (
        "❓ <b>Help — Kaise use karein?</b>\n\n"
        "1️⃣ <b>Verify Now</b> dabakar 1-tap verification karein (fake accounts rokne ke liye).\n"
        "2️⃣ <b>Join Channel</b> dabakar hamara channel join karein.\n"
        "3️⃣ Channel par diye gaye <b>sahi link</b> se task poora karke <b>code</b> laayein.\n"
        "4️⃣ <b>Enter Code</b> dabakar wo code yahan bhejein — entry confirm ✅\n"
        "5️⃣ Winner ko redeem code seedha DM me milta hai 🏆\n\n"
        "📱 <b>Open App</b> me:\n"
        f"• 👥 Refer & Earn: har verified dost = +{REFERRAL_TICKETS} ticket\n"
        "• 🎁 Daily Bonus: streak 3/7/14/30 din par extra tickets\n"
        "• ⚡ Free Code Drops: time par sabse pehle CLAIM karo\n"
        "• 🎟 Live entries, 🏆 winners aur 🏅 leaderboard\n\n"
        "⚠️ <b>Dhyan rahe:</b>\n"
        f"• {MAX_WRONG_ATTEMPTS} baar se zyada galat code daalne par aap "
        f"<b>{LOCK_HOURS} ghante</b> ke liye lock ho jayenge.\n"
        "• Ek giveaway me sirf <b>ek hi entry</b> hoti hai — spam na karein.\n\n"
        f"🆘 Support: {esc(SUPPORT_USERNAME)}"
    )


def entry_confirmed_text(admin_msg: Optional[str], tickets: int = 1) -> str:
    base = (
        "🎉 <b>Badhai ho! Aapki entry confirm ho gayi hai</b> ✅\n\n"
        f"🎟 Aapke tickets: <b>{tickets}</b>\n"
        "⏳ Ab thoda <b>intezaar</b> karein — winner ka announcement jald hi hoga.\n"
        f"📢 Updates ke liye channel par bane rahein:\n{TASK_CHANNEL_LINK}\n\n"
        "🎁 Winner ko redeem code seedha uske personal DM me bheja jayega.\n"
        "💡 Tickets badhane ke liye <b>Refer & Earn</b> aur <b>Daily Bonus</b> use karein!"
    )
    if admin_msg:
        base += "\n\n━━━━━━━━━━━━━━\n📩 <b>Admin ka message:</b>\n\n" + admin_msg
    return base


def winner_dm_text(code: str) -> str:
    return (
        "🏆 <b>CONGRATULATIONS! Aap aaj ke WINNER ho!</b> 🎉\n\n"
        "🎁 Ye raha aapka <b>Redeem Code</b>:\n\n"
        f"<code>{esc(code)}</code>\n\n"
        "👆 Code par tap karke copy kar lein.\n\n"
        f"📢 Channel: {TASK_CHANNEL_LINK}\n"
        f"🆘 Support: {esc(SUPPORT_USERNAME)}"
    )


def non_winner_text(winner_label: str) -> str:
    return (
        "📢 <b>Aaj ka Winner declare ho gaya!</b>\n\n"
        f"🏆 <b>{winner_label}</b> aaj ka winner ban gaya hai 🎉\n\n"
        "😊 Aap niraash na hon — <b>agli baar zaroor try karein!</b>\n"
        "Hamare channel par bane rahein, kabhi-kabhi yahan <b>free redeem codes</b> "
        "bhi milte rehte hain 🎁\n\n"
        f"🆘 Support ke liye contact karein: {esc(SUPPORT_USERNAME)}"
    )


# ======================================================================
#  DATABASE HELPERS
# ======================================================================
async def init_db() -> None:
    global mongo, users, entries, states, config, winners, sponsors, sponsor_joins
    global drops, drop_codes, drop_claims
    mongo = AsyncMongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=20000)
    await mongo.admin.command("ping")
    db = mongo[DB_NAME]
    users, entries, states = db["users"], db["entries"], db["states"]
    config, winners = db["config"], db["winners"]
    sponsors, sponsor_joins = db["sponsors"], db["sponsor_joins"]
    drops, drop_codes, drop_claims = db["drops"], db["drop_codes"], db["drop_claims"]
    await states.create_index("expires_at", expireAfterSeconds=0)  # TTL auto-clean
    await users.create_index("junk")
    await users.create_index([("ref_count", -1)])
    await sponsor_joins.create_index("sid")
    await drop_codes.create_index([("drop", 1), ("claimed_by", 1)])
    await drop_claims.create_index([("drop", 1), ("rank", 1)])
    await drop_claims.create_index("uid")
    site_ctx["db"].update(
        users=users, entries=entries, config=config, winners=winners, sponsors=sponsors,
        drops=drops, drop_claims=drop_claims,
    )
    logger.info("MongoDB connected ✅  (db=%s)", DB_NAME)


async def touch_user(u: User) -> bool:
    """User ko save/update karo. True return = bilkul naya user."""
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
    return res.upserted_id is not None


async def mark_junk(uid: int) -> None:
    await users.update_one({"_id": uid}, {"$set": {"junk": True, "junk_at": now_utc()}})


async def is_verified(uid: int) -> bool:
    u = await users.find_one({"_id": uid}, {"verified": 1})
    return bool(u and u.get("verified"))


async def set_state(uid: int, name: str, data: Optional[dict] = None, ttl_min: int = 15) -> None:
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


async def non_winner_ids(winner_id: int) -> list:
    if WINNER_NOTIFY == "all":
        cur = users.find({"junk": {"$ne": True}, "_id": {"$ne": winner_id}}, {"_id": 1})
        return [d["_id"] async for d in cur]
    ids = [d["_id"] async for d in entries.find({"_id": {"$ne": winner_id}}, {"_id": 1})]
    if not ids:
        return []
    cur = users.find({"_id": {"$in": ids}, "junk": {"$ne": True}}, {"_id": 1})
    return [d["_id"] async for d in cur]


async def pick_random_winner() -> Optional[dict]:
    """Tickets ke hisaab se weighted random pick (cap: 1 + MAX_BONUS_TICKETS)."""
    docs = [d async for d in entries.find({}, {"_id": 1, "tickets": 1})]
    junk = {d["_id"] async for d in users.find({"junk": True}, {"_id": 1})}
    pool = [d for d in docs if d["_id"] not in junk]
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


limiter = RateLimiter(SEND_RATE)


async def deliver_result(uid: int, sender: Callable[[int], Awaitable]) -> tuple:
    """Ek message safely bhejta hai. Returns (OK/JUNK/FAIL, telegram result)."""
    for _ in range(6):
        await limiter.wait()
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


async def credit_referral(uid: int) -> None:
    """Verified hote hi referrer ko ticket (sirf ek baar)."""
    doc = await users.find_one_and_update(
        {"_id": uid, "ref_by": {"$ne": None}, "ref_credited": {"$ne": True}},
        {"$set": {"ref_credited": True}},
    )
    if not doc:
        return
    ref = doc["ref_by"]
    await users.update_one({"_id": ref}, {"$inc": {"ref_count": 1}})
    await add_tickets(ref, REFERRAL_TICKETS)
    await deliver(
        ref,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>{esc(mask_name(doc.get('name')))}</b> aapke link se join hua aur verify ho gaya!\n"
            f"🎟 Aapko <b>+{REFERRAL_TICKETS} ticket</b> mila.",
        ),
    )


# ======================================================================
#  USER HANDLERS
# ======================================================================
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    uid = m.from_user.id
    is_new = await touch_user(m.from_user)
    await clear_state(uid)

    args = (command.args or "").strip()
    if is_new and args.startswith("ref_"):
        try:
            ref = int(args[4:])
        except ValueError:
            ref = 0
        if ref and ref != uid and await users.find_one({"_id": ref}, {"_id": 1}):
            await users.update_one({"_id": uid}, {"$set": {"ref_by": ref}})

    await m.answer(welcome_text(m.from_user.first_name), reply_markup=await user_menu(uid))
    if args in ("drop", "app"):
        await m.answer(
            "⚡ <b>Free Code Drops</b> aur baaki sab features ke liye App kholein 👇",
            reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)]),
        )


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
    await credit_referral(uid)
    await safe_edit(
        cb,
        "✅ <b>Verification complete!</b>\n\nAb aap Enter Code, Daily Bonus aur Refer & Earn use kar sakte hain 🎉",
        await user_menu(uid),
    )


# ---------------------------------------------------------------- enter code
@router.callback_query(F.data == "enter_code")
async def cb_enter_code(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)

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
    await bot.send_message(uid, "🔑 <b>Apna code ab yahan bhejein</b> 👇\n\n(Cancel karne ke liye /cancel)")


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

    typed = m.text.strip()
    if typed.casefold() == str(gw["code"]).strip().casefold():
        await accept_entry(m, gw)
    else:
        await wrong_code(m)


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
    text = entry_confirmed_text(gw.get("admin_message"), tickets)
    if len(text) <= 4000:
        await m.answer(text, reply_markup=await user_menu(u.id))
    else:  # bahut lamba ho to 2 parts me
        await m.answer(entry_confirmed_text(None, tickets), reply_markup=await user_menu(u.id))
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


async def wrong_code(m: Message) -> None:
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
        "Channel ke <b>sahi link</b> se code laayein aur dobara try karein.\n"
        f"{warn}",
        reply_markup=retry_kb(),
    )


# ---------------------------------------------------------------- daily bonus
async def daily_core(uid: int) -> dict:
    """Daily bonus claim — bot aur Mini App dono yahi use karte hain."""
    if not await is_verified(uid):
        return {"status": "unverified"}
    today = today_ist()
    prev = await users.find_one_and_update(
        {"_id": uid, "last_claim": {"$ne": today}}, {"$set": {"last_claim": today}}
    )
    if prev is None:
        u = await users.find_one({"_id": uid}) or {}
        return {"status": "already", "streak": u.get("streak", 0), "best": u.get("best_streak", 0)}

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    streak = prev.get("streak", 0) + 1 if prev.get("last_claim") == yesterday else 1
    best = max(prev.get("best_streak", 0), streak)
    await users.update_one({"_id": uid}, {"$set": {"streak": streak, "best_streak": best}})
    reward = STREAK_REWARDS.get(streak, 0)
    if reward:
        await add_tickets(uid, reward)
    nxt = next((d for d in sorted(STREAK_REWARDS) if d > streak), None)
    return {
        "status": "ok", "streak": streak, "best": best, "reward": reward,
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
    await bot.send_message(
        uid,
        "🎁 <b>Daily Bonus Claimed!</b>\n\n"
        f"🔥 Streak: <b>{streak} din</b> (best: {best})\n"
        f"{reward_line}\n{next_line}\n\n"
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
        gw = await get_giveaway()
        if gw:
            status = "🔄 Winner process chal raha hai" if gw.get("closing") else "🟢 Active"
            gw_line = f"{status}\n🔑 Code: <code>{esc(gw['code'])}</code>"
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
            f"🏆 Winners Declared: <b>{n_winners}</b>\n\n"
            f"🎁 <b>Giveaway:</b> {gw_line}",
            admin_back_kb(),
        )

    # ---------------------------------------------------------- add code
    elif action == "add":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi winner/broadcast process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_add_code")
        await safe_edit(
            cb,
            "➕ <b>Add Giveaway Code</b>\n\n"
            "Step 1/2 — Naya <b>giveaway code</b> bhejein "
            "(jo users ko sahi link se milega):",
            admin_cancel_kb(),
        )

    # ---------------------------------------------------------- winner
    elif action == "winner":
        if broadcast_lock.locked():
            await safe_edit(cb, "⏳ Abhi ek process chal raha hai. Khatam hone par try karein.", admin_back_kb())
            return
        await set_state(ADMIN_ID, "admin_win_id")
        n = await entries.count_documents({})
        await safe_edit(
            cb,
            "🏆 <b>Select Winner</b>\n\n"
            f"Current entries: <b>{n}</b>\n\n"
            "Step 1/2 — Winner ki <b>Telegram ID</b> bhejein (sirf number),\n"
            "ya neeche <b>Random Pick</b> dabayein (tickets ke hisaab se weighted):",
            kb(
                [btn("🎲 Random Pick", "adm:win_rand")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

    elif action == "win_rand":
        pick = await pick_random_winner()
        if not pick:
            await safe_edit(cb, "⚠️ Koi entry nahi mili jisme se random pick ho sake.", admin_back_kb())
            return
        u = await users.find_one({"_id": pick["_id"]}) or {}
        await set_state(ADMIN_ID, "admin_win_code", {"winner_id": pick["_id"], "random": True})
        await safe_edit(
            cb,
            "🎲 <b>Random Pick</b>\n\n"
            f"👤 {esc(u.get('name'))}  (<code>{pick['_id']}</code>)\n"
            f"🎟 Tickets: <b>{pick.get('tickets', 1)}</b>\n\n"
            "Step 2/2 — Ab <b>Redeem Code</b> bhejein jo winner ko DM me jayega:",
            admin_cancel_kb(),
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
        spawn(declare_winner(int(data["winner_id"]), str(data["code"])))

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
        await safe_edit(cb, f"✅ <b>{len(ids)}</b> junk users permanently remove ho gaye.", admin_back_kb())

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
            "Step 1/3 — <b>Redeem codes</b> bhejein, <b>har line me ek code</b>.\n"
            f"Jitni lines, utne log claim kar payenge (max {DROP_MAX_CODES}).",
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
        text, markup = await drop_label_prompt(st["data"]["codes"], now_utc() + timedelta(minutes=minutes))
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
        no = await create_drop(list(data["codes"]), go_live_at, data["label"])
        if no is None:
            await safe_edit(
                cb,
                "❌ Teaser channel par post nahi ho paya. Bot ko task channel me <b>Admin</b> banayein "
                "(post + edit + pin permission) aur dobara try karein.",
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
async def handle_admin_state(m: Message, st: dict) -> None:
    name, data = st["name"], st.get("data", {})

    # ---- Add Giveaway Code: step 1 (code)
    if name == "admin_add_code":
        if not m.text or not m.text.strip():
            await m.answer("⚠️ Code text me bhejein.")
            return
        code = m.text.strip()
        await set_state(ADMIN_ID, "admin_add_msg", {"code": code})
        await m.answer(
            f"✅ Code mil gaya: <code>{esc(code)}</code>\n\n"
            "Step 2/2 — Ab <b>custom admin message</b> bhejein jo sahi code daalne par "
            "user ko DM me jayega (bold/italic/link formatting chalegi):",
            reply_markup=admin_cancel_kb(),
        )

    # ---- Add Giveaway Code: step 2 (admin message)
    elif name == "admin_add_msg":
        if not m.text:
            await m.answer("⚠️ Message text me bhejein.")
            return
        if broadcast_lock.locked():
            await m.answer("⏳ Abhi ek process chal raha hai, thodi der baad try karein.")
            return
        await config.replace_one(
            {"_id": "giveaway"},
            {
                "_id": "giveaway",
                "code": data["code"],
                "admin_message": m.html_text,
                "created_at": now_utc(),
                "closing": False,
            },
            upsert=True,
        )
        await clear_state(ADMIN_ID)
        n = await entries.count_documents({})
        await m.answer(
            "✅ <b>Giveaway set ho gaya!</b>\n\n"
            f"🔑 Code: <code>{esc(data['code'])}</code>\n"
            f"🎟 Maujooda entries: <b>{n}</b>\n\n"
            "📩 <b>Admin message preview:</b>\n\n" + m.html_text,
            reply_markup=admin_back_kb(),
        )

    # ---- Select Winner: step 1 (ID)
    elif name == "admin_win_id":
        try:
            wid = int((m.text or "").strip())
        except ValueError:
            await m.answer("⚠️ Sirf number wali Telegram ID bhejein.")
            return
        u = await users.find_one({"_id": wid})
        if not u:
            await m.answer(
                "⚠️ Ye ID bot ke database me nahi mili. User ko pehle bot par /start karna hoga.\n"
                "Sahi ID bhejein:"
            )
            return
        await set_state(ADMIN_ID, "admin_win_code", {"winner_id": wid})
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
        wid = int(data["winner_id"])
        u = await users.find_one({"_id": wid}) or {}
        entry = await entries.find_one({"_id": wid})
        n_targets = len(await non_winner_ids(wid))
        gw = await get_giveaway()
        await set_state(ADMIN_ID, "admin_win_confirm", {"winner_id": wid, "code": code})
        entry_line = f"✅ Haan — tickets: {entry.get('tickets', 1)}" if entry else "❌ Nahi"
        rand_line = "🎲 Random pick se chuna gaya\n" if data.get("random") else ""
        await m.answer(
            "🏆 <b>Confirm Winner</b>\n\n"
            f"👤 {esc(u.get('name'))}  (<code>{wid}</code>)\n"
            f"🎟 Entry daali thi: {entry_line}\n"
            f"{rand_line}"
            f"🎁 Redeem Code: <code>{esc(code)}</code>\n"
            f"📨 Non-winners ko message jayega: <b>{n_targets}</b>\n"
            f"🔑 Purana giveaway code delete hoga: {'✅' if gw else '— (set nahi hai)'}\n\n"
            "Confirm karne par:\n"
            "1️⃣ Code winner ke DM me jayega\n"
            "2️⃣ Baaki sabko winner-announcement jayega\n"
            "3️⃣ Purana code + sabhi entries delete ho jayengi\n"
            "4️⃣ Channel par winner proof post hoga\n\n"
            "<b>Ye action undo nahi hota.</b>",
            reply_markup=kb(
                [btn("✅ Confirm & Declare", "adm:win_go")],
                [btn("❌ Cancel", "adm:home")],
            ),
        )

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
            "Step 2/3 — Drop <b>kab live</b> hoga? Button dabayein ya type karein:\n"
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
        text, markup = await drop_label_prompt(data["codes"], t)
        await m.answer(text, reply_markup=markup)

    # ---- Free Code Drop: step 3 (label)
    elif name == "admin_drop_label":
        label = (m.text or "").strip()
        if not label or len(label) > 60:
            await m.answer("⚠️ Label 1-60 characters ka text hona chahiye, ya Skip dabayein.")
            return
        text, markup = await drop_confirm_card(data, label)
        await m.answer(text, reply_markup=markup)

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
async def declare_winner(winner_id: int, redeem_code: str) -> None:
    async with broadcast_lock:
        try:
            await _declare_winner(winner_id, redeem_code)
        except Exception:
            logger.exception("declare_winner failed")
            await config.update_one({"_id": "giveaway"}, {"$set": {"closing": False}})
            await notify_admin(
                "❌ Winner process me error aaya. Giveaway wapas khol diya gaya hai.\n"
                "Agar winner ko code mil chuka ho to dobara declare karne se pehle check kar lein."
            )


async def _declare_winner(winner_id: int, redeem_code: str) -> None:
    wu = await users.find_one({"_id": winner_id}) or {}
    wname = wu.get("name") or "Ek user"
    wuser = wu.get("username")
    winner_label = esc(wname) + (f" (@{esc(wuser)})" if wuser else "")

    # giveaway band karo (naye entries na aayein)
    await config.update_one({"_id": "giveaway"}, {"$set": {"closing": True}})

    # 1) redeem code -> winner ke DM
    res = await deliver(
        winner_id,
        lambda uid: bot.send_message(uid, winner_dm_text(redeem_code), reply_markup=channel_kb()),
    )
    if res != OK:
        await config.update_one({"_id": "giveaway"}, {"$set": {"closing": False}})
        if res == JUNK:
            await mark_junk(winner_id)
        await notify_admin(
            "❌ <b>Winner ko DM nahi ja paya</b> (user ne bot block kiya ya start nahi kiya).\n"
            "Kuch bhi delete nahi hua. Dusra winner chunein."
        )
        return

    # 2) baaki sabko (non-winners) announcement
    entries_count = await entries.count_documents({})
    targets = await non_winner_ids(winner_id)
    status = await bot.send_message(ADMIN_ID, f"📨 Non-winners ko message bhej raha hoon… 0/{len(targets)}")
    stats = await run_broadcast(
        targets,
        lambda uid: bot.send_message(uid, non_winner_text(winner_label), reply_markup=channel_kb()),
        make_progress(status, "📨 Non-winners broadcast"),
    )

    # 3) cleanup: purana code + sabhi entries delete (naye giveaway ke liye reset)
    giveaway_no = await winners.count_documents({}) + 1
    declared_at = now_utc()
    await config.delete_one({"_id": "giveaway"})
    deleted = (await entries.delete_many({})).deleted_count
    await users.update_many({}, {"$set": {"wrong_count": 0, "locked_until": None}})
    await winners.insert_one(
        {
            "winner_id": winner_id,
            "name": wname,
            "username": wuser,
            "giveaway_no": giveaway_no,
            "declared_at": declared_at,
            "entries_count": entries_count,
            "entries_deleted": deleted,
            "notified": stats,
        }
    )

    # 4) winner proof -> task channel par
    proof = "— (off)"
    if POST_WINNER_TO_CHANNEL:
        pres = await deliver(
            TASK_CHANNEL_ID,
            lambda cid: bot.send_message(
                cid,
                f"🏆 <b>Giveaway #{giveaway_no} — Winner Declared!</b>\n\n"
                f"👤 Winner: <b>{esc(mask_name(wname))}</b>\n"
                f"🎟 Total entries: <b>{entries_count}</b>\n"
                f"🕒 {fmt_ist(declared_at)}\n\n"
                "✅ Redeem code winner ke DM me bhej diya gaya hai.\n"
                f"🤖 Agle giveaway ke liye: https://t.me/{BOT_USERNAME}",
            ),
        )
        proof = "✅ Post ho gaya" if pres == OK else "⚠️ Post nahi hua (bot ko channel me admin banayein)"

    # 5) reports
    report = (
        "✅ <b>Winner declare ho gaya!</b>\n\n"
        f"🏆 Winner: {winner_label}  (<code>{winner_id}</code>)\n"
        f"🎁 Giveaway #: <b>{giveaway_no}</b>\n"
        f"📨 Notified: <b>{stats['sent']}</b> / {stats['total']}\n"
        f"🚫 Blocked (Junk me gaye): <b>{stats['junk']}</b>\n"
        f"⚠️ Failed: <b>{stats['failed']}</b>\n"
        f"📣 Channel proof post: {proof}\n"
        f"🧹 Purana code + <b>{deleted}</b> entries delete ho gayi.\n\n"
        "Naye giveaway ke liye <b>Add Giveaway Code</b> use karein."
    )
    await notify_admin(report, admin_back_kb())
    await safe_log(
        "🏆 <b>Winner Declared</b>\n\n"
        f"👤 {winner_label}\n🆔 <code>{winner_id}</code>\n"
        f"🎁 Giveaway #{giveaway_no}  |  🎟 Entries: {entries_count}\n"
        f"📨 Notified: {stats['sent']}/{stats['total']}  |  🚫 Junk: {stats['junk']}\n"
        f"🕒 {fmt_ist(declared_at)}"
    )


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
#  ⚡ FREE CODE DROPS
# ======================================================================
DEFAULT_DROP_LABEL = "Google Play Redeem Code"
MEDALS = ["🥇", "🥈", "🥉"]


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


def wall_lines(wall: list, limit: int = 30) -> str:
    lines = []
    for w in wall[:limit]:
        r = w.get("rank", 0)
        tag = MEDALS[r - 1] if 1 <= r <= 3 else f"{r}."
        lines.append(f"{tag} <b>{esc(short_name(w.get('name')))}</b> — {sec_text(w.get('ms', 0))}")
    return "\n".join(lines)


def render_teaser(drop: dict, remaining: float) -> str:
    return (
        "⚡ <b>FREE REDEEM CODE DROP</b> ⚡\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"👥 Sirf <b>{drop['total']}</b> logon ke liye!\n"
        f"🕘 Live hoga: <b>{fmt_drop_time(drop['go_live_at'])}</b> (IST)\n\n"
        "📲 <b>Abhi Google Play Store kholkar Redeem screen par ready baith jao!</b>\n"
        "Code aate hi sabse pehle CLAIM karne walon ko milega.\n\n"
        f"⏳ Countdown: <b>{fmt_countdown(remaining)}</b>\n\n"
        "🔔 Reminder ke liye neeche button dabayein."
    )


def render_live(drop: dict, wall: list) -> str:
    body = wall_lines(wall) if wall else "Abhi koi claim nahi — pehle aap bano! 🚀"
    return (
        "🔥 <b>DROP LIVE — CLAIM NOW!</b> 🔥\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"📦 Claimed: <b>{drop.get('claimed_count', 0)}/{drop['total']}</b>\n\n"
        "👇 <b>CLAIM NOW</b> dabao — sabse pehle wale ko code milega!\n\n"
        f"🏁 <b>Claim Wall</b>\n{body}"
    )


def render_done(drop: dict, wall: list, reason: str) -> str:
    title = {
        "sold_out": "✅ <b>DROP COMPLETE</b> ✅",
        "timeout": "⏰ <b>DROP KHATAM</b> ⏰",
    }.get(reason, "🛑 <b>DROP KHATAM</b> 🛑")
    extra = ""
    if reason == "sold_out" and wall:
        extra = f"\n⚡ Saare codes sirf <b>{sec_text(wall[-1].get('ms', 0))}</b> me claim ho gaye!"
    body = wall_lines(wall) if wall else "Kisi ne claim nahi kiya 😔"
    return (
        f"{title}\n\n"
        f"🎁 <b>{esc(drop['label'])}</b>\n"
        f"📦 Claimed: <b>{drop.get('claimed_count', 0)}/{drop['total']}</b>{extra}\n\n"
        f"🏁 <b>Claim Wall</b>\n{body}\n\n"
        "🔔 Agla drop miss mat karna — channel notification ON rakho!"
    )


def teaser_kb(no: int) -> InlineKeyboardMarkup:
    return kb([btn("🔔 Remind Me", f"drop:remind:{no}")], [btn("📱 Open App", url=app_link())])


def live_kb(no: int) -> InlineKeyboardMarkup:
    return kb([btn("🎁 CLAIM NOW", f"drop:claim:{no}")], [btn("📱 Open App", url=app_link())])


def done_kb() -> InlineKeyboardMarkup:
    return kb([btn("📱 Open App", url=app_link())])


# ---------------------------------------------------------------- channel helpers
async def edit_post(msg_id: int, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> bool:
    res = await deliver(
        TASK_CHANNEL_ID,
        lambda cid: bot.edit_message_text(text, chat_id=cid, message_id=msg_id, reply_markup=markup),
    )
    return res == OK


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
async def create_drop(codes: list, go_live_at: datetime, label: str) -> Optional[int]:
    ctr = await config.find_one_and_update(
        {"_id": "drop_counter"}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    no = int(ctr["n"])
    drop = {
        "_id": no,
        "status": "scheduled",
        "label": label,
        "total": len(codes),
        "claimed_count": 0,
        "go_live_at": go_live_at,
        "created_at": now_utc(),
        "reminders": [],
        "reminded": False,
        "teaser_msg_id": None,
        "live_msg_id": None,
    }
    await drops.insert_one(drop)
    for c in codes:
        await drop_codes.insert_one({"drop": no, "code": c, "claimed_by": None})

    remaining = (go_live_at - now_utc()).total_seconds()
    status, msg = await deliver_result(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, render_teaser(drop, remaining), reply_markup=teaser_kb(no)),
    )
    if status != OK:  # channel post nahi gayi -> sab rollback
        await drops.delete_one({"_id": no})
        await drop_codes.delete_many({"drop": no})
        return None
    await drops.update_one({"_id": no}, {"$set": {"teaser_msg_id": msg.message_id}})
    await pin_post(msg.message_id)
    start_drop_runner(no)
    return no


def start_drop_runner(no: int) -> None:
    if no in drop_tasks and not drop_tasks[no].done():
        return
    task = asyncio.create_task(run_drop(no))
    drop_tasks[no] = task
    task.add_done_callback(lambda _t, n=no: drop_tasks.pop(n, None))


async def resume_drops() -> None:
    """Restart ke baad scheduled/live drops dobara chalu."""
    async for d in drops.find({"status": {"$in": ["scheduled", "live"]}}):
        logger.info("Resuming drop #%s (%s)", d["_id"], d["status"])
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
    await drops.update_one({"_id": no}, {"$set": {"status": "live", "live_at": now}})
    live_doc = {**drop, "status": "live", "claimed_count": 0}
    status, msg = await deliver_result(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(cid, render_live(live_doc, []), reply_markup=live_kb(no)),
    )
    if status != OK:
        await drops.update_one({"_id": no}, {"$set": {"status": "cancelled"}})
        await notify_admin(
            f"❌ Drop #{no}: live post channel par nahi ja payi (bot ko channel me admin banayein).\n"
            "Drop cancel ho gaya — codes DB me safe hain."
        )
        return False
    await drops.update_one({"_id": no}, {"$set": {"live_msg_id": msg.message_id, "live_at": now_utc()}})
    if drop.get("teaser_msg_id"):
        await edit_post(
            drop["teaser_msg_id"],
            "⚡ <b>DROP LIVE ho gaya!</b> 🔥\n\n👇 Niche wali post par <b>CLAIM NOW</b> dabao!",
            kb([btn("🎁 Live Post par jao", url=post_link(msg.message_id))]),
        )
        await unpin_post(drop["teaser_msg_id"])
    await pin_post(msg.message_id)
    spawn(
        dm_subscribers(
            no,
            f"🔥 <b>DROP #{no} LIVE HO GAYA!</b>\n\nAbhi CLAIM karo — sabse pehle wale ko code milega!",
            kb([btn("🎁 App me Claim karo", web_app=WEBSITE_URL)], [btn("📢 Channel Post", url=post_link(msg.message_id))]),
        )
    )
    return True


async def _run_drop(no: int) -> None:
    drop = await drops.find_one({"_id": no})
    if not drop:
        return

    # ---- phase 1: teaser countdown
    last_edit = -1e9
    while drop and drop["status"] == "scheduled":
        remaining = (drop["go_live_at"] - now_utc()).total_seconds()
        if remaining <= 0:
            break
        if remaining <= 60 and not drop.get("reminded"):
            await drops.update_one({"_id": no}, {"$set": {"reminded": True}})
            drop["reminded"] = True
            tl = post_link(drop["teaser_msg_id"]) if drop.get("teaser_msg_id") else TASK_CHANNEL_LINK
            spawn(
                dm_subscribers(
                    no,
                    f"⏰ <b>Drop #{no} sirf 1 minute me live hoga!</b>\n\n"
                    "📲 Abhi Google Play Store ka <b>Redeem screen</b> kholkar ready ho jao!",
                    kb([btn("📱 App kholo", web_app=WEBSITE_URL)], [btn("📢 Channel Post", url=tl)]),
                )
            )
        interval = 60 if remaining > 300 else 20 if remaining > 60 else 5
        if time.monotonic() - last_edit >= interval and drop.get("teaser_msg_id"):
            last_edit = time.monotonic()
            await edit_post(drop["teaser_msg_id"], render_teaser(drop, remaining), teaser_kb(no))
        tick = 5.0 if remaining > 70 else 1.0
        await asyncio.sleep(max(min(tick, remaining), 0.02))
        drop = await drops.find_one({"_id": no})

    if not drop:
        return
    if drop["status"] == "scheduled":
        if not await go_live(no, drop):
            return
    elif drop["status"] != "live":
        return  # cancelled

    # ---- phase 2: live — claims ginte raho, post update karte raho
    last_edit, last_count = time.monotonic(), 0
    while True:
        await asyncio.sleep(0.5)
        d = await drops.find_one({"_id": no})
        if not d or d["status"] != "live":
            return
        if d.get("claimed_count", 0) >= d["total"]:
            await finish_drop(no, "sold_out")
            return
        if d.get("live_at") and (now_utc() - d["live_at"]).total_seconds() > DROP_TIMEOUT_MIN * 60:
            await finish_drop(no, "timeout")
            return
        count = d.get("claimed_count", 0)
        if count != last_count and d.get("live_msg_id") and time.monotonic() - last_edit >= 2.0:
            last_edit, last_count = time.monotonic(), count
            await edit_post(d["live_msg_id"], render_live(d, await get_wall(no)), live_kb(no))


async def finish_drop(no: int, reason: str) -> None:
    d = await drops.find_one_and_update(
        {"_id": no, "status": "live"},
        {"$set": {"status": "ended", "ended_at": now_utc(), "end_reason": reason}},
        return_document=ReturnDocument.AFTER,
    )
    if not d:
        return
    await asyncio.sleep(1.0)  # in-flight claims settle ho jayein
    d = await drops.find_one({"_id": no}) or d
    wall = await get_wall(no)
    left = [c["code"] async for c in drop_codes.find({"drop": no, "claimed_by": None})]
    if d.get("live_msg_id"):
        await edit_post(d["live_msg_id"], render_done(d, wall, reason), done_kb())
        await unpin_post(d["live_msg_id"])

    reason_txt = {"sold_out": "sab codes claim ho gaye ✅", "timeout": "time khatam ⏰"}.get(reason, "admin ne end kiya 🛑")
    lines = "\n".join(
        f"{w['rank']}. {esc(short_name(w.get('name')))} (<code>{w['uid']}</code>) — {sec_text(w.get('ms', 0))}"
        for w in wall[:15]
    ) or "— koi claim nahi"
    more = f"\n… aur {len(wall) - 15}" if len(wall) > 15 else ""
    left_txt = ""
    if left:
        shown = "\n".join(f"<code>{esc(c)}</code>" for c in left[:20])
        left_txt = f"\n\n🔓 <b>Bache hue codes</b> ({len(left)}) — dobara use kar sakte ho:\n{shown}"
    await notify_admin(
        f"🏁 <b>Drop #{no} khatam</b> — {reason_txt}\n\n"
        f"📦 Claimed: <b>{d.get('claimed_count', 0)}/{d['total']}</b>\n\n"
        f"<b>Claim list</b>\n{lines}{more}{left_txt}",
        admin_back_kb(),
    )
    await safe_log(
        f"⚡ <b>Drop #{no} Ended</b> — {d.get('claimed_count', 0)}/{d['total']} claimed ({reason})"
    )


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
        if d.get("teaser_msg_id"):
            await edit_post(d["teaser_msg_id"], "❌ <b>Ye drop cancel ho gaya.</b>\n\nAgle drop ke liye bane rahein 🔔", done_kb())
            await unpin_post(d["teaser_msg_id"])
        return f"✅ Drop #{no} cancel ho gaya. Codes DB me safe hain (dobara naya drop banakar use kar sakte ho)."
    if d["status"] == "live":
        await finish_drop(no, "admin")
        return f"✅ Drop #{no} end kar diya. Report neeche aayegi."
    return "Ye drop pehle hi khatam ho chuka hai."


# ---------------------------------------------------------------- claim / remind (bot + Mini App)
async def claim_drop_core(uid: int, no: int) -> dict:
    drop = await drops.find_one({"_id": no})
    if not drop:
        return {"status": "not_found"}
    if drop["status"] == "scheduled":
        return {"status": "not_live"}
    if drop["status"] != "live":
        return {"status": "ended"}
    u = await users.find_one({"_id": uid})
    if not u or not u.get("verified"):
        return {"status": "unverified"}

    claim_id = f"{no}:{uid}"
    try:
        await drop_claims.insert_one(
            {"_id": claim_id, "drop": no, "uid": uid, "name": u.get("name"), "rank": None, "at": now_utc()}
        )
    except DuplicateKeyError:
        prev = await drop_claims.find_one({"_id": claim_id}) or {}
        return {"status": "duplicate", "rank": prev.get("rank"), "ms": prev.get("ms", 0), "code": prev.get("code")}

    # atomic: ek code ek hi user ko
    code_doc = await drop_codes.find_one_and_update(
        {"drop": no, "claimed_by": None}, {"$set": {"claimed_by": uid, "claimed_at": now_utc()}}
    )
    if not code_doc:
        await drop_claims.delete_one({"_id": claim_id})
        return {"status": "sold_out"}

    d = await drops.find_one_and_update(
        {"_id": no}, {"$inc": {"claimed_count": 1}}, return_document=ReturnDocument.AFTER
    )
    rank = int(d["claimed_count"])
    ms = max(int((now_utc() - (d.get("live_at") or now_utc())).total_seconds() * 1000), 1)
    code = code_doc["code"]
    await drop_claims.update_one({"_id": claim_id}, {"$set": {"rank": rank, "ms": ms, "code": code}})
    spawn(after_claim(uid, u.get("name"), no, rank, ms, code))
    return {"status": "ok", "rank": rank, "ms": ms, "code": code}


async def after_claim(uid: int, name: Optional[str], no: int, rank: int, ms: int, code: str) -> None:
    await deliver(
        uid,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>Mubarak ho! Drop #{no} claim ho gaya!</b>\n\n"
            f"🏅 Rank: <b>#{rank}</b>   ⚡ {sec_text(ms)}\n\n"
            f"🎁 Aapka Redeem Code:\n<code>{esc(code)}</code>\n\n"
            "👆 Tap karke copy karein aur <b>turant Google Play Store me redeem</b> karein!",
            reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)]),
        ),
    )
    await safe_log(
        f"⚡ <b>Drop #{no} Claim</b>\n\n👤 {esc(name)}  (<code>{uid}</code>)\n"
        f"🏅 Rank #{rank}  ⚡ {sec_text(ms)}\n🎁 Code: <code>{esc(code)}</code>"
    )


async def remind_core(uid: int, no: int) -> dict:
    if not await users.find_one({"_id": uid}, {"_id": 1}):
        return {"status": "unregistered"}
    d = await drops.find_one({"_id": no})
    if not d or d["status"] != "scheduled":
        return {"status": "closed"}
    res = await drops.update_one({"_id": no}, {"$addToSet": {"reminders": uid}})
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
            elif st == "duplicate":
                extra = f"\n\n🎁 Code: {r['code']}" if r.get("code") else ""
                await cb.answer("✅ Aap pehle hi claim kar chuke ho!" + extra, show_alert=True)
            elif st == "unverified":
                await cb.answer("Pehle bot start karke Verify karein", url=start_url)
            elif st == "sold_out":
                await cb.answer("😔 Saare codes claim ho chuke hain!", show_alert=True)
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
        if d["status"] == "scheduled":
            rem = (d["go_live_at"] - now_utc()).total_seconds()
            info = f"🟡 <b>Scheduled</b> — live hone me <b>{fmt_countdown(rem)}</b>\n🕘 {fmt_ist(d['go_live_at'])}"
            action_btn = btn("🛑 Cancel Drop", f"adm:drop_cancel:{d['_id']}")
        else:
            info = f"🔴 <b>LIVE</b> — claimed <b>{d.get('claimed_count', 0)}/{d['total']}</b>"
            action_btn = btn("🛑 End Now", f"adm:drop_cancel:{d['_id']}")
        text = f"⚡ <b>Free Code Drop #{d['_id']}</b>\n\n🎁 {esc(d['label'])}\n📦 Codes: {d['total']}\n{info}"
        rows = [[action_btn], [btn("⬅️ Admin Panel", "adm:home")]]
    else:
        text = (
            "⚡ <b>Free Code Drop</b>\n\nAbhi koi active drop nahi hai.\n\n"
            "<b>Flow:</b> codes → time → (label) → confirm.\n"
            "Bot channel par teaser post karega (pin hoga), time par <b>LIVE post</b> aayega, "
            "aur sabse pehle CLAIM karne wale ko code milega. Claim wall khud channel par dikhega."
        )
        rows = [[btn("➕ New Drop", "adm:drop_new")], [btn("⬅️ Admin Panel", "adm:home")]]
    await safe_edit(cb, text, kb(*rows))


async def drop_label_prompt(codes: list, go_live_at: datetime) -> tuple:
    await set_state(ADMIN_ID, "admin_drop_label", {"codes": codes, "go_live_at": go_live_at.isoformat()})
    text = (
        f"⏰ Live time: <b>{fmt_ist(go_live_at)}</b>\n\n"
        "Step 3/3 — <b>Prize label</b> bhejein (jaise <code>Google Play ₹50 Redeem Code</code>) "
        "ya Skip dabayein:"
    )
    return text, kb([btn("⏭ Skip", "adm:drop_skip")], [btn("❌ Cancel", "adm:home")])


async def drop_confirm_card(data: dict, label: str) -> tuple:
    go_live_at = datetime.fromisoformat(data["go_live_at"])
    await set_state(
        ADMIN_ID, "admin_drop_confirm", {"codes": data["codes"], "go_live_at": data["go_live_at"], "label": label}
    )
    text = (
        "⚡ <b>Confirm Drop</b>\n\n"
        f"🎁 Label: <b>{esc(label)}</b>\n"
        f"📦 Codes (= claimers): <b>{len(data['codes'])}</b>\n"
        f"🕘 Live time: <b>{fmt_ist(go_live_at)}</b>\n"
        f"⏳ Live hone me: <b>{fmt_countdown((go_live_at - now_utc()).total_seconds())}</b>\n\n"
        "Confirm karte hi:\n"
        "1️⃣ Channel par <b>teaser post</b> hogi (pin) — notification jayega\n"
        "2️⃣ Time par <b>LIVE post</b> + CLAIM button aayega\n"
        "3️⃣ Sabse pehle claim karne walon ko code (popup + DM)\n"
        "4️⃣ Claim wall khud channel par update hogi"
    )
    return text, kb([btn("✅ Schedule Drop", "adm:drop_go")], [btn("❌ Cancel", "adm:home")])



# ======================================================================
#  MAIN
# ======================================================================
async def main() -> None:
    global bot
    if not BOT_TOKEN or not MONGO_URI:
        raise SystemExit("❌ BOT_TOKEN aur MONGO_URI environment variables set karna zaroori hai.")

    site_ctx["actions"] = {"claim": claim_drop_core, "daily": daily_core, "remind": remind_core}

    # Mini App + health server pehle start (Koyeb health check pass ho)
    runner = await site_app.start_server(site_ctx, PORT)
    await init_db()

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Bot started: @%s", me.username)
    await resume_drops()

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
