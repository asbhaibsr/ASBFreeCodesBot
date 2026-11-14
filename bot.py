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
v3  : wallet (refer = Rs 0.20), invite code (= Telegram ID), withdraw (UPI/bank/mobile) with
      user confirm, weekly leaderboard prizes, small-caps menu, new-user log (batched),
      blocked-winner auto replacement, result post with participants (quote style).
v4  : paise ka ledger (har credit/debit ka record), invite-code anti-fraud (48h, attempts limit,
      confirm), refer 3 din baad pakka (pending), refer tracker, multi-admin withdraw, proof post,
      FAQ + problem report, simple Hinglish messages, welcome image + video links (admin se set),
      Mini App 5 tab me, admin: /balance /adjust /refs /dash.
"""

import asyncio
import html
import inspect
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
    ChatMemberUpdated,
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
from pymongo.errors import ConfigurationError, DuplicateKeyError, OperationFailure

import site_app
from site_app import (
    disp_name, fmt_when, friend_rows, gw_links, link_label, link_text, mask_name, ref_pending, short_name,
    week_end_dt, week_key, week_start_ist,
)

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

# ---- v3: wallet / invite / weekly leaderboard
REF_REWARD_PAISE = int(round(float(os.getenv("REF_REWARD_RS", "0.20")) * 100))      # har valid refer par (paise me)
MIN_WITHDRAW_PAISE = int(round(float(os.getenv("MIN_WITHDRAW_RS", "50")) * 100))     # kam se kam withdraw
LB_PRIZES_RS = [int(x) for x in os.getenv("LB_PRIZES_RS", "15,10,5").split(",") if x.strip()]  # weekly top 3
LB_MIN_REFS = int(os.getenv("LB_MIN_REFS", "10"))                                    # prize ke liye us hafte ke min refers
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+DeGNFAXMuIg0MTk9")
RESULT_MAX_NAMES = int(os.getenv("RESULT_MAX_NAMES", "300"))                          # channel result me max participant naam
RESULT_STORE_NAMES = int(os.getenv("RESULT_STORE_NAMES", "1500"))                     # DB me max participant naam
REPLACE_TRIES = int(os.getenv("REPLACE_TRIES", "8"))                                  # blocked winner ke badle max naye try

# ---- v4: ledger / anti-fraud / trust
def _id_set(text: str) -> set:
    out = set()
    for x in re.split(r"[,\s]+", text or ""):
        x = x.strip()
        if x.lstrip("-").isdigit():
            out.add(int(x))
    return out


STAFF = {ADMIN_ID} | _id_set(os.getenv("ADMINS", ""))                               # sab admin (withdraw / wallet kaam)
INVITE_MAX_AGE_HOURS = float(os.getenv("INVITE_MAX_AGE_HOURS", "48"))                # invite code sirf itne ghante tak naye user
INVITE_MAX_WRONG = int(os.getenv("INVITE_MAX_WRONG", "5"))                           # ek din me max galat invite code
INVITE_BLOCK_HOURS = float(os.getenv("INVITE_BLOCK_HOURS", "24"))                    # limit ke baad block
REF_MATURE_DAYS = float(os.getenv("REF_MATURE_DAYS", "3"))                           # dost itne din channel me rahe tab refer pakka
REF_BURST_COUNT = int(os.getenv("REF_BURST_COUNT", "8"))                             # itne refers ...
REF_BURST_WINDOW_MIN = int(os.getenv("REF_BURST_WINDOW_MIN", "10"))                  # ... itne minute me = fraud flag
REF_NUDGE_HOURS = float(os.getenv("REF_NUDGE_HOURS", "24"))                          # adhoora dost ko yaad dilana
PROOF_CHANNEL_ID = int(os.getenv("PROOF_CHANNEL_ID", "0") or 0) or TASK_CHANNEL_ID   # payment proof yahan post hoga
WD_ETA_TEXT = os.getenv("WD_ETA_TEXT", "24-48 ghante")
REPORT_PER_HOUR = int(os.getenv("REPORT_PER_HOUR", "3"))                             # problem report limit
AUTOPOST_HOURS = float(os.getenv("AUTOPOST_HOURS", "12"))                            # channel par auto post har itne ghante
AUTOPOST_DEFAULT_ON = os.getenv("AUTOPOST", "true").strip().lower() not in ("0", "false", "off", "no")
AUTOPOST_DELETE_OLD = os.getenv("AUTOPOST_DELETE_OLD", "true").strip().lower() not in ("0", "false", "off", "no")

# ======================================================================
#  VIDEO / IMAGE LINKS  —  yahan seedha link daalo.  Khaali "" = wo button / image dikhega hi nahi.
# ======================================================================
ENTRY_VIDEO_URL = "https://www.instagram.com/reel/DftSgowMl7M/?cplk=c29odnFtcm56aWpw"   # Entry kaise karein
DROP_VIDEO_URL = "https://www.instagram.com/reel/DftY_EMNJoZ/?dlrf=M3VsdW1uemk2MHR5"      # Drop kaise claim karein
BOT_VIDEO_URL = ""        # <-- poora bot kaise kaam karta hai: video ka link yahan daalna (baad me)
WELCOME_IMAGE_URL = ""    # <-- /start message ke saath image: image ka link yahan daalna (baad me)
LINKS = {
    "welcome_image": WELCOME_IMAGE_URL.strip(),
    "entry_video": ENTRY_VIDEO_URL.strip(),
    "drop_video": DROP_VIDEO_URL.strip(),
    "bot_video": BOT_VIDEO_URL.strip(),
}

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
    "links": LINKS,
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
        "group_link": GROUP_LINK,
        "lb_prizes": LB_PRIZES_RS,
        "lb_min_refs": LB_MIN_REFS,
        "min_withdraw_p": MIN_WITHDRAW_PAISE,
        "ref_reward_p": REF_REWARD_PAISE,
        "ref_mature_days": REF_MATURE_DAYS,
        "wd_eta": WD_ETA_TEXT,
        "result_names": 200,
    },
}

# ======================================================================
#  GLOBALS (main() me set hote hain)
# ======================================================================
bot: Bot = None  # type: ignore
mongo: AsyncMongoClient = None  # type: ignore
users = entries = states = config = winners = sponsors = sponsor_joins = None
drops = drop_codes = drop_claims = rewards = withdrawals = None
ledger = referrals = None
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


_SC_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def sc(text: str) -> str:
    """'Enter Code' -> 'ᴇɴᴛᴇʀ ᴄᴏᴅᴇ' (small-caps style text)."""
    return str(text).translate(_SC_MAP)


def rs(paise) -> str:
    """paise -> '₹50' ya '₹0.20'."""
    p = int(paise or 0)
    return f"₹{p // 100}" if p % 100 == 0 else f"₹{p / 100:.2f}"


def prizes_line() -> str:
    return " / ".join(f"₹{p}" for p in LB_PRIZES_RS)


def full_name(u: User) -> str:
    return " ".join(p for p in (u.first_name, u.last_name) if p) or "User"


def is_admin(uid: int) -> bool:
    """Owner panel (giveaway, broadcast, drops...) sirf main ADMIN_ID ke liye."""
    return uid == ADMIN_ID


def is_staff(uid: int) -> bool:
    """Withdraw / wallet / refers ke kaam sab admins (ADMINS env) kar sakte hain."""
    return uid in STAFF


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
    parts = [f"🎁 <b>{sc('giveaway live hai')}</b> 🔥", ""]
    where = code_where_text(gw)
    if where:
        parts += [where, ""]
    wt = when_line(gw)
    if wt:
        parts += [wt, ""]
    parts += [
        "<b>Bhaag kaise lein? (1 minute)</b>",
        "<blockquote>"
        "1️⃣ Neeche ke button se video / post kholo, usme chhupa <b>code</b> dhundo\n"
        "2️⃣ <b>Enter Code</b> dabao aur wo code bot me bhejo\n"
        "3️⃣ Winner ko redeem code seedha DM me milega 🏆"
        "</blockquote>",
        "",
        f"✅ <b>100% FREE</b>  ·  ⚠️ Galat code baar-baar = {LOCK_HOURS} ghante lock",
    ]
    return "\n".join(parts)


def giveaway_post_kb(gw: dict) -> InlineKeyboardMarkup:
    rows = code_links_rows(gw)
    rows.append([btn("🔑 Enter Code", url=f"https://t.me/{BOT_USERNAME}?start=code")])
    rows += entry_video_row()
    return kb(*rows)


def app_link() -> str:
    """Channel posts ke liye Mini App link (BotFather direct link ho to wahi, warna bot deep-link)."""
    return MINIAPP_LINK or f"https://t.me/{BOT_USERNAME}?start=drop"


# ---------------------------------------------------------------- keyboards
def main_menu_kb(verified: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if not verified:
        rows.append([btn("🛡 " + sc("verify karo (1 tap)"), "verify")])
    rows += [
        [btn("🔑 " + sc("code daalo"), "enter_code")],
        *entry_video_row(),
        [btn("💰 " + sc("paise kamao"), "refer"), btn("📱 " + sc("app kholo"), web_app=WEBSITE_URL)],
        [btn("📢 " + sc("channel"), url=TASK_CHANNEL_LINK), btn("❓ " + sc("madad"), "help")],
        [btn("ℹ️ " + sc("about"), "about")],
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
        *entry_video_row(),
    ]
    return kb(*rows)


def back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Menu", "menu")])


def admin_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("📊 Stats", "adm:stats"), btn("📅 Aaj ka Dashboard", "adm:dash")],
        [btn("➕ Add Giveaway Code", "adm:add")],
        [btn("✏️ Edit Giveaway", "adm:edit"), btn("📣 Repost", "adm:repost")],
        [btn("🏆 Select Winner", "adm:winner")],
        [btn("📢 Broadcast", "adm:bc")],
        [btn("⚡ Free Code Drop", "adm:drop"), btn("🤝 Sponsors", "adm:sponsors")],
        [btn("📥 Reward Requests", "adm:rw"), btn("🎯 Reward Cards", "adm:rwcfg")],
        [btn("💸 Withdrawals", "wa:list")],
        [btn("📣 Notice", "adm:notice"), btn("🧹 Clear Junk", "adm:junk")],
    )


def admin_back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Admin Panel", "adm:home")])


def admin_cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn("❌ Cancel", "adm:home")])


ADMIN_HOME_TEXT = "👑 <b>Admin Panel</b>\n\nKya karna chahte hain? 👇"


# ---------------------------------------------------------------- texts
def _video_row(key: str, label: str) -> list:
    """Video link set ho to ek button row, warna khaali (kuch nahi dikhta)."""
    u = (LINKS.get(key) or "").strip()
    return [[btn(label, url=u)]] if u.startswith(("http://", "https://")) else []


def entry_video_row() -> list:
    return _video_row("entry_video", "▶️ Entry kaise karein? Video dekho")


def drop_video_row() -> list:
    return _video_row("drop_video", "▶️ Drop kaise claim karein? Video dekho")


def bot_video_row() -> list:
    return _video_row("bot_video", "▶️ Poora bot kaise chalta hai? Video dekho")


def video_hint() -> str:
    return "\n▶️ <i>Samajh na aaye to neeche <b>video</b> dekho.</i>" if (LINKS.get("entry_video") or "").strip() else ""


def welcome_text(name: str) -> str:
    return (
        f"🎁 <b>{sc('asb freecodes')}</b>\n\n"
        f"Namaste <b>{esc(name)}</b> 👋\n"
        "Yahan roz <b>FREE Google Play codes</b> milte hain ✅\n\n"
        "<blockquote>"
        "1️⃣ Channel se <b>code</b> dhundo 🔍\n"
        "2️⃣ <b>Code daalo</b> dabao\n"
        "3️⃣ Winner ko code <b>DM</b> me milta hai 🏆"
        "</blockquote>\n\n"
        "🔒 <i>OTP ya password hum kabhi nahi maangte.</i>"
        f"{video_hint()}\n\n"
        "👇 <b>Neeche se shuru karo</b>"
    )


def help_text() -> str:
    return (
        "❓ <b>Madad</b>\n\n"
        "<b>🔑 Giveaway me entry kaise karein?</b>\n"
        "<blockquote>"
        "1️⃣ 🛡 Verify karo (1 tap)\n"
        "2️⃣ 📢 Channel join karo\n"
        "3️⃣ 🔍 Video / post me chhupa code dhundo\n"
        "4️⃣ 🔑 Code bot me bhejo — entry pakki ✅"
        "</blockquote>\n\n"
        "<b>⚡ Drop (Free Google Play code) kaise milta hai?</b>\n"
        "<blockquote>"
        "1️⃣ Channel par Drop announce hota hai — <b>Remind Me</b> dabao 🔔\n"
        "2️⃣ Drop live hote hi <b>CLAIM NOW</b> dabao\n"
        "3️⃣ Jo sabse pehle dabata hai use code milta hai\n"
        "4️⃣ Code copy karke Google Play me <b>Redeem</b> karo"
        "</blockquote>\n\n"
        "<b>🎟 Chance kya hai?</b>\n"
        "Winner <b>random</b> chuna jata hai. Jiske paas zyada 🎟 chance, uska naam aane ke mauke zyada.\n"
        "Chance badhao: dost ko bulao, roz Daily Bonus lo.\n\n"
        f"⚠️ {MAX_WRONG_ATTEMPTS} galat code = {LOCK_HOURS} ghante ka lock. Ek giveaway me ek hi entry.\n\n"
        f"🆘 Dikkat? {esc(SUPPORT_USERNAME)}"
    )


def entry_confirmed_text(
    admin_msg: Optional[str], tickets: int = 1, entry_no: Optional[int] = None, winner_at: Optional[datetime] = None
) -> str:
    lines = ["🎉 <b>Entry pakki!</b> ✅", ""]
    if entry_no:
        lines.append(f"🔢 Entry No: <b>#{entry_no}</b>")
    lines.append(f"🎟 Aapke chance: <b>{tickets}</b>")
    if winner_at:
        lines.append(f"⏰ Winner: <b>{esc(fmt_when(winner_at))}</b>")
    lines += [
        "",
        "Ab bas <b>intezaar</b> karo 😊",
        "Winner ko code <b>DM</b> me milega. Result channel par aayega:",
        f"📢 {TASK_CHANNEL_LINK}",
        "",
        "💡 <i>Zyada 🎟 chance = jeetne ke zyada mauke. Dost ko bulao, chance badhao.</i>",
    ]
    base = "\n".join(lines)
    if admin_msg:
        base += "\n\n━━━━━━━━━━━━━━\n📩 <b>Admin ka message:</b>\n\n" + admin_msg
    return base


def winner_dm_text(code: str) -> str:
    return (
        "🏆 <b>MUBARAK HO! Aap WINNER ho!</b> 🎉\n\n"
        "🎁 Ye raha aapka <b>Redeem Code</b>:\n\n"
        f"<code>{esc(code)}</code>\n\n"
        "👆 Code par tap karo, copy ho jayega.\n\n"
        "<b>Redeem kaise kare?</b>\n"
        "Google Play Store → Profile → Payments &amp; subscriptions → Redeem code\n\n"
        f"📢 Channel: {TASK_CHANNEL_LINK}\n"
        f"🆘 Help: {esc(SUPPORT_USERNAME)}"
    )


def non_winner_text(winner_label: str, n: int = 1) -> str:
    who = (
        f"🏆 <b>{winner_label}</b> is baar jeet gaye 🎉"
        if n == 1
        else f"🏆 <b>{winner_label}</b> is baar jeet gaye ({n} winners) 🎉"
    )
    return (
        "📢 <b>Giveaway ka result aa gaya!</b>\n\n"
        f"{who}\n\n"
        "Aap udaas mat ho 😊 — <b>agli baar aap bhi jeet sakte ho!</b>\n"
        "Channel par bane raho, naye giveaway aur free drops wahin aate hain 🎁\n\n"
        "🔒 Winner ka proof channel par post ho gaya hai.\n"
        f"🆘 Koi sawaal? {esc(SUPPORT_USERNAME)}"
    )


# ======================================================================
#  DATABASE HELPERS
# ======================================================================
async def init_db() -> None:
    global mongo, users, entries, states, config, winners, sponsors, sponsor_joins
    global drops, drop_codes, drop_claims, rewards, withdrawals, ledger, referrals
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
    withdrawals = db["withdrawals"]
    ledger, referrals = db["ledger"], db["referrals"]
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
    await withdrawals.create_index([("status", 1), ("created_at", 1)])
    await withdrawals.create_index([("uid", 1), ("created_at", -1)])
    await ledger.create_index([("uid", 1), ("at", -1)])
    await referrals.create_index([("ref", 1), ("qualified_at", -1)])
    await referrals.create_index([("status", 1), ("mature_at", 1)])
    await users.create_index("ref_by")
    await ensure_week_index(week_key())
    cfg = await config.find_one({"_id": "reward_cfg"})
    for k in ("streak", "refer"):
        if cfg and cfg.get(k):
            REWARD_CFG[k] = cfg[k]
    nt = await config.find_one({"_id": "notice"})
    NOTICE["text"] = (nt or {}).get("text", "")
    site_ctx["db"].update(
        users=users, entries=entries, config=config, winners=winners, sponsors=sponsors,
        drops=drops, drop_claims=drop_claims, rewards=rewards, withdrawals=withdrawals,
        ledger=ledger, referrals=referrals,
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
                "balance_p": 0,
                "earned_p": 0,
                "withdrawn_p": 0,
            },
        },
        upsert=True,
    )
    if len(_touched) > 50000:
        _touched.clear()
    _touched[u.id] = now
    is_new = res.upserted_id is not None
    if is_new:
        queue_new_user(u)  # log channel me batched message
    return is_new


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
    for aid in sorted(STAFF):
        await deliver(aid, lambda cid: bot.send_message(cid, text, reply_markup=markup))


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
    for aid in sorted(STAFF):
        try:
            await bot.send_message(aid, text)
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
        if user and user.id not in STAFF:
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


# ======================================================================
#  v4: PAISE KA LEDGER  (har credit / debit ka record — atomic)
# ======================================================================
LEDGER_LABEL = {
    "refer": "Dost ka refer",
    "leaderboard": "Weekly leaderboard",
    "card": "Reward card",
    "withdraw": "Withdraw",
    "refund": "Paisa wapas",
    "admin_adjust": "Admin ne badla",
    "clawback": "Refer cancel",
    "opening": "Purana balance",
}
_TXN = {"ok": True}


class _WalletAbort(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def _run_txn(fn):
    """fn(session) ko ek MongoDB transaction me chalao. Transaction na chale to bina session (fn(None))."""
    if not _TXN["ok"] or mongo is None:
        return await fn(None)
    try:
        sess = mongo.start_session()
        if inspect.isawaitable(sess):
            sess = await sess
        async with sess as s:
            return await s.with_transaction(fn)
    except _WalletAbort:
        raise
    except (TypeError, AttributeError, NotImplementedError, ConfigurationError) as e:
        _TXN["ok"] = False
        logger.warning("Mongo transaction use nahi ho paya, bina transaction chalega: %s", e)
        return await fn(None)
    except OperationFailure as e:
        if e.code in (20, 263) or "ransaction" in str(e):
            _TXN["ok"] = False
            logger.warning("Mongo transaction support nahi: %s — bina transaction chalega", e)
            return await fn(None)
        raise


async def wallet_apply(
    uid: int,
    delta_p: int,
    typ: str,
    ref: Optional[str] = None,
    note: str = "",
    earned_delta: Optional[int] = None,
    extra_inc: Optional[dict] = None,
    extra_set: Optional[dict] = None,
    by: Optional[int] = None,
) -> dict:
    """Balance badalne ka EKLAUTA raasta. Balance + ledger entry ek saath (transaction).
    delta_p > 0 = credit, < 0 = debit (balance kam ho to fail). `ref` same ho to dobara apply nahi hota.
    Return: {"ok": True, "balance_p", "before_p", "entry_id", "user"} ya {"ok": False, "reason": dup/low/nouser/zero}"""
    delta_p = int(delta_p)
    if delta_p == 0:
        return {"ok": False, "reason": "zero"}
    now = now_utc()
    eid = f"{typ}:{ref}" if ref else f"{typ}:{uid}:{int(time.time() * 1000)}:{random.randint(1000, 9999)}"
    if earned_delta is None:
        earned_delta = delta_p if (delta_p > 0 and typ in ("refer", "leaderboard", "card")) else 0
    inc = {"balance_p": delta_p}
    if earned_delta:
        inc["earned_p"] = int(earned_delta)
    for k, v in (extra_inc or {}).items():
        inc[k] = inc.get(k, 0) + v
    flt: dict = {"_id": uid}
    if delta_p < 0:
        flt["balance_p"] = {"$gte": -delta_p}
    upd: dict = {"$inc": inc}
    if extra_set:
        upd["$set"] = dict(extra_set)
    row = {
        "_id": eid, "uid": uid, "amount_p": delta_p, "type": typ, "ref": str(ref) if ref else None,
        "note": (note or "")[:120], "by": by, "at": now, "balance_after": None,
    }
    fail_reason = "low" if delta_p < 0 else "nouser"

    async def body(session):
        kw = {"session": session} if session is not None else {}
        if await ledger.find_one({"_id": eid}, {"_id": 1}, **kw):
            return {"ok": False, "reason": "dup"}
        try:
            await ledger.insert_one(dict(row), **kw)
        except DuplicateKeyError:
            return {"ok": False, "reason": "dup"}
        after = await users.find_one_and_update(flt, upd, return_document=ReturnDocument.AFTER, **kw)
        if not after:
            if session is not None:
                raise _WalletAbort(fail_reason)  # transaction abort = ledger entry bhi wapas
            await ledger.delete_one({"_id": eid})
            return {"ok": False, "reason": fail_reason}
        bal = int(after.get("balance_p", 0))
        await ledger.update_one({"_id": eid}, {"$set": {"balance_after": bal}}, **kw)
        return {"ok": True, "balance_p": bal, "before_p": bal - delta_p, "entry_id": eid, "user": after}

    try:
        res = await _run_txn(body)
    except _WalletAbort as e:
        return {"ok": False, "reason": e.reason}
    if res.get("ok"):
        site_invalidate(uid)
        invalidate_user(uid)
        if delta_p > 0 and res["before_p"] < MIN_WITHDRAW_PAISE <= res["balance_p"]:
            spawn(notify_min_reached(uid, res["balance_p"]))
    return res


async def notify_min_reached(uid: int, bal: int) -> None:
    await deliver(
        uid,
        lambda cid: bot.send_message(
            cid,
            f"🎉 <b>Balance {rs(bal)} ho gaya!</b>\nAb aap withdraw kar sakte ho 💸",
            reply_markup=kb([btn("💸 " + sc("withdraw"), "w:start")]),
        ),
    )


async def ledger_recent(uid: int, n: int = 20) -> list:
    return [d async for d in ledger.find({"uid": uid}).sort("at", -1).limit(n)]


async def ledger_sum(uid: int) -> int:
    cur = await ledger.aggregate([{"$match": {"uid": uid}}, {"$group": {"_id": None, "t": {"$sum": "$amount_p"}}}])
    rows = [d async for d in cur]
    return int(rows[0]["t"]) if rows else 0


async def ledger_opening_once() -> int:
    """v4 se pehle ke balance ke liye ek 'opening' entry (sirf ek baar)."""
    if await config.find_one({"_id": "ledger_opening"}):
        return 0
    n = 0
    async for u in users.find({"balance_p": {"$gt": 0}}, {"balance_p": 1}):
        bal = int(u.get("balance_p", 0))
        try:
            await ledger.insert_one({
                "_id": f"opening:{u['_id']}", "uid": u["_id"], "amount_p": bal, "type": "opening", "ref": None,
                "note": "v4 se pehle ka balance", "by": None, "at": now_utc(), "balance_after": bal,
            })
            n += 1
        except DuplicateKeyError:
            pass
    await config.update_one({"_id": "ledger_opening"}, {"$set": {"at": now_utc(), "n": n}}, upsert=True)
    logger.info("Ledger opening entries: %s", n)
    return n


def ledger_line(e: dict) -> str:
    amt = int(e.get("amount_p", 0))
    sign = "➕" if amt > 0 else "➖"
    label = LEDGER_LABEL.get(e.get("type"), e.get("type") or "")
    note = f" · {esc(e['note'])}" if e.get("note") and e.get("type") in ("admin_adjust", "clawback") else ""
    at = e.get("at")
    when = at.astimezone(IST).strftime("%d %b") if at else ""
    return f"{sign} <b>{rs(abs(amt))}</b> · {esc(label)}{note} · {when}"


_paid_cache = {"t": -1e9, "v": (0, 0)}


async def paid_stats() -> tuple:
    """(total paid paise, payments count) — 60 sec cache."""
    if time.monotonic() - _paid_cache["t"] < 60:
        return _paid_cache["v"]
    cur = await withdrawals.aggregate([
        {"$match": {"status": {"$in": ["paid", "confirmed"]}}},
        {"$group": {"_id": None, "p": {"$sum": "$amount_p"}, "n": {"$sum": 1}}},
    ])
    rows = [d async for d in cur]
    v = (int(rows[0]["p"]), int(rows[0]["n"])) if rows else (0, 0)
    _paid_cache.update(t=time.monotonic(), v=v)
    return v


# ======================================================================
#  v4: REFER  (verify + channel join -> PENDING, REF_MATURE_DAYS baad PAKKA)
# ======================================================================
async def credit_referral(uid: int) -> None:
    """Dost verify + channel join kar chuka: refer 'pending' me jata hai (paisa abhi nahi)."""
    doc = await users.find_one_and_update(
        {"_id": uid, "ref_by": {"$ne": None}, "ref_credited": {"$ne": True}},
        {"$set": {"ref_credited": True}},
    )
    if not doc:
        return
    ref = doc["ref_by"]
    now = now_utc()
    await referrals.update_one(
        {"_id": uid},
        {
            "$set": {
                "ref": ref, "friend": uid, "name": doc.get("name"), "status": "pending",
                "qualified_at": now, "mature_at": now + timedelta(days=REF_MATURE_DAYS),
            },
            "$setOnInsert": {"created_at": doc.get("ref_at") or now},
        },
        upsert=True,
    )
    # ek saath bahut refers = fraud flag + admin alert
    recent = await referrals.count_documents(
        {"ref": ref, "qualified_at": {"$gte": now - timedelta(minutes=REF_BURST_WINDOW_MIN)}}
    )
    if recent >= REF_BURST_COUNT:
        ru0 = await users.find_one_and_update({"_id": ref}, {"$set": {"ref_flag": True}}) or {}
        spawn(alert_admin(
            f"refburst:{ref}",
            f"⚠️ <b>Referral burst</b>: {mention(ref, ru0.get('name'))} (<code>{ref}</code>) ke "
            f"{REF_BURST_WINDOW_MIN} min me {recent} referrals!\n"
            f"Paisa roka gaya hai. Check: <code>/refs {ref}</code>",
            cooldown=1800,
        ))
    ru = await users.find_one({"_id": ref}, {"banned": 1})
    if ru and not ru.get("banned"):
        days = f"{REF_MATURE_DAYS:g}"
        await deliver(
            ref,
            lambda cid: bot.send_message(
                cid,
                f"👋 <b>{esc(disp_name(doc.get('name'), 28))}</b> aapke invite se aaya aur verify ho gaya!\n\n"
                f"⏳ Wo <b>{days} din</b> channel me rahe to aapka <b>{rs(REF_REWARD_PAISE)}</b> pakka ho jayega.",
                reply_markup=kb([btn("👥 " + sc("mere dost"), "friends")]),
            ),
        )
    if REF_MATURE_DAYS <= 0:
        await settle_referral(uid)


async def settle_referral(friend: int, force: bool = False) -> str:
    """pending -> credited / cancelled / held / retry. Returns status text."""
    now = now_utc()
    r = await referrals.find_one_and_update(
        {"_id": friend, "status": "pending"}, {"$set": {"status": "settling", "settle_at": now}}
    )
    if not r:
        return "none"
    ref = r["ref"]

    async def back(status: str, **extra) -> None:
        await referrals.update_one({"_id": friend}, {"$set": {"status": status, **extra}})

    ru = await users.find_one({"_id": ref}, {"banned": 1, "ref_flag": 1, "name": 1})
    fu = await users.find_one({"_id": friend}, {"banned": 1, "name": 1}) or {}
    if not ru or ru.get("banned"):
        await back("cancelled", cancel_reason="referrer_banned", cancelled_at=now)
        return "cancelled"
    if fu.get("banned"):
        await back("cancelled", cancel_reason="friend_banned", cancelled_at=now)
        return "cancelled"
    if ru.get("ref_flag") and not force:
        await back("held", held_at=now)
        spawn(alert_admin(
            f"refheld:{ref}",
            f"⚠️ {mention(ref, ru.get('name'))} (<code>{ref}</code>) ka refer paisa <b>roka</b> hai (fraud flag).\n"
            f"Check karein: <code>/refs {ref}</code>",
            cooldown=3600,
        ))
        return "held"
    if REFERRAL_REQUIRE_JOIN:
        m = await is_member(TASK_CHANNEL_ID, friend)
        if m is False:
            await back("cancelled", cancel_reason="left", cancelled_at=now)
            spawn(notify_ref_cancelled(ref, r.get("name")))
            return "cancelled"
        if m is None:
            await back("pending", mature_at=now + timedelta(hours=1))
            return "retry"
    wk = week_key()
    await ensure_week_index(wk)
    counts = {"ref_count": 1, "ref_cycle_count": 1, f"wkc.{wk}": 1}
    if REF_REWARD_PAISE > 0:
        res = await wallet_apply(
            ref, REF_REWARD_PAISE, "refer", ref=f"f{friend}", note=disp_name(r.get("name"), 20),
            extra_inc=counts, extra_set={f"wkt.{wk}": now},
        )
        if not res["ok"]:
            if res["reason"] == "dup":
                await back("credited", credited_at=now, reward_p=REF_REWARD_PAISE, wk=wk)
                return "credited"
            await back("pending", mature_at=now + timedelta(hours=1))
            return "retry"
        ru2 = res["user"]
    else:
        ru2 = await users.find_one_and_update(
            {"_id": ref}, {"$inc": counts, "$set": {f"wkt.{wk}": now}}, return_document=ReturnDocument.AFTER
        )
        res = {"balance_p": int((ru2 or {}).get("balance_p", 0))}
    await back("credited", credited_at=now, reward_p=REF_REWARD_PAISE, wk=wk)
    cnt, cycle = int(ru2.get("ref_cycle_count", 1)), int(ru2.get("ref_cycle", 1))
    card = await grant_card(ref, "refer", cycle, cnt)
    if card:
        spawn(notify_card_earned(ref, card))
    if cnt >= max(t for t, _ in REWARD_CFG["refer"]):  # cycle poora -> fresh start
        await users.update_one({"_id": ref}, {"$set": {"ref_cycle_count": 0, "ref_cycle": cycle + 1}})
    await add_tickets(ref, REFERRAL_TICKETS)
    site_invalidate(ref)
    await deliver(
        ref,
        lambda cid: bot.send_message(
            cid,
            f"✅ <b>{esc(disp_name(r.get('name'), 28))}</b> ka refer <b>pakka</b> ho gaya!\n\n"
            f"💰 <b>+{rs(REF_REWARD_PAISE)}</b> balance me add\n"
            f"🎟 <b>+{REFERRAL_TICKETS} chance</b> bhi mila\n"
            f"💼 Balance: <b>{rs(res.get('balance_p', 0))}</b>",
            reply_markup=kb([btn("💰 " + sc("paise kamao"), "refer")]),
        ),
    )
    return "credited"


async def notify_ref_cancelled(ref: int, friend_name) -> None:
    await deliver(
        ref,
        lambda cid: bot.send_message(
            cid,
            f"ℹ️ <b>{esc(disp_name(friend_name, 28))}</b> ne channel chhod diya, isliye ye refer cancel ho gaya.\n"
            "Aapke balance se kuch nahi kata 🙂",
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


@router.chat_member(F.chat.id == TASK_CHANNEL_ID)
async def on_channel_member(ev: ChatMemberUpdated):
    """Dost channel chhode to pending refer turant cancel."""
    if ev.new_chat_member.status not in ("left", "kicked"):
        return
    uid = ev.new_chat_member.user.id
    r = await referrals.find_one_and_update(
        {"_id": uid, "status": {"$in": ["pending", "held"]}},
        {"$set": {"status": "cancelled", "cancel_reason": "left", "cancelled_at": now_utc()}},
    )
    if r:
        spawn(notify_ref_cancelled(r["ref"], r.get("name")))


async def referral_watch_once() -> dict:
    now = now_utc()
    out = {"settled": 0, "nudged": 0}
    # atka hua 'settling' wapas pending
    await referrals.update_many(
        {"status": "settling", "settle_at": {"$lte": now - timedelta(minutes=10)}}, {"$set": {"status": "pending"}}
    )
    due = [d["_id"] async for d in referrals.find({"status": "pending", "mature_at": {"$lte": now}}).limit(40)]
    for fid in due:
        if await settle_referral(fid) == "credited":
            out["settled"] += 1
    # adhoora dost ko ek baar yaad dilana
    cutoff = now - timedelta(hours=REF_NUDGE_HOURS)
    cur = users.find(
        {"ref_by": {"$ne": None}, "ref_credited": {"$ne": True}, "ref_nudged": {"$ne": True},
         "ref_at": {"$lte": cutoff}, "banned": {"$ne": True}, "junk": {"$ne": True}},
        {"verified": 1},
    ).limit(30)
    for u in [d async for d in cur]:
        got = await users.find_one_and_update({"_id": u["_id"], "ref_nudged": {"$ne": True}}, {"$set": {"ref_nudged": True}})
        if not got:
            continue
        todo = "🛡 <b>Verify</b> karo (1 tap)" if not got.get("verified") else "📢 <b>Channel join</b> karo"
        spawn(deliver(
            u["_id"],
            lambda cid, todo=todo: bot.send_message(
                cid,
                "👋 Aapne dost ka invite code lagaya tha, bas ek kaam baaki hai:\n\n"
                f"{todo}\n\nPhir aapke dost ka refer pending me chala jayega 🙏",
                reply_markup=kb([btn("🔑 " + sc("shuru karo"), "enter_code")], [btn("📢 " + sc("join channel"), url=TASK_CHANNEL_LINK)]),
            ),
        ))
        out["nudged"] += 1
    return out


async def referral_watch_loop() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            await referral_watch_once()
        except Exception:
            logger.exception("referral_watch_loop")


# ======================================================================
#  USER HANDLERS
# ======================================================================
async def send_welcome(m: Message, name: str, markup) -> None:
    """Welcome message (image set ho to image ke saath; image na chale to sirf text)."""
    text = welcome_text(name)
    img = (LINKS.get("welcome_image") or "").strip()
    if img:
        try:
            await m.answer_photo(img, caption=text, reply_markup=markup)
            return
        except TelegramAPIError as e:
            logger.warning("Welcome image nahi gayi (%s) — text bhej raha hu", e)
    await m.answer(text, reply_markup=markup)


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
            await users.update_one({"_id": uid}, {"$set": {"ref_by": ref, "ref_at": now_utc(), "ref_via": "link"}})
            invalidate_user(uid)

    await send_welcome(m, m.from_user.first_name, await user_menu(uid))
    if args == "report":
        await start_report(uid)
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
            *entry_video_row(),
            *drop_video_row(),
            *bot_video_row(),
            [btn("📋 " + sc("rules & faq"), "faq"), btn("🆘 " + sc("problem batao"), "report")],
            [btn("👤 " + sc("support"), url=SUPPORT_LINK)],
            [btn("⬅️ " + sc("back"), "menu")],
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
        lines = [f"🏆 <b>{sc('pichhle winners')}</b>\n"]
        for d in docs:
            allw = d.get("winners_all") or []
            if allw:
                names = ", ".join(mention(x.get("id"), x.get("name")) for x in allw)
            else:
                names = mention(d.get("winner_id"), d.get("name"))
            when = d["declared_at"].astimezone(IST).strftime("%d %b %Y") if d.get("declared_at") else ""
            line = f"🎁 <b>#{d.get('giveaway_no', '?')}</b> — {names} — {when}"
            if d.get("entries_count"):
                line += f" · 👥 {d['entries_count']}"
            if d.get("proof_url"):
                line += f' — <a href="{esc(d["proof_url"])}">Proof</a>'
            lines.append(line)
        text = "\n".join(lines)
    await safe_edit(
        cb,
        text,
        kb(
            [btn("📢 " + sc("channel par saare proof"), url=TASK_CHANNEL_LINK)],
            [btn("⬅️ " + sc("menu"), "menu")],
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
    text = "🔑 <b>Code yahan bhejo</b> 👇\n<i>Cancel: /cancel</i>"
    where = code_where_text(gw)
    if where:
        text += "\n\n" + where
    wt = when_line(gw)
    if wt:
        text += "\n\n" + wt
    rows = code_links_rows(gw) + entry_video_row()
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
        f"🎉 Milestone! <b>+{reward} chance</b> mil gaya 🎟"
        if reward
        else "Aaj ke liye extra chance nahi — milestone ka wait karein 😊"
    )
    next_line = (
        f"🎯 Agla reward: <b>{nxt} din</b> par (+{r['next_reward']} chance) — {nxt - streak} din baaki"
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
        n_wd = await withdrawals.count_documents({"status": "pending"})
        n_ban = await users.count_documents({"banned": True})
        liab = await sum_field(users, {}, "balance_p")
        pend_wd = await sum_field(withdrawals, {"status": "pending"}, "amount_p")
        paid_p, paid_n = await paid_stats()
        n_pref = await referrals.count_documents({"status": {"$in": ["pending", "settling", "held"]}})
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
            f"💸 Withdrawals pending: <b>{n_wd}</b> ({rs(pend_wd)})\n"
            f"💼 Sabke balance ka total (dena hai): <b>{rs(liab)}</b>\n"
            f"✅ Ab tak paid: <b>{rs(paid_p)}</b> ({paid_n})\n"
            f"⏳ Pending refers: <b>{n_pref}</b>\n"
            f"🚫 Banned: <b>{n_ban}</b>\n"
            f"{'⚠️ Degraded mode ON' if STATUS['degraded'] else '🟢 Bot healthy'}\n\n"
            f"🎁 <b>Giveaway:</b> {gw_line}",
            admin_back_kb(),
        )

    elif action == "dash":
        await safe_edit(cb, await dash_text(), admin_back_kb())

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
# ======================================================================
#  v4: ADMIN / STAFF COMMANDS  (/balance /adjust /refs /dash)
# ======================================================================
async def sum_field(coll, match: dict, field: str) -> int:
    cur = await coll.aggregate([{"$match": match}, {"$group": {"_id": None, "t": {"$sum": f"${field}"}}}])
    rows = [d async for d in cur]
    return int(rows[0]["t"]) if rows else 0


def today_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def dash_text() -> str:
    t0 = today_start_utc()
    new_users = await users.count_documents({"joined_at": {"$gte": t0}})
    q_today = await referrals.count_documents({"qualified_at": {"$gte": t0}})
    ok_today = await referrals.count_documents({"credited_at": {"$gte": t0}})
    wd_req = await withdrawals.count_documents({"created_at": {"$gte": t0}})
    paid_today_n = await withdrawals.count_documents({"paid_at": {"$gte": t0}})
    paid_today_p = await sum_field(withdrawals, {"paid_at": {"$gte": t0}}, "amount_p")
    paid_p, paid_n = await paid_stats()
    liab = await sum_field(users, {}, "balance_p")
    n_pw = await withdrawals.count_documents({"status": "pending"})
    return (
        f"📅 <b>Aaj ka Dashboard</b> <i>({datetime.now(IST).strftime('%d %b')})</i>\n\n"
        f"👥 Naye users: <b>{new_users}</b>\n"
        f"🤝 Naye refers (pending me gaye): <b>{q_today}</b>\n"
        f"✅ Refers pakke hue: <b>{ok_today}</b>\n"
        f"💸 Withdraw requests: <b>{wd_req}</b>  (abhi pending: {n_pw})\n"
        f"✅ Aaj paid: <b>{paid_today_n}</b> · {rs(paid_today_p)}\n\n"
        f"📊 Ab tak total paid: <b>{rs(paid_p)}</b> ({paid_n})\n"
        f"💼 Sabke balance ka total: <b>{rs(liab)}</b>"
    )


@router.message(Command("dash"))
async def cmd_dash(m: Message):
    if is_staff(m.from_user.id):
        await m.answer(await dash_text())


def parse_uid(command: CommandObject) -> Optional[int]:
    try:
        return int((command.args or "").split()[0])
    except (ValueError, IndexError):
        return None


@router.message(Command("balance"))
async def cmd_balance(m: Message, command: CommandObject):
    if not is_staff(m.from_user.id):
        return
    uid = parse_uid(command)
    if uid is None:
        await m.answer("Use: <code>/balance 123456789</code>")
        return
    u = await users.find_one({"_id": uid})
    if not u:
        await m.answer("⚠️ Ye user database me nahi mila.")
        return
    led_sum = await ledger_sum(uid)
    bal = int(u.get("balance_p", 0))
    pend_n, pend_p = await ref_pending({"referrals": referrals}, uid, REF_REWARD_PAISE)
    recent = await ledger_recent(uid, 5)
    pw = await withdrawals.find_one({"uid": uid, "status": "pending"})
    warn = "" if led_sum == bal else f"\n⚠️ <b>Ledger mismatch!</b> ledger total {rs(led_sum)} ≠ balance {rs(bal)}"
    text = (
        f"💳 <b>Balance</b> — {mention(uid, u.get('name'))} (<code>{uid}</code>)\n\n"
        f"💼 Balance: <b>{rs(bal)}</b>\n"
        f"💰 Kamaya: {rs(u.get('earned_p', 0))} · 💸 Nikala: {rs(u.get('withdrawn_p', 0))}\n"
        f"👥 Refers: {u.get('ref_count', 0)} · ⏳ pending: {pend_n} ({rs(pend_p)})\n"
        f"🚩 Flag: {'HAAN' if u.get('ref_flag') else 'nahi'} · 🚫 Ban: {'HAAN' if u.get('banned') else 'nahi'}\n"
        f"💸 Pending withdraw: {rs(pw['amount_p']) if pw else 'nahi'}{warn}\n\n"
        "<b>Last 5:</b>\n" + ("\n".join(ledger_line(e) for e in recent) if recent else "—")
    )
    await m.answer(text, reply_markup=kb(
        [btn("👥 Refers dekho", f"ar:{uid}")],
        [btn("🚫 Ban", f"ab:{uid}")],
    ))


def parse_rupees(text: str) -> Optional[int]:
    mt = re.fullmatch(r"([+-]?)(\d{1,6})(?:\.(\d{1,2}))?", (text or "").strip())
    if not mt:
        return None
    paise = int(mt.group(2)) * 100 + (int(mt.group(3).ljust(2, "0")) if mt.group(3) else 0)
    return -paise if mt.group(1) == "-" else paise


ADJUST_MAX_P = 500000  # ek baar me max ₹5000


@router.message(Command("adjust"))
async def cmd_adjust(m: Message, command: CommandObject):
    me = m.from_user.id
    if not is_staff(me):
        return
    usage = "Use: <code>/adjust 123456789 +10 wajah</code>  (ya <code>-5</code>)"
    parts = (command.args or "").split(None, 2)
    if len(parts) < 3:
        await m.answer(usage)
        return
    try:
        uid = int(parts[0])
    except ValueError:
        await m.answer(usage)
        return
    amt = parse_rupees(parts[1])
    reason = parts[2].strip()
    if not amt or abs(amt) > ADJUST_MAX_P:
        await m.answer("⚠️ Amount sahi nahi (jaise <code>+10</code>, <code>-5.50</code>; max ₹5000).\n" + usage)
        return
    if len(reason) < 3:
        await m.answer("⚠️ Wajah (reason) zaroor likho — wo user ko bhi dikhegi.\n" + usage)
        return
    u = await users.find_one({"_id": uid}, {"name": 1, "balance_p": 1})
    if not u:
        await m.answer("⚠️ Ye user database me nahi mila.")
        return
    await set_state(me, "adj_confirm", {"uid": uid, "amt": amt, "reason": reason[:100]}, ttl_min=5)
    await m.answer(
        f"{'➕' if amt > 0 else '➖'} <b>Balance adjust — confirm</b>\n\n"
        f"👤 {mention(uid, u.get('name'))} (<code>{uid}</code>)\n"
        f"💼 Abhi: {rs(u.get('balance_p', 0))}\n"
        f"✏️ Badlav: <b>{'+' if amt > 0 else '-'}{rs(abs(amt))}</b>\n"
        f"📝 Wajah: {esc(reason[:100])}\n\nUser ko message bhi jayega.",
        reply_markup=kb([btn("✅ Haan, karo", "adj:y"), btn("❌ Cancel", "adj:n")]),
    )


@router.callback_query(F.data.in_({"adj:y", "adj:n"}))
async def cb_adjust(cb: CallbackQuery):
    me = cb.from_user.id
    if not is_staff(me):
        await cb.answer("⛔ Sirf admin ke liye", show_alert=True)
        return
    st = await get_state(me)
    if cb.data == "adj:n":
        await cb.answer("Cancel")
        await clear_state(me)
        await safe_edit(cb, "❌ Adjust cancel.")
        return
    if not st or st["name"] != "adj_confirm":
        await cb.answer("⌛ Time khatam — dobara /adjust likho", show_alert=True)
        return
    await cb.answer()
    d = st["data"]
    await clear_state(me)
    res = await wallet_apply(d["uid"], d["amt"], "admin_adjust", note=d["reason"], by=me)
    if not res["ok"]:
        why = "balance kam hai" if res["reason"] == "low" else res["reason"]
        await safe_edit(cb, f"⚠️ Adjust nahi hua: {esc(why)}")
        return
    amt, bal = d["amt"], res["balance_p"]
    if amt > 0:
        msg = f"ℹ️ Aapke balance me <b>+{rs(amt)}</b> add kiye gaye.\n📝 Wajah: {esc(d['reason'])}\n💼 Balance: <b>{rs(bal)}</b>"
    else:
        msg = (
            f"ℹ️ Aapke balance se <b>{rs(-amt)}</b> kam kiye gaye.\n📝 Wajah: {esc(d['reason'])}\n"
            f"💼 Balance: <b>{rs(bal)}</b>\n\nGalti lage to: {esc(SUPPORT_USERNAME)}"
        )
    spawn(deliver(d["uid"], lambda cid: bot.send_message(cid, msg)))
    await safe_edit(cb, f"✅ Ho gaya. Naya balance: <b>{rs(bal)}</b>\n(ledger me record + user ko message gaya)")
    await safe_log(f"✏️ <b>Admin adjust</b> by {esc(cb.from_user.full_name)}: <code>{d['uid']}</code> "
                   f"{'+' if amt > 0 else '-'}{rs(abs(amt))} — {esc(d['reason'])}")


async def refs_panel(uid: int) -> tuple:
    rows = await friend_rows({"users": users, "referrals": referrals}, uid, 20)
    u = await users.find_one({"_id": uid}, {"name": 1, "ref_flag": 1, "banned": 1, "ref_count": 1}) or {}
    n_cr = await referrals.count_documents({"ref": uid, "status": "credited"})
    n_pe = await referrals.count_documents({"ref": uid, "status": {"$in": ["pending", "settling"]}})
    n_he = await referrals.count_documents({"ref": uid, "status": "held"})
    body = "\n".join(
        f"• {esc(disp_name(f['name'], 16))} — {FRIEND_LABEL.get(f['status'], f['status'])}"
        f"{' (' + str(f['days_left']) + ' din)' if f.get('days_left') is not None else ''}"
        f" · {fmt_ist(datetime.fromisoformat(f['at'])) if f.get('at') else '—'}"
        for f in rows
    ) or "Koi dost nahi."
    text = (
        f"👥 <b>Refers</b> — {mention(uid, u.get('name'))} (<code>{uid}</code>)\n"
        f"✅ pakke: {n_cr} · ⏳ pending: {n_pe} · ⏸ held: {n_he} · gine gaye: {u.get('ref_count', 0)}\n"
        f"🚩 Flag: {'HAAN' if u.get('ref_flag') else 'nahi'} · 🚫 Ban: {'HAAN' if u.get('banned') else 'nahi'}\n\n{body}"
    )
    rws = [[btn("🚫 Ban", f"ab:{uid}"), btn("💸 Clawback", f"ac:{uid}")]]
    if n_he:
        rws.append([btn("▶️ Held refers chhodo (flag hatao)", f"arl:{uid}")])
    return text, kb(*rws)


@router.message(Command("refs"))
async def cmd_refs(m: Message, command: CommandObject):
    if not is_staff(m.from_user.id):
        return
    uid = parse_uid(command)
    if uid is None:
        await m.answer("Use: <code>/refs 123456789</code>")
        return
    text, markup = await refs_panel(uid)
    await m.answer(text, reply_markup=markup)


async def clawback_refs(ref: int, by: int) -> dict:
    """Is user ke saare 'pakke' refers ka paisa wapas lo (ledger me record + user ko message)."""
    now = now_utc()
    got = []
    async for d in referrals.find({"ref": ref, "status": "credited"}):
        x = await referrals.find_one_and_update(
            {"_id": d["_id"], "status": "credited"}, {"$set": {"status": "clawback", "clawed_at": now, "clawed_by": by}}
        )
        if x:
            got.append(x)
    if not got:
        return {"n": 0, "total_p": 0, "taken_p": 0}
    total = sum(int(x.get("reward_p", 0)) for x in got)
    counts = {"ref_count": -len(got)}
    for x in got:
        if x.get("wk"):
            counts[f"wkc.{x['wk']}"] = counts.get(f"wkc.{x['wk']}", 0) - 1
    taken, bal = 0, 0
    for _ in range(2):
        cur = await users.find_one({"_id": ref}, {"balance_p": 1}) or {}
        bal = int(cur.get("balance_p", 0))
        take = min(total, bal)
        if take <= 0:
            break
        res = await wallet_apply(ref, -take, "clawback", ref=f"cb:{ref}:{int(time.time())}", note=f"{len(got)} refer cancel",
                                 earned_delta=-total, extra_inc=counts, by=by)
        if res["ok"]:
            taken, bal = take, res["balance_p"]
            break
    if not taken:
        await users.update_one({"_id": ref}, {"$inc": {"earned_p": -total, **counts}})
    await users.update_one({"_id": ref}, {"$set": {"ref_flag": True}})
    site_invalidate(ref)
    spawn(deliver(
        ref,
        lambda cid: bot.send_message(
            cid,
            f"ℹ️ Aapke <b>{len(got)} refer</b> cancel kiye gaye (check me galat paaye gaye).\n"
            f"💸 Balance se <b>{rs(taken)}</b> kata gaya.\n💼 Balance: <b>{rs(bal)}</b>\n\n"
            f"Galti lage to: {esc(SUPPORT_USERNAME)}",
        ),
    ))
    return {"n": len(got), "total_p": total, "taken_p": taken}


@router.callback_query(F.data.regexp(r"^(ar|ab|ac|acy|arl):-?\d+$"))
async def cb_refs_admin(cb: CallbackQuery):
    me = cb.from_user.id
    if not is_staff(me):
        await cb.answer("⛔ Sirf admin ke liye", show_alert=True)
        return
    await cb.answer()
    act, _, raw = cb.data.partition(":")
    uid = int(raw)
    if act == "ar":
        text, markup = await refs_panel(uid)
        await bot.send_message(me, text, reply_markup=markup)
    elif act == "ab":
        res = await users.update_one({"_id": uid}, {"$set": {"banned": True}})
        invalidate_user(uid)
        await bot.send_message(me, f"🚫 <code>{uid}</code> ban ho gaya." if res.matched_count else "⚠️ User nahi mila.")
    elif act == "ac":
        docs = [d async for d in referrals.find({"ref": uid, "status": "credited"})]
        total = sum(int(d.get("reward_p", 0)) for d in docs)
        await bot.send_message(
            me,
            f"💸 <b>Clawback</b> — <code>{uid}</code>\n\n{len(docs)} pakke refers ({rs(total)}) cancel honge aur balance se "
            f"(jitna hai utna, max {rs(total)}) kat jayega. User ko message jayega.",
            reply_markup=kb([btn("✅ Haan, clawback", f"acy:{uid}")], [btn("↩️ Wapas", f"ar:{uid}")]),
        )
    elif act == "acy":
        r = await clawback_refs(uid, me)
        await bot.send_message(
            me, f"✅ {r['n']} refers cancel · {rs(r['taken_p'])} kata (kul {rs(r['total_p'])})." if r["n"] else "ℹ️ Koi pakka refer nahi mila."
        )
    elif act == "arl":
        await users.update_one({"_id": uid}, {"$set": {"ref_flag": False}})
        n = (await referrals.update_many({"ref": uid, "status": "held"}, {"$set": {"status": "pending", "mature_at": now_utc()}})).modified_count
        await bot.send_message(me, f"▶️ {n} held refers chhod diye. Flag hata diya (5 min me settle honge).")


# ======================================================================
#  v4: CHANNEL AUTO POST  (har AUTOPOST_HOURS ghante me ek post — bharosa badhane ke liye)
#  Topics ghoomte rehte hain: giveaway / leaderboard / streak / refer / drop / kamai / about
# ======================================================================
def _medal(i: int) -> str:
    return ("🥇", "🥈", "🥉")[i] if i < 3 else f"{i + 1}."


def _post_rows(videos: tuple = ("entry",), first: str = "🤖 Bot kholo — Shuru karo") -> InlineKeyboardMarkup:
    """Har post ke neeche buttons: Bot, Mini App, aur jo videos is topic ke liye (agar link set hai)."""
    rows = [[btn(first, url=BOT_LINK)], [btn("📱 Mini App kholo", url=app_link())]]
    for v in videos:
        rows += {"entry": entry_video_row, "drop": drop_video_row, "bot": bot_video_row}[v]()
    return kb(*rows)


async def bot_numbers() -> dict:
    """Post me dikhane ke liye asli ginti: kitne log, kitni entry, drop me kitna bacha."""
    users_n = await users.count_documents({"junk": {"$ne": True}, "banned": {"$ne": True}})
    entries_n = await entries.count_documents({})
    d = await active_drop()
    total = int(d.get("total", 0)) if d else 0
    claimed = int(d.get("claimed_count", 0)) if d else 0
    return {"users": users_n, "entries": entries_n, "drop": d, "drop_total": total, "drop_claimed": claimed,
            "drop_left": max(0, total - claimed)}


async def post_giveaway():
    gw = await get_giveaway()
    if not gw or gw.get("closing"):
        return None
    n = await bot_numbers()
    when = f"\n⏰ Winner: <b>{esc(fmt_when(gw['winner_at']))}</b>" if gw.get("winner_at") else ""
    text = (
        "🎁 <b>Giveaway LIVE hai!</b>\n\n"
        f"👥 Bot par <b>{n['users']}</b> log hain\n"
        f"✅ <b>{n['entries']}</b> ne entry kar li" + ("" if n["entries"] else " — <b>sabse pehle aap</b> bano!") + f"{when}\n\n"
        "<b>Entry kaise karein:</b>\n"
        "1️⃣ Bot kholo 🤖  2️⃣ Verify karo 🛡\n"
        "3️⃣ Channel join karo 📢\n"
        "4️⃣ Chhupa code dhundo, bot me bhejo 🔑\n\n"
        "🎟 Zyada chance = jeetne ke zyada mauke.\n"
        "<i>100% free — OTP / password kabhi nahi maangte.</i>"
    )
    return text, _post_rows(("entry",), "🔑 Entry karo")


async def post_howto():
    n = await bot_numbers()
    text = (
        "🤖 <b>Is bot ko kaise use karein?</b>\n\n"
        f"👥 Ab tak <b>{n['users']}</b> log juda chuke hain.\n\n"
        "<b>3 asaan step:</b>\n"
        "1️⃣ Bot kholo aur <b>Verify</b> karo (1 tap) 🛡\n"
        "2️⃣ Channel join karo, <b>giveaway code</b> dhundo aur bot me bhejo 🔑\n"
        "3️⃣ Roz <b>Mini App</b> khol kar Daily Bonus lo 🎁\n\n"
        "<b>Fayda:</b> Free Google Play codes jeeto, aur dost bulao to paise bhi kamao 💰\n"
        "<i>Sab bilkul free hai.</i>"
    )
    return text, _post_rows(("entry", "bot"))


async def post_leaderboard():
    wk = week_key()
    rows = await weekly_board(wk, 3)
    prizes = LB_PRIZES_RS
    top_n = int((rows[0].get("wkc") or {}).get(wk, 0)) if rows else 0
    lines = []
    for i in range(len(prizes)):
        if i < len(rows):
            r = rows[i]
            cnt = int((r.get("wkc") or {}).get(wk, 0))
            lines.append(f"{_medal(i)} <b>{esc(mask_name(r.get('name')))}</b> — {cnt} refers  ·  🎁 ₹{prizes[i]}")
        else:
            lines.append(f"{_medal(i)} <i>khaali — yahan aap ho sakte ho</i>  ·  🎁 ₹{prizes[i]}")
    end = week_end_dt()
    need = max(LB_MIN_REFS - top_n, 0)
    text = (
        "🏆 <b>Weekly Leaderboard</b>\n\n" + "\n".join(lines) + "\n\n"
        f"📊 Abhi top par <b>{top_n}</b> refers hain. Prize ke liye kam se kam <b>{LB_MIN_REFS}</b> refers chahiye"
        + (f" (abhi {need} aur)." if need else " ✅") + "\n"
        f"⏳ Hafta khatam: <b>{esc(fmt_when(end))}</b>\n\n"
        "<b>Upar kaise chadhein:</b> Bot → 💰 Paise Kamao → apna code / link dost ko bhejo. "
        "Dost verify + join kare aur 3 din rahe to refer pakka. Prize seedha balance me 💰"
    )
    return text, _post_rows(("bot",), "💰 Refer karo — Bot kholo")


async def post_streak():
    cards = REWARD_CFG.get("streak") or []
    cur = users.find({"streak": {"$gt": 0}, "banned": {"$ne": True}}).sort("streak", -1).limit(3)
    top = [d async for d in cur]
    cards_line = "  ·  ".join(f"{d} din = ₹{a}" for d, a in cards)
    tops = "\n".join(f"{_medal(i)} {esc(mask_name(u.get('name')))} — 🔥 {u.get('streak', 0)} din" for i, u in enumerate(top))
    text = (
        "🔥 <b>Daily Streak — roz aao, card jeeto</b>\n\n"
        "<b>Kaise:</b> Mini App kholo → 🎁 <b>Daily Bonus</b> dabao. Roz aao, streak tootne mat do.\n\n"
        f"🎯 Streak cards (paisa seedha balance me):\n{cards_line}\n"
        + (f"\n🏅 <b>Abhi ke top streak:</b>\n{tops}\n" if top else "")
        + "\n🎟 Har milestone par aapke jeetne ke chance bhi badhte hain."
    )
    return text, _post_rows(("bot",), "🎁 Daily Bonus lo")


async def post_refer():
    total_refs = await sum_field(users, {}, "ref_count")
    paid_p, paid_n = await paid_stats()
    cur = users.find({"ref_count": {"$gt": 0}, "banned": {"$ne": True}}).sort("ref_count", -1).limit(3)
    top = [d async for d in cur]
    tops = "\n".join(f"{_medal(i)} {esc(mask_name(u.get('name')))} — {u.get('ref_count', 0)} dost" for i, u in enumerate(top))
    text = (
        "👥 <b>Dost bulao, paise kamao</b>\n\n"
        f"Har <b>pakke dost</b> par <b>{rs(REF_REWARD_PAISE)}</b> + 🎟 chance.\n"
        f"✅ Ab tak <b>{total_refs}</b> refers pakke hue"
        + (f"\n💸 Ab tak <b>{rs(paid_p)}</b> ({paid_n} payments) users ko bheje ja chuke hain" if paid_p else "")
        + (f"\n\n🏅 <b>Top referrers:</b>\n{tops}" if top else "")
        + "\n\n<b>Kaise karein:</b>\n"
        "1️⃣ Bot → 💰 Paise Kamao kholo\n"
        "2️⃣ Apna <b>Invite Code / Link</b> dost ko bhejo\n"
        f"3️⃣ Dost verify + channel join kare aur {REF_MATURE_DAYS:g} din rahe → paisa pakka ✅\n\n"
        f"Withdraw {rs(MIN_WITHDRAW_PAISE)} se. Har payment ka proof is channel par aata hai."
    )
    return text, _post_rows(("bot",), "👥 Refer karo — Bot kholo")


async def post_drop():
    n = await bot_numbers()
    d = n["drop"]
    if not d:
        return None
    if d.get("status") == "live":
        text = (
            f"⚡ <b>Drop #{d['_id']} LIVE hai!</b>\n\n🎁 {esc(d.get('label', 'Google Play Redeem Code'))}\n"
            f"📦 Total: <b>{n['drop_total']}</b>  ·  ✅ Claim hue: <b>{n['drop_claimed']}</b>  ·  🔥 Bache: <b>{n['drop_left']}</b>\n\n"
            "<b>Claim kaise karein:</b>\n1️⃣ Bot / Mini App kholo\n2️⃣ <b>CLAIM NOW</b> dabao\n"
            "3️⃣ Code DM me aayega — Google Play me <b>Redeem</b> karo\n\n"
            "Jaldi karo, pehle aane walon ko milta hai 🏃"
        )
    else:
        when = esc(fmt_when(d.get("go_live_at"))) if d.get("go_live_at") else "jaldi"
        text = (
            f"⚡ <b>Naya Drop aa raha hai!</b>\n\n🎁 {esc(d.get('label', 'Google Play Redeem Code'))}\n"
            f"📦 Codes: <b>{n['drop_total']}</b>  ·  ⏰ Live: <b>{when}</b>\n\n"
            "Bot me <b>Remind Me</b> dabao, notification ON rakho 🔔\nLive hote hi CLAIM NOW dabana!"
        )
    return text, _post_rows(("drop",), "⚡ Drop claim karo")


async def post_drop_info():
    text = (
        "⚡ <b>Free Google Play Redeem Code kab aur kaise milta hai?</b>\n\n"
        "Kabhi kabhi channel par <b>Drop</b> aata hai — kuch Google Play codes thodi der ke liye live hote hain.\n\n"
        "<b>Kaise lein:</b>\n"
        "1️⃣ Drop announce hote hi bot me <b>Remind Me</b> dabao 🔔\n"
        "2️⃣ Live hote hi <b>CLAIM NOW</b> dabao\n"
        "3️⃣ Jo sabse pehle dabata hai use code milta hai\n"
        "4️⃣ Code copy karke Google Play → Redeem me daalo ✅\n\n"
        "💡 Notification ON rakho, tabhi pata chalega."
    )
    return text, _post_rows(("drop",), "🔔 Bot kholo — Remind Me")


async def post_earn_ways():
    cards_s = "  ·  ".join(f"{d} din = ₹{a}" for d, a in (REWARD_CFG.get("streak") or []))
    cards_r = "  ·  ".join(f"{d} refer = ₹{a}" for d, a in (REWARD_CFG.get("refer") or []))
    text = (
        "💰 <b>Is bot se paise kaise kamayein?</b>\n\n"
        f"1️⃣ <b>Refer:</b> har pakke dost par {rs(REF_REWARD_PAISE)}\n"
        f"2️⃣ <b>Weekly Leaderboard:</b> top 3 ko {prizes_line()} ({LB_MIN_REFS}+ refers)\n"
        f"3️⃣ <b>Streak cards:</b> {cards_s}\n"
        f"4️⃣ <b>Refer cards:</b> {cards_r}\n"
        "5️⃣ <b>Giveaway + Drops:</b> free Google Play codes 🎁\n\n"
        f"💸 Withdraw {rs(MIN_WITHDRAW_PAISE)} se — UPI / Bank / Mobile. Har payment ka proof yahin aata hai ✅"
    )
    return text, _post_rows(("bot",), "💰 Kamai shuru karo")


async def post_chance():
    text = (
        "🎟 <b>Chance (ticket) kya hai?</b>\n\n"
        "Giveaway me winner <b>random</b> chuna jata hai.\n"
        "Jiske paas <b>zyada 🎟 chance</b>, uska naam aane ke <b>zyada mauke</b>.\n\n"
        "<b>Chance kaise badhayein:</b>\n"
        "• Entry karo (1 chance)\n"
        "• Dost bulao — har pakke dost par +1\n"
        "• Roz Daily Bonus lo, streak milestone par extra\n\n"
        "Entry free hai, bas bot me code bhejna hai 🔑"
    )
    return text, _post_rows(("entry",), "🔑 Entry karo")


async def post_winners():
    total = await winners.count_documents({})
    if not total:
        return None
    docs = [d async for d in winners.find({}).sort("declared_at", -1).limit(3)]
    paid_p, paid_n = await paid_stats()
    lines = "\n".join(f"🏆 {esc(mask_name(d.get('name')))} — Giveaway #{d.get('giveaway_no', '?')}" for d in docs)
    text = (
        "🎉 <b>Ye log jeet chuke hain!</b>\n\n"
        f"Ab tak <b>{total}</b> giveaway ke winners:\n{lines}\n"
        + (f"\n💸 Ab tak <b>{rs(paid_p)}</b> ({paid_n} payments) users ko mil chuke hain\n" if paid_p else "")
        + "\nAgla naam aapka ho sakta hai — entry free hai 🔑"
    )
    return text, _post_rows(("entry",), "🔑 Entry karo")


async def post_earners():
    cur = users.find({"earned_p": {"$gt": 0}, "banned": {"$ne": True}}).sort("earned_p", -1).limit(3)
    top = [d async for d in cur]
    if not top:
        return None
    paid_p, paid_n = await paid_stats()
    tops = "\n".join(f"{_medal(i)} {esc(mask_name(u.get('name')))} — <b>{rs(u.get('earned_p', 0))}</b>" for i, u in enumerate(top))
    text = (
        "💰 <b>Sabse zyada kamai (is bot par)</b>\n\n" + tops + "\n\n"
        + (f"💸 Total paid: <b>{rs(paid_p)}</b> ({paid_n} payments)\n" if paid_p else "")
        + "Refer, streak cards aur weekly leaderboard — teeno se kamai hoti hai. Aap bhi shuru karo 👇"
    )
    return text, _post_rows(("bot",), "💰 Kamai shuru karo")


async def post_about():
    n = await bot_numbers()
    text = (
        f"🎁 <b>{BOT_NAME}</b>\n\n"
        f"👥 <b>{n['users']}</b> log juda chuke hain\n\n"
        "✅ Free Google Play codes ke giveaway aur drops\n"
        "🔥 Daily bonus aur streak cards\n"
        "👥 Refer karo, paise kamao\n"
        "🏆 Weekly leaderboard prizes\n\n"
        "100% free. OTP / password kabhi nahi. Har winner aur payment ka proof yahin aata hai ✅"
    )
    return text, _post_rows(("bot",))


# Har 12 ghante me ek alag topic — saare topics ghoomte rehte hain (khaali wale apne aap skip)
AUTOPOST_TOPICS = [
    post_giveaway, post_howto, post_leaderboard, post_drop, post_earn_ways, post_streak, post_winners,
    post_refer, post_drop_info, post_chance, post_earners, post_about,
]


async def autopost_cfg() -> dict:
    doc = await config.find_one({"_id": "autopost"}) or {}
    return {
        "enabled": doc.get("enabled", AUTOPOST_DEFAULT_ON), "hours": float(doc.get("hours", AUTOPOST_HOURS)),
        "last_at": doc.get("last_at"), "idx": int(doc.get("idx", 0)), "last_msg": doc.get("last_msg"),
    }


async def autopost_once(force: bool = False) -> str:
    """Return: 'posted:<topic>' / 'off' / 'wait' / 'failed'."""
    cfg = await autopost_cfg()
    now = now_utc()
    if not force:
        if not cfg["enabled"]:
            return "off"
        la = cfg["last_at"]
        if la is not None and now - la < timedelta(hours=cfg["hours"]):
            return "wait"
    prev_at = cfg["last_at"]
    try:  # slot atomic claim — do deploy ek saath chalein to bhi ek hi post
        flt: dict = {"_id": "autopost"}
        if not force and prev_at is not None:
            flt["last_at"] = prev_at
        r = await config.update_one(flt, {"$set": {"last_at": now}}, upsert=prev_at is None)
        if r.matched_count == 0 and r.upserted_id is None:
            return "wait"
    except DuplicateKeyError:
        return "wait"
    n = len(AUTOPOST_TOPICS)
    for k in range(n):
        i = (cfg["idx"] + k) % n
        fn = AUTOPOST_TOPICS[i]
        try:
            built = await fn()
        except Exception:
            logger.exception("autopost topic %s", fn.__name__)
            built = None
        if not built:
            continue
        text, markup = built
        res, msg = await deliver_result(TASK_CHANNEL_ID, lambda cid: bot.send_message(cid, text, reply_markup=markup))
        if res == OK and msg is not None:
            if AUTOPOST_DELETE_OLD and cfg["last_msg"]:
                try:
                    await bot.delete_message(TASK_CHANNEL_ID, int(cfg["last_msg"]))
                except Exception:
                    pass
            await config.update_one({"_id": "autopost"}, {"$set": {"idx": i + 1, "last_msg": msg.message_id}})
            return f"posted:{fn.__name__[5:]}"
        spawn(alert_admin("autopost_fail", "⚠️ Channel par auto post nahi ja paya. Bot ko task channel me <b>admin</b> (post karne ki permission ke saath) banayein.", cooldown=3600))
        await config.update_one({"_id": "autopost"}, {"$set": {"last_at": prev_at}} if prev_at else {"$unset": {"last_at": ""}})
        return "failed"
    return "failed"


async def autopost_loop() -> None:
    while True:
        await asyncio.sleep(600)
        try:
            await autopost_once()
        except Exception:
            logger.exception("autopost_loop")


@router.message(Command("autopost"))
async def cmd_autopost(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    arg = (command.args or "").strip().lower().split()
    if arg and arg[0] in ("on", "off"):
        await config.update_one({"_id": "autopost"}, {"$set": {"enabled": arg[0] == "on"}}, upsert=True)
    elif arg and arg[0] == "hours" and len(arg) > 1:
        try:
            h = float(arg[1])
            assert 1 <= h <= 72
        except (ValueError, AssertionError):
            await m.answer("Use: <code>/autopost hours 12</code>  (1 se 72 ke beech)")
            return
        await config.update_one({"_id": "autopost"}, {"$set": {"hours": h}}, upsert=True)
    elif arg and arg[0] == "now":
        out = await autopost_once(force=True)
        await m.answer(f"📣 Result: <code>{esc(out)}</code>")
        return
    c = await autopost_cfg()
    la = fmt_ist(c["last_at"]) if c["last_at"] else "abhi tak nahi"
    await m.answer(
        "📣 <b>Channel Auto Post</b>\n\n"
        f"Status: <b>{'ON ✅' if c['enabled'] else 'OFF ⏸'}</b>\nHar: <b>{c['hours']:g} ghante</b>\nPichhla post: {la}\n\n"
        "<code>/autopost on</code> · <code>/autopost off</code>\n<code>/autopost hours 12</code> · <code>/autopost now</code>"
    )


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
        if st["name"] in ("invite_code", "invite_confirm"):
            await handle_invite_code(m)
            return
        if st["name"] == "report":
            await handle_report(m)
            return
        if st["name"] == "wd_detail":
            await handle_wd_detail(m, st)
            return
        if st["name"] == "wd_name":
            await handle_wd_name(m, st)
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


def result_post_texts(no, all_w: list, losers: list, total: int, declared_at, all_random: bool) -> list:
    """Channel result: winner + participants (side by side, tappable naam, quote style). Max ~60 naam / message."""
    single = len(all_w) == 1
    wnames = "  •  ".join(mention(x["id"], x["name"]) for x in all_w)
    lost_total = max(0, total - len(all_w))
    head = (
        f"🏆 <b>{sc('giveaway')} #{no} — {sc('result')}</b> 🏆\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎯 Is giveaway ka code {'is user' if single else 'in users'} ne claim kiya 👇\n\n"
        f"<blockquote>🏆 <b>{'Winner' if single else 'Winners'}:</b>\n{wnames}</blockquote>\n\n"
        f"👥 Total participants: <b>{total}</b>\n"
        f"🏅 Jeete: <b>{len(all_w)}</b>   ·   😔 Nahi jeete: <b>{lost_total}</b>\n"
        f"🕒 {fmt_ist(declared_at)}"
        + ("\n🎲 Random Pick (zyada 🎟 chance = zyada mauka)" if all_random else "")
    )
    foot = (
        "\n\n✅ Redeem code winner ke DM me bhej diya gaya hai.\n"
        "😊 Nahi jeete? Agli baar aap bhi — naam par tap karke profile dekh sakte ho."
    )
    shown = losers[:RESULT_MAX_NAMES]
    hidden = max(0, lost_total - len(shown))

    def block(chunk: list, title: str) -> str:
        names = "  •  ".join(mention(x["id"], x["name"]) for x in chunk)
        return f"<blockquote expandable>{title}\n{names}</blockquote>"

    texts = []
    first, rest = shown[:40], shown[40:]
    msg = head
    if first:
        msg += "\n\n" + block(first, "😔 <b>Participants (jo nahi jeete):</b>")
    texts.append(msg)
    for i in range(0, len(rest), 60):
        texts.append(block(rest[i:i + 60], "📜 <b>Participants (continued):</b>"))
    tail = foot + (f"\n➕ aur <b>{hidden}</b> participants" if hidden else "")
    tail += f"\n🤖 Agla giveaway: https://t.me/{BOT_USERNAME}"
    texts[-1] += tail
    return texts


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

    # 1) redeem code -> har winner ke DM.
    #    Bot block / delete kiya ho to code usko nahi jata — wahi code kisi aur entrant ko chala jata hai.
    ok, failed, replaced = [], [], []
    taken = {i["id"] for i in infos} | {p["id"] for p in paid}
    for orig in infos:
        cur = orig
        for _try in range(REPLACE_TRIES):
            res = await deliver(
                cur["id"],
                lambda uid, c=cur["code"]: bot.send_message(uid, winner_dm_text(c), reply_markup=channel_kb()),
            )
            if res == OK:
                ok.append(cur)
                if cur is not orig:
                    replaced.append((orig, cur))
                break
            if res == JUNK:
                await mark_junk(cur["id"])
            rep_w = await pick_random_winner(exclude=taken)
            if not rep_w:  # koi aur entrant bacha nahi
                failed.append(cur)
                break
            taken.add(rep_w["_id"])
            ru = await users.find_one({"_id": rep_w["_id"]}) or {}
            cur = {
                "id": rep_w["_id"],
                "name": ru.get("name") or "Ek user",
                "username": ru.get("username"),
                "code": orig["code"],
                "random": True,
            }
        else:
            failed.append(cur)
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
        {"id": i["id"], "name": i["name"], "username": i.get("username"), "random": i["random"]} for i in ok
    ]
    ids = [x["id"] for x in all_w]
    # participants (jo nahi jeete) — entries delete hone se pehle naam save (result post + Mini App ke liye)
    loser_docs = [
        {"id": e["_id"], "name": e.get("name"), "username": e.get("username")}
        async for e in entries.find({"_id": {"$nin": ids}}, {"name": 1, "username": 1}).sort("entered_at", 1).limit(RESULT_STORE_NAMES)
    ]
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
            "losers": loser_docs,
            "losers_total": max(0, entries_count - len(all_w)),
        }
    )
    live_state["v"] += 1
    await close_channel_post(gw)  # purani giveaway post "khatam" ho jati hai

    # 4) winner proof -> task channel par (winner + participants, quote style, tappable naam)
    proof = "— (off)"
    if POST_WINNER_TO_CHANNEL:
        texts = result_post_texts(giveaway_no, all_w, loser_docs, entries_count, declared_at, all_random)
        last = len(texts) - 1
        first_id = None
        sent_all = True
        for n, txt in enumerate(texts):
            markup = kb([btn("🎁 " + sc("next giveaway"), url=f"https://t.me/{BOT_USERNAME}")]) if n == last else None
            pres, pmsg = await deliver_result(
                TASK_CHANNEL_ID, lambda cid, t=txt, mk=markup: bot.send_message(cid, t, reply_markup=mk)
            )
            if pres == OK and pmsg:
                if first_id is None:
                    first_id = pmsg.message_id
            else:
                sent_all = False
                if first_id is None:
                    break
        if first_id is not None:
            await winners.update_one({"_id": ins.inserted_id}, {"$set": {"proof_url": post_link(first_id)}})
            proof = "✅ Post ho gaya" if sent_all else "⚠️ Post adhoori gayi"
        else:
            proof = "⚠️ Post nahi hua (bot ko channel me admin banayein)"

    # 5) reports
    report = (
        "✅ <b>Winner declare ho gaya!</b>\n\n"
        + "\n".join(f"🏆 {_wlabel(x)}  (<code>{x['id']}</code>)" for x in all_w)
        + "".join(
            f"\n♻️ {_wlabel(o)} ko DM nahi ja paya → code <b>{_wlabel(n)}</b> ko bheja gaya" for o, n in replaced
        )
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
            f"💰 Aapka <b>₹{card['amount']}</b> ka card ready hai.\n\n"
            "📱 App → <b>Rewards</b> tab → <b>Claim Now</b> dabao, paisa seedha aapke balance me add ho jayega.",
            reply_markup=kb([btn("🎁 " + sc("rewards kholo"), web_app=WEBSITE_URL)]),
        ),
    )


async def redeem_reward_core(uid: int, rid: str) -> dict:
    """Card CLAIM: paisa seedha profile balance me (admin ko request nahi jaati)."""
    u = await get_user_cached(uid)
    if not u:
        return {"status": "unregistered"}
    if u.get("banned"):
        return {"status": "banned"}
    now = now_utc()
    r = await rewards.find_one_and_update(
        {"_id": str(rid), "uid": uid, "status": "earned"},
        {"$set": {"status": "claimed", "claimed_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not r:
        cur = await rewards.find_one({"_id": str(rid), "uid": uid})
        return {"status": "already" if cur else "not_found", "state": cur.get("status") if cur else None}
    paise = int(r["amount"]) * 100
    try:
        res = await wallet_apply(uid, paise, "card", ref=r["_id"], note=f"{r.get('track')} {r.get('target')}")
        if not res["ok"] and res["reason"] != "dup":
            raise RuntimeError(f"wallet card fail: {res['reason']}")
    except Exception:
        await rewards.update_one({"_id": r["_id"]}, {"$set": {"status": "earned"}, "$unset": {"claimed_at": ""}})
        raise
    site_invalidate(uid)
    if res["ok"]:
        bal = int(res["balance_p"])
    else:
        bal = int(((await users.find_one({"_id": uid}, {"balance_p": 1})) or {}).get("balance_p", paise))
    spawn(deliver(
        uid,
        lambda cid: bot.send_message(
            cid,
            f"✅ <b>Card claim ho gaya!</b>\n\n💰 <b>+₹{r['amount']}</b> aapke balance me add ho gaye\n"
            f"💼 Total balance: <b>{rs(bal)}</b>",
            reply_markup=kb([btn("💸 " + sc("withdraw"), "w:start")]),
        ),
    ))
    return {"status": "ok", "amount": r["amount"], "balance_p": bal}


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
        await cb.answer("✅ Verified! Dost ka refer pending me gaya (kuch din baad pakka). Shukriya 🙏", show_alert=True)
    else:
        await cb.answer("✅ Sab theek hai!", show_alert=True)


# ======================================================================
#  💰 WALLET: NEW-USER LOG · INVITE CODE · WITHDRAW · WEEKLY LEADERBOARD
# ======================================================================
_week_idx: set = set()


async def ensure_week_index(wk: str) -> None:
    """Is hafte ke refer counter par index (leaderboard fast rahe)."""
    if wk in _week_idx:
        return
    try:
        await users.create_index([(f"wkc.{wk}", -1), (f"wkt.{wk}", 1)])
        _week_idx.add(wk)
    except Exception as e:  # index fail hone se kuch nahi rukna chahiye
        logger.warning("week index nahi bana (%s): %s", wk, e)


def wk_count(doc: dict, wk: str) -> int:
    return int(((doc or {}).get("wkc") or {}).get(wk, 0))


async def weekly_board(wk: str, limit: int = 10) -> list:
    await ensure_week_index(wk)
    cur = users.find({f"wkc.{wk}": {"$gt": 0}, "banned": {"$ne": True}}).sort(
        [(f"wkc.{wk}", -1), (f"wkt.{wk}", 1)]
    ).limit(limit)
    return [d async for d in cur]


# ---------------------------------------------------------------- naye user ka log (batched — spike me bhi flood nahi)
_newuser_q: deque = deque(maxlen=5000)


def queue_new_user(u: User) -> None:
    _newuser_q.append((u.id, full_name(u), u.username, time.monotonic()))


async def flush_newusers() -> None:
    if not _newuser_q:
        return
    now = time.monotonic()
    compact = len(_newuser_q) > 40  # bahut zyada join ho rahe ho to chhoti lines
    cap = 20 if compact else 8
    batch = []
    while _newuser_q and len(batch) < cap and now - _newuser_q[0][3] >= 2:
        batch.append(_newuser_q.popleft())
    if not batch:
        return
    refs = {d["_id"]: d.get("ref_by") async for d in users.find({"_id": {"$in": [b[0] for b in batch]}}, {"ref_by": 1})}
    total = await users.estimated_document_count()
    blocks = []
    for uid, name, uname, _t in batch:
        ref = refs.get(uid)
        if compact:
            blocks.append(f"• {mention(uid, name)} <code>{uid}</code>" + (f" ← <code>{ref}</code>" if ref else ""))
        else:
            blocks.append(
                f"👤 {mention(uid, name)}\n"
                f"🔗 {('@' + esc(uname)) if uname else 'N/A'}   🆔 <code>{uid}</code>\n"
                f"👥 Referred by: {('<code>' + str(ref) + '</code>') if ref else '—'}"
            )
    head = "🆕 <b>New User Joined</b>" if len(batch) == 1 else f"🆕 <b>{len(batch)} New Users Joined</b>"
    waiting = len(_newuser_q)
    tail = f"\n⏳ Queue me aur: {waiting}" if waiting else ""
    await safe_log(f"{head}\n\n" + ("\n" if compact else "\n\n").join(blocks) + f"\n\n📊 Total users: <b>{total}</b>{tail}")


async def newuser_log_loop() -> None:
    while True:
        await asyncio.sleep(4)  # ~15 msg/min — channel limit (20/min) se neeche
        try:
            await flush_newusers()
        except Exception:
            logger.exception("newuser_log_loop")


# ---------------------------------------------------------------- invite code
async def _inv_fail(uid: int, status: str) -> dict:
    """Galat invite attempt gino. INVITE_MAX_WRONG ke baad INVITE_BLOCK_HOURS ka block."""
    day = today_ist()
    r = await users.update_one({"_id": uid, "inv_day": day}, {"$inc": {"inv_n": 1}})
    if r.matched_count == 0:
        await users.update_one({"_id": uid}, {"$set": {"inv_day": day, "inv_n": 1}})
        n = 1
    else:
        n = int(((await users.find_one({"_id": uid}, {"inv_n": 1})) or {}).get("inv_n", 1))
    if n >= INVITE_MAX_WRONG:
        await users.update_one({"_id": uid}, {"$set": {"inv_block_until": now_utc() + timedelta(hours=INVITE_BLOCK_HOURS)}})
        return {"status": "blocked", "hours": int(INVITE_BLOCK_HOURS)}
    return {"status": status, "left": max(INVITE_MAX_WRONG - n, 0)}


async def invite_core(uid: int, code: str, preview: bool = False) -> dict:
    """Invite code (= referrer ki Telegram ID) lagao — bot aur Mini App dono yahi use karte hain.
    preview=True: sirf check karo aur 'ye <naam> ka code hai' dikhao (kuch save nahi hota)."""
    code = (code or "").strip()
    u = await users.find_one(
        {"_id": uid}, {"verified": 1, "banned": 1, "ref_by": 1, "ref_credited": 1, "joined_at": 1, "inv_block_until": 1}
    )
    if not u:
        return {"status": "unregistered"}
    if u.get("banned"):
        return {"status": "banned"}
    if u.get("ref_by"):
        res = await maybe_credit_referral(uid)  # pehle ka pending ho to aage badhao
        ru0 = await users.find_one({"_id": u["ref_by"]}, {"name": 1}) or {}
        return {"status": "already", "credited": res == "credited", "ref_name": short_name(ru0.get("name"))}
    now = now_utc()
    blk = u.get("inv_block_until")
    if blk and blk > now:
        return {"status": "blocked", "hours": max(1, int((blk - now).total_seconds() // 3600) + 1)}
    joined = u.get("joined_at")
    if not joined or now - joined > timedelta(hours=INVITE_MAX_AGE_HOURS):
        return {"status": "too_old", "hours": int(INVITE_MAX_AGE_HOURS)}
    if not code.isdigit() or len(code) > 15:
        return await _inv_fail(uid, "invalid")
    ref = int(code)
    if ref == uid:
        return await _inv_fail(uid, "self")
    ru = await users.find_one({"_id": ref}, {"banned": 1, "ref_by": 1, "name": 1})
    if not ru or ru.get("banned"):
        return await _inv_fail(uid, "not_found")
    if ru.get("ref_by") == uid:
        return await _inv_fail(uid, "reciprocal")
    member = await is_member(TASK_CHANNEL_ID, uid)
    if member is False:
        return {"status": "need_join"}
    if member is None:
        spawn(alert_admin(
            "invite_member_check",
            "⚠️ Invite code ke liye channel membership check nahi ho pa raha — bot ko task channel me <b>admin</b> banayein.",
            cooldown=900,
        ))
        return {"status": "check_failed"}
    if preview:
        return {"status": "preview", "ref_name": short_name(ru.get("name")), "code": str(ref)}
    upd = await users.update_one(
        {"_id": uid, "ref_by": None}, {"$set": {"ref_by": ref, "ref_via": "code", "ref_at": now_utc()}}
    )
    if upd.matched_count == 0:
        return {"status": "already", "credited": False}
    invalidate_user(uid)
    if not u.get("verified"):
        return {"status": "need_verify", "ref_name": short_name(ru.get("name"))}
    res = await maybe_credit_referral(uid)
    site_invalidate(uid)
    return {"status": "ok", "credited": res == "credited", "ref_name": short_name(ru.get("name"))}


def invite_retry_kb() -> InlineKeyboardMarkup:
    return kb([btn("🔁 " + sc("dubara code daalo"), "invite")], [btn("⬅️ " + sc("menu"), "menu")])


@router.callback_query(F.data == "invite")
async def cb_invite(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    u = await users.find_one({"_id": uid}, {"ref_by": 1}) or {}
    if u.get("ref_by"):
        ru0 = await users.find_one({"_id": u["ref_by"]}, {"name": 1}) or {}
        await safe_edit(
            cb,
            f"✅ Aapne pehle hi <b>{esc(short_name(ru0.get('name')))}</b> ka invite code laga rakha hai.\n"
            "Ek hi code lagta hai, dobara nahi lag sakta 🙏",
            kb([btn("⬅️ " + sc("back"), "refer")]),
        )
        return
    await set_state(uid, "invite_code", ttl_min=10)
    await safe_edit(
        cb,
        f"🎟 <b>{sc('invite code daalo')}</b>\n\n"
        "Jis dost ne aapko bot bataya, uska <b>Invite Code</b> (number) yahan bhejo 👇\n\n"
        f"ℹ️ Code sirf <b>pehle {INVITE_MAX_AGE_HOURS:g} ghante</b> me lag sakta hai, aur ek hi baar.\n"
        "📢 Pehle channel join karna hoga.\n\n"
        "<i>Cancel: /cancel</i>",
        kb([btn("⬅️ " + sc("back"), "refer")]),
    )


async def handle_invite_code(m: Message) -> None:
    uid = m.from_user.id
    if not m.text:
        await m.answer("⚠️ Invite code number hota hai — text me bhejo 🙂")
        return
    await touch_user(m.from_user)
    res = await invite_core(uid, m.text, preview=True)
    st = res["status"]
    left = res.get("left")
    left_txt = f"\n<i>Aaj {left} koshish aur baaki hain.</i>" if left is not None else ""
    if st == "preview":
        await set_state(uid, "invite_confirm", {"code": res["code"]}, ttl_min=10)
        await m.answer(
            f"🎟 Ye code <b>{esc(res['ref_name'])}</b> ka hai.\n\nKya yehi aapko laya? Pakka karo 👇\n"
            "<i>Ek baar lagne ke baad badal nahi sakte.</i>",
            reply_markup=kb([btn("✅ " + sc("haan, laga do"), "inv:y"), btn("❌ " + sc("nahi"), "inv:n")]),
        )
        return
    if st in ("invalid", "not_found", "self", "reciprocal"):
        msg = {
            "invalid": "⚠️ Invite code sirf <b>number</b> hota hai (jaise <code>7315805581</code>).",
            "not_found": "❌ Ye invite code nahi mila. Dost se sahi code puchho.",
            "self": "😅 Apna hi code nahi chalega! Dost ka code bhejo.",
            "reciprocal": "⚠️ Is dost ne pehle hi aapka code lagaya hai — ek doosre ko refer nahi kar sakte.",
        }[st]
        await m.answer(msg + left_txt, reply_markup=invite_retry_kb())
        return
    await clear_state(uid)
    await send_invite_result(uid, res, m.answer)


async def send_invite_result(uid: int, res: dict, send) -> None:
    st = res["status"]
    if st == "need_join":
        await send(
            "📢 <b>Pehle channel join karo</b>, phir dobara code daalo 🙂",
            reply_markup=kb([btn("📢 " + sc("join channel"), url=TASK_CHANNEL_LINK)], [btn("🔁 " + sc("dubara code daalo"), "invite")]),
        )
    elif st == "blocked":
        await send(
            f"⏳ Bahut galat koshish ho gayi. <b>{res.get('hours', 24)} ghante</b> baad dobara try karo 🙏\n"
            f"Madad: {esc(SUPPORT_USERNAME)}",
            reply_markup=back_kb(),
        )
    elif st == "too_old":
        await send(
            f"⌛ Invite code sirf naye users ke liye hai (pehle <b>{res.get('hours', 48)} ghante</b>). "
            "Ab ye lag nahi sakta.\nAap apna code dost ko dekar kamai kar sakte ho 💰",
            reply_markup=kb([btn("💰 " + sc("paise kamao"), "refer")]),
        )
    elif st == "already":
        who = f" <b>{esc(res['ref_name'])}</b> ka" if res.get("ref_name") else ""
        await send(f"ℹ️ Aapne pehle hi{who} invite code laga rakha hai. Dobara nahi lag sakta.", reply_markup=back_kb())
    elif st == "banned":
        await send(f"🚫 Aapka account restricted hai. Support: {esc(SUPPORT_USERNAME)}")
    elif st == "check_failed":
        await send("⏳ Abhi channel check nahi ho pa raha. Thodi der baad dobara try karo 🙏", reply_markup=invite_retry_kb())
    elif st == "need_verify":
        await send("✅ Invite code mil gaya! Bas ek chhota <b>verification</b> baaki hai 👇")
        await send_captcha(uid)
    elif st == "ok":
        extra = (
            f"\n⏳ <b>{esc(res.get('ref_name'))}</b> ko refer {REF_MATURE_DAYS:g} din baad pakka milega."
            if res.get("credited") else ""
        )
        await send(f"🎉 <b>Invite code lag gaya!</b>{extra}\nShukriya 🙏", reply_markup=await user_menu(uid))
    else:
        await send("⚠️ Kuch gadbad hui, thodi der baad try karo.", reply_markup=back_kb())


@router.callback_query(F.data.in_({"inv:y", "inv:n"}))
async def cb_invite_confirm(cb: CallbackQuery):
    uid = cb.from_user.id
    st = await get_state(uid)
    if cb.data == "inv:n":
        await cb.answer()
        await clear_state(uid)
        await safe_edit(cb, "👍 Theek hai, code nahi lagaya.", kb([btn("🔁 " + sc("dusra code"), "invite")], [btn("⬅️ " + sc("menu"), "menu")]))
        return
    if not st or st["name"] != "invite_confirm":
        await cb.answer("⌛ Time khatam — dobara code daalo", show_alert=True)
        return
    await cb.answer()
    code = st["data"].get("code", "")
    await clear_state(uid)
    res = await invite_core(uid, code)

    async def send(text, reply_markup=None):
        await safe_edit(cb, text, reply_markup)

    if res["status"] == "need_verify":
        await safe_edit(cb, "✅ Invite code mil gaya! Bas ek chhota <b>verification</b> baaki hai 👇")
        await send_captcha(uid)
        return
    await send_invite_result(uid, res, send)


# ---------------------------------------------------------------- refer & earn screen
@router.callback_query(F.data == "refer")
async def cb_refer(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    await clear_state(uid)
    u = await users.find_one({"_id": uid}) or {}
    wk = week_key()
    link = ref_link(uid)
    pend_n, pend_p = await ref_pending({"referrals": referrals}, uid, REF_REWARD_PAISE)
    share_text = "🎁 Free Google Play codes jeeto! Mera invite code ya link use karo:"
    pend_line = f"   ⏳ Pending: <b>{pend_n}</b> ({rs(pend_p)})" if pend_n else ""
    text = (
        f"💰 <b>{sc('paise kamao')}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"Dost ko bulao — har <b>pakke dost</b> par <b>{rs(REF_REWARD_PAISE)}</b> 🎁\n"
        f"<i>(dost {REF_MATURE_DAYS:g} din channel me rahe tab pakka)</i>\n\n"
        f"🎟 <b>Aapka Invite Code:</b>\n<code>{uid}</code>\n\n"
        f"🔗 <b>Aapka Link:</b>\n<code>{link}</code>\n\n"
        f"✅ Pakke dost: <b>{u.get('ref_count', 0)}</b>{pend_line}\n"
        f"💼 Balance: <b>{rs(u.get('balance_p', 0))}</b>  (withdraw {rs(MIN_WITHDRAW_PAISE)} se)\n"
        f"🏅 Weekly top 3 ko extra {prizes_line()} ({LB_MIN_REFS}+ refers) — is hafte aapke: <b>{wk_count(u, wk)}</b>"
    )
    rows = [[btn("📤 " + sc("share link"), url=f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}")]]
    rows.append([btn("👥 " + sc("mere dost"), "friends"), btn("💳 " + sc("meri kamai"), "earn")])
    row3 = [btn("💸 " + sc("withdraw"), "w:start"), btn("📋 " + sc("status"), "wstat")]
    rows.append(row3)
    row4 = []
    if not u.get("ref_by"):
        row4.append(btn("🎟 " + sc("invite code daalo"), "invite"))
    row4.append(btn("🏅 " + sc("leaderboard"), "top"))
    rows.append(row4)
    rows.append([btn("⬅️ " + sc("back"), "menu")])
    await safe_edit(cb, text, kb(*rows))


FRIEND_LABEL = {
    "credited": "✅ pakka",
    "pending": "⏳ pending",
    "held": "⏳ check me",
    "verify": "🛡 verify baaki",
    "join": "📢 channel join baaki",
    "cancelled": "❌ cancel",
    "clawback": "❌ cancel",
    "banned": "🚫 band",
}


def friend_line(f: dict) -> str:
    label = FRIEND_LABEL.get(f["status"], f["status"])
    if f["status"] == "pending" and f.get("days_left") is not None:
        label = f"⏳ pending ({f['days_left']} din baaki)"
    return f"• {esc(disp_name(f['name'], 18))} — {label}"


@router.callback_query(F.data == "friends")
async def cb_friends(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    rows = await friend_rows({"users": users, "referrals": referrals}, uid, 20)
    if rows:
        body = "\n".join(friend_line(f) for f in rows)
    else:
        body = "Abhi koi dost nahi juda. Apna invite code ya link share karo 👇"
    await safe_edit(
        cb,
        f"👥 <b>{sc('mere dost')}</b>\n━━━━━━━━━━━━━━━\n{body}\n\n"
        f"<i>Dost {REF_MATURE_DAYS:g} din channel me rahe to refer pakka ho jata hai.</i>",
        kb([btn("⬅️ " + sc("back"), "refer")]),
    )


@router.callback_query(F.data == "earn")
async def cb_earn(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    u = await users.find_one({"_id": uid}, {"balance_p": 1, "earned_p": 1, "withdrawn_p": 1}) or {}
    ents = await ledger_recent(uid, 20)
    body = "\n".join(ledger_line(e) for e in ents) if ents else "Abhi koi entry nahi. Dost bulao aur kamao 💪"
    await safe_edit(
        cb,
        f"💳 <b>{sc('meri kamai')}</b>\n━━━━━━━━━━━━━━━\n"
        f"💼 Balance: <b>{rs(u.get('balance_p', 0))}</b>\n"
        f"💰 Kamaya: {rs(u.get('earned_p', 0))}  ·  💸 Nikala: {rs(u.get('withdrawn_p', 0))}\n\n"
        f"<b>Pichhle 20:</b>\n{body}",
        kb([btn("💸 " + sc("withdraw"), "w:start")], [btn("⬅️ " + sc("back"), "refer")]),
    )


WD_STATUS_TEXT = {
    "pending": "⏳ Admin check kar raha hai",
    "paid": "✅ Bhej diya gaya",
    "confirmed": "✅ Aapko mil gaya",
    "rejected": "❌ Reject — paisa balance me wapas",
    "disputed": "⚠️ Admin dekh raha hai",
}


@router.callback_query(F.data == "wstat")
async def cb_wstat(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    ws = [w async for w in withdrawals.find({"uid": uid}).sort("created_at", -1).limit(3)]
    if not ws:
        body = "Abhi koi withdraw request nahi."
    else:
        body = "\n\n".join(
            f"💰 <b>{rs(w['amount_p'])}</b>  ·  {fmt_ist(w['created_at'])}\n{WD_STATUS_TEXT.get(w['status'], w['status'])}"
            for w in ws
        )
    await safe_edit(
        cb,
        f"📋 <b>{sc('withdraw status')}</b>\n━━━━━━━━━━━━━━━\n{body}\n\n"
        f"🕒 Admin khud bhejta hai, <b>{esc(WD_ETA_TEXT)}</b> me.",
        kb([btn("⬅️ " + sc("back"), "refer")]),
    )


# ---------------------------------------------------------------- weekly leaderboard screen
@router.callback_query(F.data == "top")
async def cb_top(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    wk = week_key()
    top = await weekly_board(wk, 10)
    medals = ["🥇", "🥈", "🥉"]
    if top:
        lines = []
        for i, d in enumerate(top):
            tag = medals[i] if i < 3 else f"{i + 1}."
            prize = f" → <b>₹{LB_PRIZES_RS[i]}</b>" if i < len(LB_PRIZES_RS) and wk_count(d, wk) >= LB_MIN_REFS else ""
            lines.append(f"{tag} {esc(disp_name(d.get('name'), 22))} — <b>{wk_count(d, wk)}</b>{prize}")
        body = "\n".join(lines)
    else:
        body = "Is hafte abhi kisi ke refer nahi — pehle aap bano champion! 🚀"
    me = await users.find_one({"_id": uid}) or {}
    mine = wk_count(me, wk)
    if mine > 0:
        rank = await users.count_documents({f"wkc.{wk}": {"$gt": mine}}) + 1
        you = f"\n\n📍 Aapka rank: <b>#{rank}</b> ({mine} refers)"
        if mine < LB_MIN_REFS:
            you += f"\n⚠️ Prize ke liye {LB_MIN_REFS - mine} refer aur chahiye"
    else:
        you = "\n\n📍 Aapke is hafte 0 refers hain — Refer &amp; Earn se shuru karo!"
    left = week_end_dt() - now_utc()
    await safe_edit(
        cb,
        f"🏅 <b>{sc('weekly leaderboard')}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎁 Prize: {prizes_line()}  (top 3, {LB_MIN_REFS}+ refers)\n"
        f"⏳ Hafta khatam: <b>{fmt_td(left)}</b> baad (Sunday)\n\n"
        f"{body}{you}",
        kb([btn("💰 " + sc("refer & earn"), "refer")], [btn("⬅️ " + sc("back"), "menu")]),
    )


# ---------------------------------------------------------------- about
@router.callback_query(F.data == "about")
async def cb_about(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    await safe_edit(
        cb,
        f"ℹ️ <b>{sc('about us')}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎁 <b>{BOT_NAME}</b> par free Google Play codes ke giveaway aur drops hote hain.\n\n"
        "✅ 100% FREE — OTP, password ya card detail kabhi nahi maangte.\n"
        "🏆 Har winner aur har payment ka proof channel par aata hai.\n\n"
        f"👤 Support: {esc(SUPPORT_USERNAME)}",
        kb(
            [btn("👤 " + sc("contact") + f" {SUPPORT_USERNAME}", url=SUPPORT_LINK)],
            [btn("📢 " + sc("channel"), url=TASK_CHANNEL_LINK), btn("👥 " + sc("group"), url=GROUP_LINK)],
            [btn("🏆 " + sc("pichhle winners"), "winners"), btn("📋 " + sc("rules & faq"), "faq")],
            *bot_video_row(),
            [btn("⬅️ " + sc("back"), "menu")],
        ),
    )


FAQ_TEXT = (
    "📋 <b>Rules &amp; FAQ</b>\n\n"
    "<b>Kya sach me free hai?</b>\nHaan. Yahan kabhi paise nahi maange jaate.\n\n"
    "<b>Winner kaise chuna jata hai?</b>\nRandom. Jiske paas zyada 🎟 chance, uske chunne ke mauke zyada.\n\n"
    "<b>Refer ka paisa kab milta hai?</b>\n"
    f"Dost verify + channel join kare, phir <b>{REF_MATURE_DAYS:g} din</b> channel me rahe — tab pakka. "
    "Tab tak 'pending' dikhta hai.\n\n"
    "<b>Invite code kab laga sakte hain?</b>\n"
    f"Sirf naye user, pehle <b>{INVITE_MAX_AGE_HOURS:g} ghante</b> me, aur ek hi baar.\n\n"
    "<b>Withdraw kaise?</b>\n"
    f"Balance <b>{rs(MIN_WITHDRAW_PAISE)}</b> se. Admin khud paisa bhejta hai, <b>{esc(WD_ETA_TEXT)}</b> me. "
    "Bhejte hi proof channel par aata hai.\n\n"
    "<b>Kya galat hai?</b>\n"
    "Fake account, khud ko refer, doosre ka code chura kar lagana = refer cancel, ban. "
    "Paisa kabhi bina message aur record ke nahi katta.\n\n"
    "🆘 Dikkat ho to <b>Problem batao</b> dabao."
)


@router.callback_query(F.data == "faq")
async def cb_faq(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    await safe_edit(
        cb, FAQ_TEXT,
        kb([btn("🆘 " + sc("problem batao"), "report")], [btn("⬅️ " + sc("back"), "help")]),
    )


# ---------------------------------------------------------------- problem report
_report_times: dict = {}


async def start_report(uid: int) -> None:
    await set_state(uid, "report", ttl_min=15)
    await bot.send_message(
        uid,
        "🆘 <b>Problem batao</b>\n\nApni dikkat ek message me likho (screenshot bhi bhej sakte ho) 👇\n<i>Cancel: /cancel</i>",
    )


@router.callback_query(F.data == "report")
async def cb_report(cb: CallbackQuery):
    await cb.answer()
    await touch_user(cb.from_user)
    await start_report(cb.from_user.id)


async def handle_report(m: Message) -> None:
    uid = m.from_user.id
    text = (m.text or m.caption or "").strip()
    if not text and not m.photo:
        await m.answer("⚠️ Likh kar ya screenshot bhej kar batao 🙏")
        return
    dq = _report_times.setdefault(uid, deque(maxlen=10))
    recent = [t for t in dq if time.monotonic() - t < 3600]
    if len(recent) >= REPORT_PER_HOUR:
        await clear_state(uid)
        await m.answer("⏳ Aapne abhi kaafi reports bhej di hain. Thodi der baad dobara batao 🙏", reply_markup=back_kb())
        return
    dq.append(time.monotonic())
    await clear_state(uid)
    head = (
        "🆘 <b>Problem Report</b>\n\n"
        f"👤 {mention(uid, m.from_user.full_name)}  (<code>{uid}</code>)"
        + (f"  @{esc(m.from_user.username)}" if m.from_user.username else "")
        + f"\n\n{esc(text[:1500])}\n\nCheck: <code>/balance {uid}</code>"
    )
    for aid in sorted(STAFF):
        await deliver(aid, lambda cid: bot.send_message(cid, head))
        if m.photo:
            await deliver(aid, lambda cid: bot.copy_message(cid, m.chat.id, m.message_id))
    await m.answer(
        f"✅ <b>Aapki baat admin tak pahunch gayi.</b>\nJaldi jawab milega 🙏\nZaroorat ho to: {esc(SUPPORT_USERNAME)}",
        reply_markup=back_kb(),
    )


# ---------------------------------------------------------------- withdraw
METHOD_LABEL = {"upi": "UPI ID", "bank": "Bank Account", "mobile": "Mobile No."}
UPI_RE = re.compile(r"^[A-Za-z0-9._\-]{2,64}@[A-Za-z][A-Za-z0-9.\-]{1,31}$")
MOBILE_RE = re.compile(r"^(?:\+?91)?([6-9]\d{9})$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def clean_payout(method: str, detail: str, holder: str) -> tuple:
    """(clean_dict, '') ya (None, 'name' | 'detail')."""
    holder = " ".join(str(holder or "").split())
    if not (3 <= len(holder) <= 60) or any(ch.isdigit() for ch in holder):
        return None, "name"
    detail = str(detail or "").strip()
    if method == "upi":
        if not UPI_RE.match(detail):
            return None, "detail"
        val = detail
    elif method == "mobile":
        m = MOBILE_RE.match(re.sub(r"[\s\-]", "", detail))
        if not m:
            return None, "detail"
        val = m.group(1)
    elif method == "bank":
        toks = detail.replace(",", " ").replace("|", " ").split()
        acct = next((t for t in toks if t.isdigit() and 9 <= len(t) <= 18), None)
        ifsc = next((t.upper() for t in toks if IFSC_RE.match(t.upper())), None)
        if not acct or not ifsc:
            return None, "detail"
        val = f"A/C {acct} | IFSC {ifsc}"
    else:
        return None, "detail"
    return {"method": method, "detail": val, "holder": holder}, ""


async def withdraw_core(uid: int, method: str, detail: str, holder: str) -> dict:
    """Pura balance withdraw request me jata hai. DB me save pehle, admin notify baad me (queue jaisa)."""
    if STATUS["degraded"]:
        return {"status": "busy"}
    u = await users.find_one({"_id": uid}, {"name": 1, "username": 1, "banned": 1, "balance_p": 1})
    if not u:
        return {"status": "unregistered"}
    if u.get("banned"):
        return {"status": "banned"}
    clean, err = clean_payout(method, detail, holder)
    if not clean:
        return {"status": "invalid", "field": err}
    if await withdrawals.find_one({"uid": uid, "status": "pending"}):
        return {"status": "has_pending"}
    wid = f"{uid}-{int(time.time() * 1000)}-{random.randint(100, 999)}"
    bal = 0
    for _ in range(3):  # balance badalte hi retry (double-spend se bachne ke liye — debit atomic hai)
        cur = await users.find_one({"_id": uid}, {"balance_p": 1}) or {}
        bal = int(cur.get("balance_p", 0))
        if bal < MIN_WITHDRAW_PAISE:
            return {"status": "low", "balance_p": bal, "min_p": MIN_WITHDRAW_PAISE}
        res = await wallet_apply(uid, -bal, "withdraw", ref=wid, note=clean["method"].upper())
        if res["ok"]:
            break
        if res["reason"] == "dup":
            return {"status": "busy"}
    else:
        return {"status": "busy"}
    w = {
        "_id": wid, "uid": uid, "name": u.get("name"), "username": u.get("username"),
        "amount_p": bal, "method": clean["method"], "detail": clean["detail"], "holder": clean["holder"],
        "status": "pending", "created_at": now_utc(), "admin_notified": False,
    }
    try:
        await withdrawals.insert_one(w)
    except Exception:
        await wallet_apply(uid, bal, "refund", ref=f"fail:{wid}", note="withdraw request save nahi hui")  # paisa wapas
        logger.exception("withdraw insert fail")
        return {"status": "busy"}
    site_invalidate(uid)
    spawn(notify_withdrawal(w))
    return {"status": "ok", "id": wid, "amount_p": bal}


async def notify_withdrawal(w: dict, reminder: bool = False, from_list: bool = False, only: Optional[int] = None) -> None:
    """Withdraw card SAB admins ko (only=<id> ho to ek ko). Jo pehle Paid/Reject dabaye uska record."""
    u = await users.find_one({"_id": w["uid"]}) or {}
    flag = "\n⚠️ <b>Fraud flag</b> — pehle check kar lein!" if u.get("ref_flag") else ""
    head = "⏰ <b>REMINDER — Withdraw pending</b>" if reminder else "💸 <b>New Withdraw Request</b>"
    text = (
        f"{head}\n\n"
        f"👤 {mention(w['uid'], w.get('name'))}  (<code>{w['uid']}</code>)\n"
        f"💰 Amount: <b>{rs(w['amount_p'])}</b>\n"
        f"🏦 {METHOD_LABEL.get(w['method'], w['method'])}: <code>{esc(w['detail'])}</code>\n"
        f"🧾 Name: <b>{esc(w['holder'])}</b>\n"
        f"📊 Refers: {u.get('ref_count', 0)} · Total earned: {rs(u.get('earned_p', 0))}\n"
        f"🕒 {fmt_ist(w['created_at'])}{flag}"
    )
    markup = kb(
        [btn("✅ Paid kar diya", f"wa:paid:{w['_id']}"), btn("❌ Reject", f"wa:rej:{w['_id']}")],
        [btn("👥 Refers dekho", f"ar:{w['uid']}")],
    )
    ok_any = False
    for aid in ([only] if only else sorted(STAFF)):
        res, msg = await deliver_result(aid, lambda cid: bot.send_message(cid, text, reply_markup=markup))
        if res == OK and msg is not None:
            ok_any = True
            await withdrawals.update_one({"_id": w["_id"]}, {"$set": {f"admin_msgs.{aid}": msg.message_id}})
    if ok_any and not from_list:
        await withdrawals.update_one(
            {"_id": w["_id"]}, {"$set": {"admin_notified": True, "remind_at": now_utc() + timedelta(hours=6)}}
        )


async def sync_admin_cards(wid: str, text: str) -> None:
    """Kisi ek admin ne kaam kar diya: baaki admins ke card se buttons hata do (already done)."""
    w = await withdrawals.find_one({"_id": wid}) or {}
    for aid, mid in (w.get("admin_msgs") or {}).items():
        try:
            await bot.edit_message_text(text, chat_id=int(aid), message_id=int(mid))
        except TelegramAPIError:
            pass


def mask_payout(method: str, detail: str) -> str:
    d = str(detail or "").strip()
    if method == "upi" and "@" in d:
        name, _, handle = d.partition("@")
        return f"{name[:2]}***@{handle}"
    if method == "mobile":
        digits = re.sub(r"\D", "", d)[-10:]
        return f"{digits[:2]}******{digits[-2:]}" if len(digits) >= 4 else "******"
    acct = re.sub(r"\D", "", d.split()[0]) if d.split() else ""
    return "••••" + acct[-4:] if acct else "••••"


async def post_proof(w: dict) -> None:
    """Paid hote hi proof channel par post (UPI/account masked)."""
    _paid_cache["t"] = -1e9
    total_p, n = await paid_stats()
    text = (
        "✅ <b>Payment Proof</b>\n\n"
        f"💰 Amount: <b>{rs(w['amount_p'])}</b>\n"
        f"🏦 {METHOD_LABEL.get(w['method'], w['method'])}: <code>{esc(mask_payout(w['method'], w['detail']))}</code>\n"
        f"👤 {esc(mask_name(w.get('name')))}\n"
        f"🕒 {fmt_ist(now_utc())}\n\n"
        f"📊 Ab tak total paid: <b>{rs(total_p)}</b> ({n} payments)\n"
        f"🤖 {BOT_LINK}"
    )
    res, msg = await deliver_result(PROOF_CHANNEL_ID, lambda cid: bot.send_message(cid, text))
    if res == OK and msg is not None:
        await withdrawals.update_one({"_id": w["_id"]}, {"$set": {"proof_msg_id": msg.message_id}})
    else:
        spawn(alert_admin(
            "proof_fail",
            "⚠️ Payment proof channel me post nahi hua. Bot ko proof channel me <b>admin</b> banayein "
            "(PROOF_CHANNEL_ID / TASK_CHANNEL_ID).",
            cooldown=3600,
        ))


async def withdraw_watch_once() -> int:
    """Pending queue: jinki admin ko khabar nahi gayi (ya reminder due hai) unhe dobara bhejo."""
    now = now_utc()
    n = 0
    fresh = [
        w async for w in withdrawals.find(
            {"status": "pending", "admin_notified": {"$ne": True}, "created_at": {"$lte": now - timedelta(seconds=90)}}
        ).limit(10)
    ]
    for w in fresh:
        await notify_withdrawal(w)
        n += 1
    due = [w async for w in withdrawals.find({"status": "pending", "remind_at": {"$lte": now}}).limit(10)]
    for w in due:
        await withdrawals.update_one({"_id": w["_id"]}, {"$set": {"remind_at": now + timedelta(hours=6)}})
        await notify_withdrawal(w, reminder=True)
        n += 1
    return n


async def withdraw_watch_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await withdraw_watch_once()
        except Exception:
            logger.exception("withdraw_watch_loop")


def wd_methods_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("📲 " + sc("upi id"), "w:m:upi")],
        [btn("🏦 " + sc("bank account"), "w:m:bank"), btn("📞 " + sc("mobile no."), "w:m:mobile")],
        [btn("⬅️ " + sc("back"), "refer")],
    )


WD_DETAIL_PROMPT = {
    "upi": "📲 Apni <b>UPI ID</b> bhejo (jaise <code>name@okhdfcbank</code>):",
    "mobile": "📞 Apna <b>mobile number</b> bhejo (10 digit, UPI wala):",
    "bank": "🏦 <b>Account number</b> aur <b>IFSC</b> ek message me bhejo\n(jaise <code>123456789012 SBIN0001234</code>):",
}


@router.callback_query(F.data == "w:start")
async def cb_wd_start(cb: CallbackQuery):
    uid = cb.from_user.id
    await cb.answer()
    await touch_user(cb.from_user)
    await clear_state(uid)
    u = await users.find_one({"_id": uid}) or {}
    bal = int(u.get("balance_p", 0))
    back = kb([btn("⬅️ " + sc("back"), "refer")])
    if u.get("banned"):
        await safe_edit(cb, f"🚫 Aapka account restricted hai. Support: {esc(SUPPORT_USERNAME)}", back)
        return
    pend = await withdrawals.find_one({"uid": uid, "status": "pending"})
    if pend:
        await safe_edit(
            cb,
            f"⏳ <b>Aapki ek withdraw request pending hai</b>\n\n💰 {rs(pend['amount_p'])}\n"
            f"🕒 Bheji: {fmt_ist(pend['created_at'])}\n"
            f"Admin khud bhejta hai, <b>{esc(WD_ETA_TEXT)}</b> me aa jata hai 🙏",
            back,
        )
        return
    if bal < MIN_WITHDRAW_PAISE:
        need = MIN_WITHDRAW_PAISE - bal
        await safe_edit(
            cb,
            f"💼 Aapka balance: <b>{rs(bal)}</b>\n\n"
            f"Withdraw ke liye kam se kam <b>{rs(MIN_WITHDRAW_PAISE)}</b> chahiye — abhi <b>{rs(need)}</b> aur kamao 💪\n"
            "Refer karo, weekly leaderboard jeeto, reward cards claim karo!",
            back,
        )
        return
    await safe_edit(
        cb,
        f"💸 <b>{sc('withdraw')}</b>\n\n💼 Balance: <b>{rs(bal)}</b>\n"
        "Poora balance ek baar me nikalega.\n\n<b>Paisa kahan chahiye?</b> 👇",
        wd_methods_kb(),
    )


@router.callback_query(F.data.startswith("w:m:"))
async def cb_wd_method(cb: CallbackQuery):
    uid = cb.from_user.id
    method = cb.data.split(":", 2)[2]
    if method not in METHOD_LABEL:
        await cb.answer()
        return
    await cb.answer()
    await set_state(uid, "wd_detail", {"method": method}, ttl_min=15)
    await safe_edit(
        cb, WD_DETAIL_PROMPT[method] + "\n\n<i>Cancel: /cancel</i>", kb([btn("⬅️ " + sc("back"), "w:start")])
    )


async def handle_wd_detail(m: Message, st: dict) -> None:
    uid = m.from_user.id
    method = st["data"].get("method")
    text = (m.text or "").strip()
    probe, err = clean_payout(method, text, "Test Name")
    if not probe:
        await m.answer("⚠️ Ye sahi nahi lag raha. Format dekho aur dobara bhejo:\n\n" + WD_DETAIL_PROMPT.get(method, ""))
        return
    await set_state(uid, "wd_name", {"method": method, "detail": text}, ttl_min=15)
    await m.answer(
        "🧾 Ab us account / UPI par jo <b>sahi naam</b> hai wahi bhejo.\n"
        "<i>(Naam match nahi hua to payment nahi hoga)</i>"
    )


async def handle_wd_name(m: Message, st: dict) -> None:
    uid = m.from_user.id
    data = st["data"]
    clean, err = clean_payout(data.get("method"), data.get("detail"), m.text or "")
    if not clean:
        if err == "name":
            await m.answer("⚠️ Naam sahi bhejo (sirf letters, 3 se 60 akshar, number nahi).")
        else:
            await clear_state(uid)
            await m.answer("⚠️ Detail sahi nahi thi. Dobara shuru karo 👇", reply_markup=wd_methods_kb())
        return
    await set_state(uid, "wd_confirm", clean, ttl_min=15)
    u = await users.find_one({"_id": uid}, {"balance_p": 1}) or {}
    await m.answer(
        f"💸 <b>{sc('confirm withdraw')}</b>\n\n"
        f"💰 Amount: <b>{rs(u.get('balance_p', 0))}</b>\n"
        f"🏦 {METHOD_LABEL[clean['method']]}: <code>{esc(clean['detail'])}</code>\n"
        f"🧾 Name: <b>{esc(clean['holder'])}</b>\n\n"
        f"🕒 Paisa <b>{esc(WD_ETA_TEXT)}</b> me aayega.\n\nSab sahi hai na? 👇",
        reply_markup=kb([btn("✅ " + sc("confirm"), "w:ok"), btn("❌ " + sc("cancel"), "w:no")]),
    )


@router.callback_query(F.data == "w:no")
async def cb_wd_cancel(cb: CallbackQuery):
    await cb.answer("Cancel ho gaya")
    await clear_state(cb.from_user.id)
    await safe_edit(cb, "❌ Withdraw cancel ho gaya.", kb([btn("⬅️ " + sc("back"), "refer")]))


@router.callback_query(F.data == "w:ok")
async def cb_wd_confirm(cb: CallbackQuery):
    uid = cb.from_user.id
    st = await get_state(uid)
    if not st or st["name"] != "wd_confirm":
        await cb.answer("⌛ Expire ho gaya — dobara shuru karo", show_alert=True)
        return
    await cb.answer()
    d = st["data"]
    await clear_state(uid)
    res = await withdraw_core(uid, d["method"], d["detail"], d["holder"])
    back = kb([btn("⬅️ " + sc("back"), "refer")])
    s = res["status"]
    if s == "ok":
        await safe_edit(
            cb,
            f"✅ <b>Request bhej di!</b>\n\n💰 {rs(res['amount_p'])}\n"
            f"🕒 Admin <b>{esc(WD_ETA_TEXT)}</b> me bhej dega. Bhejte hi yahan message aayega 🙏",
            back,
        )
    elif s == "has_pending":
        await safe_edit(cb, "⏳ Aapki ek request pehle se pending hai.", back)
    elif s == "low":
        await safe_edit(cb, f"💼 Balance kam hai ({rs(res.get('balance_p', 0))}). Min {rs(MIN_WITHDRAW_PAISE)} chahiye.", back)
    elif s == "banned":
        await safe_edit(cb, f"🚫 Account restricted hai. Support: {esc(SUPPORT_USERNAME)}", back)
    else:
        await safe_edit(cb, "⚠️ Abhi thodi dikkat hai. Aapka paisa safe hai — thodi der baad dobara try karo 🙏", back)


# ---------------------------------------------------------------- withdraw: admin buttons
async def wd_admin_view(w: dict) -> str:
    return (
        f"👤 {mention(w['uid'], w.get('name'))}  (<code>{w['uid']}</code>)\n"
        f"💰 <b>{rs(w['amount_p'])}</b> → {METHOD_LABEL.get(w['method'], w['method'])}: <code>{esc(w['detail'])}</code>\n"
        f"🧾 {esc(w['holder'])}"
    )


def staff_back_kb() -> InlineKeyboardMarkup:
    return kb([btn("⬅️ Pending list", "wa:list")])


def who_did(w: dict) -> str:
    return esc(w.get("by_name") or str(w.get("by") or "kisi admin"))


@router.callback_query(F.data.startswith("wa:"))
async def cb_wd_admin(cb: CallbackQuery):
    me = cb.from_user.id
    if not is_staff(me):
        await cb.answer("⛔ Sirf admin ke liye", show_alert=True)
        return
    await cb.answer()
    parts = cb.data.split(":", 2)
    action = parts[1]
    wid = parts[2] if len(parts) > 2 else ""
    if action == "list":
        pend = [w async for w in withdrawals.find({"status": "pending"}).sort("created_at", 1).limit(10)]
        total = await withdrawals.count_documents({"status": "pending"})
        if not pend:
            await safe_edit(cb, "💸 <b>Withdrawals</b>\n\n✅ Koi pending request nahi.", None)
            return
        await safe_edit(cb, f"💸 <b>Pending withdrawals: {total}</b>\nNeeche har request ka card aa raha hai 👇", None)
        for w in pend:
            await notify_withdrawal(w, from_list=True, only=me)
        return
    w = await withdrawals.find_one({"_id": wid})
    if not w:
        await bot.send_message(me, "⚠️ Ye withdraw request nahi mili.")
        return
    info = await wd_admin_view(w)
    if action in ("paid", "rej", "resend") and w["status"] not in ("pending", "disputed"):
        extra = f" (<b>{who_did(w)}</b> ne)" if w.get("by") else ""
        await bot.send_message(me, f"ℹ️ Ye request pehle hi <b>{esc(w['status'])}</b> ho chuki hai{extra}.")
        return
    if action == "paid":
        await bot.send_message(
            me,
            f"✅ Kya aapne ye paisa <b>bhej diya</b>?\n\n{info}",
            reply_markup=kb([btn("✅ Haan, bhej diya", f"wa:paidy:{wid}")], [btn("↩️ Wapas", "wa:list")]),
        )
    elif action == "paidy":
        got = await withdrawals.find_one_and_update(
            {"_id": wid, "status": "pending"},
            {"$set": {"status": "paid", "paid_at": now_utc(), "by": me, "by_name": cb.from_user.full_name}},
        )
        if not got:
            cur = await withdrawals.find_one({"_id": wid}) or {}
            await bot.send_message(me, f"ℹ️ Ye pehle hi <b>{who_did(cur)}</b> ne process kar di hai (already done).")
            return
        await users.update_one({"_id": w["uid"]}, {"$inc": {"withdrawn_p": w["amount_p"]}})
        site_invalidate(w["uid"])
        await ask_user_confirm(w)
        await bot.send_message(
            me, f"✅ <b>Paid mark ho gaya.</b> User se confirmation maangi gayi.\n\n{info}", reply_markup=staff_back_kb()
        )
        spawn(sync_admin_cards(wid, f"✅ <b>Paid</b> — {esc(cb.from_user.full_name)} ne bhej diya.\n\n{info}"))
        spawn(post_proof({**w, "status": "paid"}))
        await safe_log(f"💸 <b>Withdraw Paid</b> (by {esc(cb.from_user.full_name)})\n\n{info}")
    elif action == "resend":
        await ask_user_confirm(w)
        await bot.send_message(me, "📨 User se dobara confirmation maangi gayi.", reply_markup=staff_back_kb())
    elif action == "rej":
        await bot.send_message(
            me,
            f"❌ Ye request <b>reject</b> karein? Paisa user ke balance me wapas chala jayega.\n\n{info}",
            reply_markup=kb([btn("✅ Haan, Reject", f"wa:rejy:{wid}")], [btn("↩️ Wapas", "wa:list")]),
        )
    elif action == "rejy":
        got = await withdrawals.find_one_and_update(
            {"_id": wid, "status": "pending"},
            {"$set": {"status": "rejected", "rejected_at": now_utc(), "by": me, "by_name": cb.from_user.full_name}},
        )
        if not got:
            cur = await withdrawals.find_one({"_id": wid}) or {}
            await bot.send_message(me, f"ℹ️ Ye pehle hi <b>{who_did(cur)}</b> ne process kar di hai (already done).")
            return
        await wallet_apply(w["uid"], w["amount_p"], "refund", ref=f"rej:{wid}", note="withdraw reject", by=me)
        await deliver(
            w["uid"],
            lambda cid: bot.send_message(
                cid,
                f"❌ Aapki <b>{rs(w['amount_p'])}</b> withdraw request verify nahi ho paayi.\n"
                f"Paisa aapke balance me <b>wapas aa gaya</b> hai 💼\nMadad ke liye: {esc(SUPPORT_USERNAME)}",
            ),
        )
        await bot.send_message(me, "✅ Reject ho gaya, paisa user ke balance me wapas.", reply_markup=staff_back_kb())
        spawn(sync_admin_cards(wid, f"❌ <b>Reject</b> — {esc(cb.from_user.full_name)} ne reject kiya.\n\n{info}"))


async def ask_user_confirm(w: dict) -> None:
    await deliver(
        w["uid"],
        lambda cid: bot.send_message(
            cid,
            f"💸 <b>{rs(w['amount_p'])} aapko bhej diye gaye hain!</b>\n\n"
            f"{METHOD_LABEL.get(w['method'], w['method'])}: <code>{esc(w['detail'])}</code>\n\n"
            "Apna account check karo — paise <b>mil gaye</b>? 👇",
            reply_markup=kb(
                [btn("✅ " + sc("haan, mil gaye"), f"wc:yes:{w['_id']}"), btn("❌ " + sc("nahi mile"), f"wc:no:{w['_id']}")]
            ),
        ),
    )


@router.callback_query(F.data.startswith("wc:"))
async def cb_wd_user_confirm(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    if len(parts) < 3:
        await cb.answer()
        return
    ans, wid = parts[1], parts[2]
    w = await withdrawals.find_one({"_id": wid})
    if not w or w["uid"] != cb.from_user.id:
        await cb.answer("⚠️ Ye request nahi mili", show_alert=True)
        return
    if w["status"] not in ("paid", "disputed"):
        await cb.answer("ℹ️ Ye pehle hi ho chuka hai", show_alert=True)
        return
    await cb.answer()
    who = f"{mention(w['uid'], w.get('name'))} (<code>{w['uid']}</code>)"
    if ans == "yes":
        await withdrawals.update_one(
            {"_id": wid}, {"$set": {"status": "confirmed", "user_confirm": "yes", "confirmed_at": now_utc()}}
        )
        site_invalidate(w["uid"])
        await safe_edit(cb, f"✅ <b>Shukriya!</b> {rs(w['amount_p'])} mil gaye 🎉\nAise hi kamate raho 💪", back_kb())
        await notify_admin(f"✅ <b>User ne confirm kiya</b>: paise mil gaye\n\n{who}\n💰 {rs(w['amount_p'])}")
        await safe_log(f"✅ <b>Withdraw Confirmed by user</b>\n\n{who}\n💰 {rs(w['amount_p'])}")
    else:
        await withdrawals.update_one(
            {"_id": wid}, {"$set": {"status": "disputed", "user_confirm": "no", "disputed_at": now_utc()}}
        )
        site_invalidate(w["uid"])
        await safe_edit(
            cb,
            "🙏 Maaf kijiye! Humne admin ko bata diya hai, wo jaldi check karke aapse baat karenge.\n"
            f"Zaroorat ho to: {esc(SUPPORT_USERNAME)}",
            back_kb(),
        )
        await notify_admin(
            f"⚠️ <b>User ne kaha: paise NAHI mile</b>\n\n{who}\n💰 {rs(w['amount_p'])} → <code>{esc(w['detail'])}</code>\n\n"
            "Check karke dobara bhejo, phir niche button dabao.",
            kb([btn("📨 Dobara confirm maango", f"wa:resend:{wid}")]),
        )


# ---------------------------------------------------------------- weekly leaderboard prize (Sunday 00:00 IST)
async def settle_weekly_once() -> None:
    if not LB_PRIZES_RS:
        return
    cur_wk = week_key()
    nxt_wk = (week_start_ist() + timedelta(days=7)).isoformat()
    prev = (week_start_ist() - timedelta(days=7)).isoformat()
    for k in (prev, cur_wk, nxt_wk):  # index pehle se ready (rollover par slow query na ho)
        await ensure_week_index(k)
    doc_id = f"lbweek:{prev}"
    old = await config.find_one({"_id": doc_id})
    if old and old.get("done"):
        return
    rows = await weekly_board(prev, limit=len(LB_PRIZES_RS))
    paid = []
    for i, d in enumerate(rows):
        cnt = wk_count(d, prev)
        if cnt < LB_MIN_REFS:
            break
        prize_p = LB_PRIZES_RS[i] * 100
        if d.get("ref_flag"):  # fraud flag: auto prize nahi, admin check kare
            spawn(alert_admin(
                f"lbflag:{prev}:{d['_id']}",
                f"⚠️ Weekly leaderboard #{i + 1}: {mention(d['_id'], d.get('name'))} (<code>{d['_id']}</code>) "
                f"— {cnt} refers, par <b>fraud flag</b> hai. Prize {rs(prize_p)} roka gaya — manual check karein.",
                cooldown=0,
            ))
            continue
        wres = await wallet_apply(d["_id"], prize_p, "leaderboard", ref=f"{prev}:{d['_id']}", note=f"#{i + 1} week {prev}")
        fresh = bool(wres["ok"])  # dup = pehle hi credit ho chuka
        if fresh:
            try:
                await config.insert_one({"_id": f"lbpay:{prev}:{d['_id']}", "uid": d["_id"], "rank": i + 1, "prize_p": prize_p, "at": now_utc()})
            except DuplicateKeyError:
                pass
        paid.append((i + 1, d, cnt, prize_p, fresh))
    try:
        res = await config.update_one(
            {"_id": doc_id, "done": {"$ne": True}},
            {"$set": {"done": True, "at": now_utc(), "winners": [x[1]["_id"] for x in paid]}},
            upsert=True,
        )
    except DuplicateKeyError:
        return  # kisi aur ne finish kar diya
    if not (res.modified_count or res.upserted_id is not None):
        return
    if not paid:
        return
    medals = ["🥇", "🥈", "🥉"]
    start = date.fromisoformat(prev)
    lines = [
        f"{medals[r - 1] if r <= 3 else str(r) + '.'} {mention(d['_id'], d.get('name'))} — <b>{cnt}</b> refers → <b>₹{p // 100}</b>"
        for r, d, cnt, p, _f in paid
    ]
    await deliver(
        TASK_CHANNEL_ID,
        lambda cid: bot.send_message(
            cid,
            f"🏅 <b>{sc('weekly leaderboard result')}</b> 🏅\n"
            f"<i>{start.strftime('%d %b')} – {(start + timedelta(days=7)).strftime('%d %b')}</i>\n\n"
            "<blockquote>" + "\n".join(lines) + "</blockquote>\n\n"
            "✅ Prize unke bot balance me add ho gaya.\n"
            f"💰 Is hafte ka top 3 aap bano! Refer karo: https://t.me/{BOT_USERNAME}",
        ),
    )
    for r, d, cnt, p, fresh in paid:
        if fresh:
            spawn(deliver(
                d["_id"],
                lambda cid, r=r, p=p: bot.send_message(
                    cid,
                    f"🏅 <b>Badhai ho!</b> Pichhle hafte aap leaderboard me <b>#{r}</b> rahe 🎉\n"
                    f"💰 <b>₹{p // 100}</b> aapke balance me add ho gaye!",
                ),
            ))
    await safe_log("🏅 <b>Weekly Leaderboard Paid</b>\n\n" + "\n".join(lines))


async def weekly_lb_loop() -> None:
    while True:
        try:
            await settle_weekly_once()
        except Exception:
            logger.exception("weekly_lb_loop")
        await asyncio.sleep(60)


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
        nm = mention(w["uid"], w.get("name")) if links else f"<b>{esc(disp_name(w.get('name'), 28))}</b>"
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
    return kb([btn("🔔 Remind Me", f"drop:remind:{no}")], [btn("📱 Open App", url=app_link())], *drop_video_row())


def live_kb(no: int, lucky: bool = False) -> InlineKeyboardMarkup:
    return kb([btn("🎲 JOIN LUCKY DRAW" if lucky else "🎁 CLAIM NOW", f"drop:claim:{no}")], [btn("📱 Open App", url=app_link())], *drop_video_row())


def done_kb() -> InlineKeyboardMarkup:
    return kb([btn("📱 Open App", url=app_link())], *drop_video_row())


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
            reply_markup=kb([btn("📱 Open App", web_app=WEBSITE_URL)], *drop_video_row()),
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
        "invite": invite_core, "withdraw": withdraw_core,
    }
    site_ctx["hooks"]["paid_stats"] = paid_stats

    # Mini App + health server pehle start (Koyeb health check pass ho)
    runner = await site_app.start_server(site_ctx, PORT)
    await init_db()
    await ledger_opening_once()

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
    spawn(withdraw_watch_loop())
    spawn(weekly_lb_loop())
    spawn(referral_watch_loop())
    spawn(autopost_loop())
    spawn(newuser_log_loop())
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
