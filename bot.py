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
from site_app import mask_name

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("asb-bot")

IST = timezone(timedelta(hours=5, minutes=30))

# website ke liye shared context (db collections bot start hone par bharte hain)
site_ctx = {
    "db": {},
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


# ---------------------------------------------------------------- keyboards
def main_menu_kb(verified: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if not verified:
        rows.append([btn("🛡 Verify Now (1 tap)", "verify")])
    rows += [
        [btn("📢 Join Channel", url=TASK_CHANNEL_LINK)],
        [btn("❓ Help", "help")],
        [btn("🔑 Enter Code", "enter_code")],
        [btn("🎁 Daily Bonus", "daily"), btn("👥 Refer & Earn", "refer")],
        [btn("🏅 Leaderboard", "top"), btn("🌐 Website", web_app=WEBSITE_URL)],
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
        "🎟 Dosto ko refer karo aur daily bonus lo — <b>extra tickets</b> pao!\n\n"
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
        "🎟 <b>Extra tickets:</b>\n"
        f"• 👥 Refer & Earn: har verified dost = +{REFERRAL_TICKETS} ticket\n"
        "• 🎁 Daily Bonus: streak 3/7/14/30 din par extra tickets\n"
        "Zyada tickets = random winner pick me zyada chance.\n\n"
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
    mongo = AsyncMongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=20000)
    await mongo.admin.command("ping")
    db = mongo[DB_NAME]
    users, entries, states = db["users"], db["entries"], db["states"]
    config, winners = db["config"], db["winners"]
    sponsors, sponsor_joins = db["sponsors"], db["sponsor_joins"]
    await states.create_index("expires_at", expireAfterSeconds=0)  # TTL auto-clean
    await users.create_index("junk")
    await users.create_index([("ref_count", -1)])
    await sponsor_joins.create_index("sid")
    site_ctx["db"].update(
        users=users, entries=entries, config=config, winners=winners, sponsors=sponsors
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


async def deliver(uid: int, sender: Callable[[int], Awaitable]) -> str:
    """Ek message safely bhejta hai. Result: OK / JUNK (blocked etc.) / FAIL."""
    for _ in range(6):
        await limiter.wait()
        try:
            await sender(uid)
            return OK
        except TelegramRetryAfter as e:
            wait = int(e.retry_after) + 1
            logger.warning("FloodWait %ss — queue paused", wait)
            limiter.pause(wait)
        except TelegramForbiddenError:
            return JUNK
        except TelegramBadRequest as e:
            if any(h in str(e).lower() for h in JUNK_HINTS):
                return JUNK
            logger.warning("BadRequest (%s): %s", uid, e)
            return FAIL
        except TelegramNetworkError:
            await asyncio.sleep(2)
        except TelegramAPIError as e:
            logger.warning("TelegramAPIError (%s): %s", uid, e)
            return FAIL
    return FAIL


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
@router.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    if not await is_verified(uid):
        await send_captcha(uid, note="Daily Bonus ke liye pehle verification zaroori hai.\n\n")
        return

    today = today_ist()
    prev = await users.find_one_and_update(
        {"_id": uid, "last_claim": {"$ne": today}}, {"$set": {"last_claim": today}}
    )
    if prev is None:
        u = await users.find_one({"_id": uid}) or {}
        await bot.send_message(
            uid,
            "✅ <b>Aaj ka bonus claim ho chuka hai!</b>\n\n"
            f"🔥 Streak: <b>{u.get('streak', 0)} din</b>\n"
            "⏳ Agla bonus kal (12 AM IST ke baad) milega — streak mat todna!",
            reply_markup=back_kb(),
        )
        return

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    streak = prev.get("streak", 0) + 1 if prev.get("last_claim") == yesterday else 1
    best = max(prev.get("best_streak", 0), streak)
    await users.update_one({"_id": uid}, {"$set": {"streak": streak, "best_streak": best}})

    reward = STREAK_REWARDS.get(streak, 0)
    if reward:
        await add_tickets(uid, reward)
        reward_line = f"🎉 Milestone! <b>+{reward} ticket</b> mil gaya 🎟"
    else:
        reward_line = "Aaj ke liye ticket reward nahi — milestone ka wait karein 😊"
    nxt = next((d for d in sorted(STREAK_REWARDS) if d > streak), None)
    next_line = (
        f"🎯 Agla reward: <b>{nxt} din</b> par (+{STREAK_REWARDS[nxt]} ticket) — {nxt - streak} din baaki"
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
#  MAIN
# ======================================================================
async def main() -> None:
    global bot
    if not BOT_TOKEN or not MONGO_URI:
        raise SystemExit("❌ BOT_TOKEN aur MONGO_URI environment variables set karna zaroori hai.")

    # website + health server pehle start (Koyeb health check pass ho)
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

    try:  # chat ke menu button se website (Mini App) khulegi
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🌐 Website", web_app=WebAppInfo(url=WEBSITE_URL))
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
