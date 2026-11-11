"""
site_app.py — Telegram Mini App server for ASB FreeCodes Bot (aiohttp)

Routes
  GET  /                    -> Mini App page (static/index.html)
  GET  /health              -> plain "OK" (Koyeb health check + UptimeRobot monitor)
  GET  /api/state           -> bahut halka live drop status (sirf memory, DB nahi)
  POST /api/app             -> sab tabs ka data
  POST /api/claim           -> drop claim / lucky join
  POST /api/daily           -> daily bonus
  POST /api/remind          -> drop reminder ON
  POST /api/reward/redeem   -> reward card CLAIM (paisa seedha profile balance me)
  POST /api/invite          -> invite code lagao (referrer ki Telegram ID)
  POST /api/withdraw        -> withdraw request (UPI / bank / mobile)
  POST /api/settings        -> user settings (streak reminder)

Har POST me Telegram ka signed `initData` chahiye — bina Telegram ke koi data nahi dekh sakta.
Free tier ke liye: shared data cache, per-user cache, concurrency cap, rate limits.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

logger = logging.getLogger("asb-web")

BASE_DIR = Path(__file__).parent
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------- helpers
def mask_name(name) -> str:
    """'Ravi Kumar' -> 'Ra***' (privacy ke liye)."""
    n = str(name or "").strip() or "User"
    return (n[:2] if len(n) > 2 else n[:1]) + "***"


def short_name(name) -> str:
    """'Ravi Kumar Singh' -> 'Ravi' (public lists me sirf pehla naam)."""
    parts = str(name or "").strip().split()
    return (parts[0] if parts else "User")[:14]


def disp_name(name, n: int = 26) -> str:
    """Poora naam (channel / mini app results me) — bahut lamba ho to kaat do."""
    s = " ".join(str(name or "").split()) or "User"
    return s if len(s) <= n else s[: n - 1] + "…"


def week_start_ist(dt=None):
    """Hafta Sunday (IST) se shuru hota hai. Return: us Sunday ki date."""
    base = dt or datetime.now(timezone.utc)
    d = base.astimezone(IST).date()
    return d - timedelta(days=(d.weekday() + 1) % 7)  # Mon=0 .. Sun=6  ->  Sunday par 0


def week_key(dt=None) -> str:
    """Hafte ki key, jaise '2026-11-08' (us Sunday ki date)."""
    return week_start_ist(dt).isoformat()


def week_end_dt(dt=None):
    """Is hafte ka khatam hone ka time = agla Sunday 00:00 IST."""
    start = week_start_ist(dt) + timedelta(days=7)
    return datetime(start.year, start.month, start.day, tzinfo=IST)


def iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def video_label(url: str) -> str:
    u = (url or "").lower()
    if "youtu" in u:
        return "▶️ YouTube par dekho"
    if "instagram" in u:
        return "📸 Instagram par dekho"
    return "🔗 Video dekho"


def link_label(label, url) -> str:
    """Platform ka naam: admin ne diya ho to wahi, warna link se pehchan."""
    label = (label or "").strip()
    if label:
        return label
    u = (url or "").lower()
    if "youtu" in u:
        return "YouTube"
    if "instagram" in u:
        return "Instagram"
    if "t.me" in u or "telegram" in u:
        return "Telegram"
    if "facebook" in u or "fb.com" in u or "fb.watch" in u:
        return "Facebook"
    return "Link"


def link_text(link: dict) -> str:
    """Button ka text, jaise '📸 Instagram par dekho'."""
    label = link_label(link.get("label"), link.get("url"))
    s = (label + " " + (link.get("url") or "")).lower()
    if "youtu" in s:
        emoji = "▶️"
    elif "instagram" in s or "insta" in s:
        emoji = "📸"
    elif "t.me" in s or "telegram" in s:
        emoji = "✈️"
    elif "facebook" in s or "fb." in s:
        emoji = "📘"
    elif "whatsapp" in s:
        emoji = "💬"
    else:
        emoji = "🔗"
    return f"{emoji} {label} par dekho"


def gw_links(gw) -> list:
    """Giveaway ke saare links (purane giveaway ka single video_url bhi chalta hai)."""
    gw = gw or {}
    links = [l for l in (gw.get("links") or []) if l.get("url")]
    if not links and gw.get("video_url"):
        links = [{"label": "", "url": gw["video_url"]}]
    return links


def fmt_when(dt) -> str:
    """Winner time, jaise '12 Nov, 09:00 PM IST'."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b, %I:%M %p") + " IST"


def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400):
    """Telegram Mini App initData verify karta hai. Valid ho to user dict, warna None."""
    if not init_data or len(init_data) > 4096:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        return None
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    def calc(exclude: tuple) -> str:
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()) if k not in exclude)
        return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    # Telegram ne 'signature' field jodi hai; dono tareeke try karte hain (dono secure hain)
    if not (hmac.compare_digest(calc(()), received) or hmac.compare_digest(calc(("signature",)), received)):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except (ValueError, KeyError):
        return None


class RateLimiter:
    def __init__(self, per_minute: int):
        self.limit = per_minute
        self.hits: dict = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        if len(self.hits) > 5000:
            self.hits.clear()
        recent = [t for t in self.hits.get(key, []) if now - t < 60]
        if len(recent) >= self.limit:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        return True


def client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote) or "unknown"


def jerr(msg: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": msg}, status=status, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- data builders
def drop_window(ctx: dict, live_at):
    if not live_at:
        return ""
    return iso(live_at + timedelta(seconds=ctx["public"].get("lucky_window", 10)))


async def drop_shared(db: dict, ctx: dict, d: dict, wall_limit: int) -> dict:
    cur = db["drop_claims"].find({"drop": d["_id"], "rank": {"$ne": None}}).sort("rank", 1).limit(wall_limit)
    wall = [
        {"uid": w.get("uid"), "rank": w.get("rank"), "name": short_name(w.get("name")), "uname": w.get("username"),
         "ms": w.get("ms", 0)}
        async for w in cur
    ]
    ld = (ctx.get("live") or {}).get("drop")
    queued = ld["queued"] if ld and ld.get("no") == d["_id"] else 0
    return {
        "no": d["_id"],
        "label": d.get("label", "Redeem Code"),
        "status": d.get("status"),
        "mode": d.get("mode", "fast"),
        "total": d.get("total", 0),
        "claimed": d.get("claimed_count", 0),
        "queued": queued,
        "go_live_at": iso(d.get("go_live_at")),
        "live_at": iso(d.get("live_at")),
        "window_ends": drop_window(ctx, d.get("live_at")) if d.get("mode") == "lucky" else "",
        "lucky_closed": bool(d.get("lucky_closed")),
        "ended_at": iso(d.get("ended_at")),
        "end_reason": d.get("end_reason"),
        "wall": wall,
        "_reminders": set(d.get("reminders", [])),
    }


async def build_shared(db: dict, ctx: dict) -> dict:
    users, entries, winners = db["users"], db["entries"], db["winners"]
    sponsors, config, drops = db["sponsors"], db["config"], db["drops"]

    gw = await config.find_one({"_id": "giveaway"})
    gl = gw_links(gw)
    shared = {
        "giveaway": {
            "active": bool(gw and not gw.get("closing")),
            "closing": bool(gw and gw.get("closing")),
            "video_url": gl[0]["url"] if gl else "",
            "video_label": link_text(gl[0]) if gl else "",
            "links": [{"label": link_text(l), "url": l["url"]} for l in gl],
            "winner_text": fmt_when((gw or {}).get("winner_at")),
        },
        "totals": {
            "users": await users.count_documents({"junk": {"$ne": True}}),
            "winners": await winners.count_documents({}),
        },
        "entries_total": await entries.count_documents({}),
        "entries": [],
        "winners": [],
        "board": {"refs": [], "streaks": [], "weekly": []},
        "week": {
            "key": week_key(),
            "ends_at": iso(week_end_dt()),
            "prizes": list(ctx["public"].get("lb_prizes", [])),
            "min_refs": int(ctx["public"].get("lb_min_refs", 10)),
        },
        "results": [],
        "sponsors": [],
        "drops": {"current": None, "history": []},
    }
    shared["giveaway"]["entries"] = shared["entries_total"]

    async for e in entries.find({}).sort("entered_at", -1).limit(100):
        shared["entries"].append(
            {"uid": e["_id"], "name": short_name(e.get("name")), "uname": e.get("username"),
             "tickets": int(e.get("tickets", 1)), "at": iso(e.get("entered_at"))}
        )
    async for w in winners.find({}).sort("declared_at", -1).limit(20):
        allw = w.get("winners_all") or []
        names = ", ".join(short_name(x.get("name")) for x in allw) if allw else short_name(w.get("name"))
        uids = [x.get("id") for x in allw] if allw else [w.get("winner_id")]
        shared["winners"].append(
            {"uid": w.get("winner_id"), "uids": uids, "name": names, "uname": w.get("username"),
             "at": iso(w.get("declared_at")), "no": w.get("giveaway_no"), "entries": w.get("entries_count", 0)}
        )
    wk = shared["week"]["key"]
    async for u in users.find({f"wkc.{wk}": {"$gt": 0}, "banned": {"$ne": True}}).sort(
        [(f"wkc.{wk}", -1), (f"wkt.{wk}", 1)]
    ).limit(20):
        shared["board"]["weekly"].append(
            {"uid": u["_id"], "name": disp_name(u.get("name"), 22), "uname": u.get("username"),
             "count": int((u.get("wkc") or {}).get(wk, 0))}
        )
    async for u in users.find({"ref_count": {"$gt": 0}}).sort("ref_count", -1).limit(20):
        shared["board"]["refs"].append(
            {"uid": u["_id"], "name": short_name(u.get("name")), "uname": u.get("username"), "count": u.get("ref_count", 0)}
        )
    async for u in users.find({"best_streak": {"$gt": 0}}).sort("best_streak", -1).limit(20):
        shared["board"]["streaks"].append(
            {"uid": u["_id"], "name": short_name(u.get("name")), "uname": u.get("username"), "count": u.get("best_streak", 0)}
        )
    names_cap = int(ctx["public"].get("result_names", 200))
    ridx = 0
    async for w in winners.find({}).sort("declared_at", -1).limit(3):
        allw = w.get("winners_all") or []
        losers = w.get("losers") or []
        shared["results"].append(
            {
                "no": w.get("giveaway_no"),
                "at": iso(w.get("declared_at")),
                "total": int(w.get("entries_count", 0)),
                "winners": [{"uid": x.get("id"), "name": disp_name(x.get("name")), "uname": x.get("username")} for x in allw],
                "losers": [
                    {"uid": x.get("id"), "name": disp_name(x.get("name")), "uname": x.get("username")}
                    for x in losers[:names_cap]
                ] if ridx < 2 else [],
                "losers_total": int(w.get("losers_total", max(0, int(w.get("entries_count", 0)) - len(allw)))),
            }
        )
        ridx += 1
    async for s in sponsors.find({"active": True}):
        shared["sponsors"].append({"title": s.get("title", "Sponsor"), "link": s.get("link", "")})

    active = await drops.find_one({"status": {"$in": ["scheduled", "live"]}})
    if active:
        shared["drops"]["current"] = await drop_shared(db, ctx, active, 60)
    async for d in drops.find({"status": "ended"}).sort("_id", -1).limit(5):
        shared["drops"]["history"].append(await drop_shared(db, ctx, d, 12))
    return shared


def drop_public(v: dict, uid: int) -> dict:
    return {
        "no": v["no"], "label": v["label"], "status": v["status"], "mode": v["mode"], "total": v["total"],
        "claimed": v["claimed"], "queued": v["queued"], "go_live_at": v["go_live_at"], "live_at": v["live_at"],
        "window_ends": v["window_ends"], "lucky_closed": v["lucky_closed"], "ended_at": v["ended_at"],
        "end_reason": v["end_reason"], "reminded": uid in v["_reminders"],
        "wall": [{"rank": w["rank"], "name": w["name"], "uname": w["uname"], "ms": w["ms"], "me": w["uid"] == uid}
                 for w in v["wall"]],
    }


def personalize(sh: dict, uid: int) -> dict:
    cur = sh["drops"]["current"]
    return {
        "giveaway": sh["giveaway"],
        "totals": sh["totals"],
        "sponsors": sh["sponsors"],
        "entries_total": sh["entries_total"],
        "entries": [{"name": e["name"], "uname": e["uname"], "tickets": e["tickets"], "at": e["at"], "me": e["uid"] == uid}
                    for e in sh["entries"]],
        "winners": [{"name": w["name"], "uname": w["uname"], "at": w["at"], "no": w["no"], "entries": w["entries"],
                     "me": uid in w["uids"]} for w in sh["winners"]],
        "board": {
            k: [{"name": x["name"], "uname": x["uname"], "count": x["count"], "me": x["uid"] == uid} for x in sh["board"][k]]
            for k in ("refs", "streaks", "weekly")
        },
        "week": sh["week"],
        "results": [
            {
                "no": r["no"], "at": r["at"], "total": r["total"], "losers_total": r["losers_total"],
                "winners": [{"name": x["name"], "uname": x["uname"], "me": x["uid"] == uid} for x in r["winners"]],
                "losers": [{"name": x["name"], "uname": x["uname"], "me": x["uid"] == uid} for x in r["losers"]],
            }
            for r in sh["results"]
        ],
        "drops": {
            "current": drop_public(cur, uid) if cur else None,
            "history": [drop_public(h, uid) for h in sh["drops"]["history"]],
        },
    }


async def build_me(db: dict, ctx: dict, uid: int, tg_user: dict, current_no) -> dict:
    users, entries, drop_claims, rewards = db["users"], db["entries"], db["drop_claims"], db["rewards"]
    ref_link = f"https://t.me/{ctx['public']['bot_username']}?start=ref_{uid}"
    u = await users.find_one({"_id": uid})
    if not u:
        return {"registered": False, "name": tg_user.get("first_name", ""), "ref_link": ref_link,
                "invite_code": str(uid), "my_claims": [], "rewards": [], "withdrawals": []}

    entry = await entries.find_one({"_id": uid})
    refs = int(u.get("ref_count", 0))
    best = int(u.get("best_streak", 0))
    today = datetime.now(IST).date().isoformat()
    my_claims = []
    async for c in drop_claims.find({"uid": uid, "rank": {"$ne": None}}).sort("at", -1).limit(10):
        my_claims.append({"drop": c.get("drop"), "code": c.get("code"), "rank": c.get("rank"), "ms": c.get("ms", 0),
                          "at": iso(c.get("at"))})
    my_drop = None
    if current_no is not None:
        c = await drop_claims.find_one({"_id": f"{current_no}:{uid}"})
        if c:
            my_drop = {"drop": current_no, "queued": bool(c.get("lucky") and c.get("rank") is None and not c.get("lost")),
                       "lost": bool(c.get("lost")), "rank": c.get("rank")}
    rw = []
    async for r in rewards.find({"uid": uid}).sort("earned_at", -1).limit(40):
        rw.append({
            "id": r["_id"], "track": r.get("track"), "cycle": r.get("cycle"), "target": r.get("target"),
            "amount": r.get("amount"), "status": r.get("status"), "earned_at": iso(r.get("earned_at")),
            "requested_at": iso(r.get("requested_at")), "deadline": iso(r.get("deadline")),
            "sent_at": iso(r.get("sent_at")), "claimed_at": iso(r.get("claimed_at")),
        })
    wk = week_key()
    week_refs = int((u.get("wkc") or {}).get(wk, 0))
    wds = []
    if db.get("withdrawals") is not None:
        async for w in db["withdrawals"].find({"uid": uid}).sort("created_at", -1).limit(6):
            wds.append({"id": w["_id"], "amount_p": int(w.get("amount_p", 0)), "method": w.get("method"),
                        "status": w.get("status"), "user_confirm": w.get("user_confirm"),
                        "at": iso(w.get("created_at"))})
    return {
        "registered": True,
        "name": u.get("name") or tg_user.get("first_name", ""),
        "verified": bool(u.get("verified")),
        "banned": bool(u.get("banned")),
        "entered": entry is not None,
        "tickets": int(entry.get("tickets", 1)) if entry else int(u.get("bonus_tickets", 0)),
        "refs": refs,
        "ref_cycle": int(u.get("ref_cycle", 1)),
        "ref_cycle_count": int(u.get("ref_cycle_count", 0)),
        "rank_refs": (await users.count_documents({"ref_count": {"$gt": refs}}) + 1) if refs > 0 else None,
        "week_refs": week_refs,
        "rank_week": (await users.count_documents({f"wkc.{wk}": {"$gt": week_refs}}) + 1) if week_refs > 0 else None,
        "balance_p": int(u.get("balance_p", 0)),
        "earned_p": int(u.get("earned_p", 0)),
        "withdrawn_p": int(u.get("withdrawn_p", 0)),
        "invite_code": str(uid),
        "has_referrer": bool(u.get("ref_by")),
        "withdrawals": wds,
        "rank_streak": (await users.count_documents({"best_streak": {"$gt": best}}) + 1) if best > 0 else None,
        "streak": int(u.get("streak", 0)),
        "streak_cycle": int(u.get("streak_cycle", 1)),
        "best_streak": best,
        "claimed_today": u.get("last_claim") == today,
        "streak_remind": u.get("streak_remind") is not False,
        "ref_link": ref_link,
        "my_claims": my_claims,
        "my_drop": my_drop,
        "rewards": rw,
    }


# ---------------------------------------------------------------- app
def create_app(ctx: dict) -> web.Application:
    """
    ctx = {
      "db": {...collections, bot start hone ke baad bharta hai...},
      "public": {...page par jaane wali non-secret settings...},
      "bot_token": "...",               # sirf initData verify karne ke liye
      "actions": {...},                 # bot.py ke functions (claim/daily/remind/redeem/settings)
      "live": {"v": int, "drop": {...}},  # drop ki in-memory state
      "status": {"degraded": bool, "msg": str}, "notice": {"text": str}, "reward_cfg": {...},
      "hooks": {},                      # site_app yahan invalidate() register karta hai
    }
    """
    app = web.Application(client_max_size=64 * 1024)
    app["ctx"] = ctx
    app["shared"] = {"t": 0.0, "v": -1, "data": None}
    app["shared_lock"] = asyncio.Lock()
    app["me_cache"] = {}
    app["sem"] = asyncio.Semaphore(20)
    app["waiting"] = 0
    app["ip_limiter"] = RateLimiter(240)
    app["state_limiter"] = RateLimiter(300)
    app["uid_limiter"] = RateLimiter(90)
    app["claim_limiter"] = RateLimiter(30)
    ctx.setdefault("hooks", {})["invalidate"] = lambda uid: app["me_cache"].pop(uid, None)

    html_raw = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    cfg_json = json.dumps(ctx["public"], ensure_ascii=False).replace("</", "<\\/")
    page = html_raw.replace("/*__CONFIG__*/{}", cfg_json)

    async def index(_request):
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-cache"})

    async def health(_request):
        return web.Response(text="OK ✅ ASB FreeCodes Bot is running")

    async def api_state(request):
        if not app["state_limiter"].allow(client_ip(request)):
            return jerr("too many requests", 429)
        live = ctx.get("live") or {"v": 0, "drop": None}
        d = live.get("drop")
        drop = None
        if d:
            drop = {
                "no": d["no"], "status": d["status"], "mode": d.get("mode", "fast"), "claimed": d.get("claimed", 0),
                "total": d.get("total", 0), "queued": d.get("queued", 0), "go_live_at": iso(d.get("go_live_at")),
                "live_at": iso(d.get("live_at")), "window_ends": iso(d.get("window_ends")),
                "lucky_closed": bool(d.get("lucky_closed")),
            }
        return web.json_response(
            {"ok": True, "v": live.get("v", 0), "server_ms": int(time.time() * 1000), "drop": drop,
             "degraded": bool(ctx.get("status", {}).get("degraded"))},
            headers={"Cache-Control": "no-store"},
        )

    async def authed(request, limiter=None):
        """(uid, tg_user, body, error_response)"""
        if not ctx["db"]:
            return None, None, None, jerr("starting", 503)
        if not app["ip_limiter"].allow(client_ip(request)):
            return None, None, None, jerr("too many requests", 429)
        try:
            body = await request.json()
        except Exception:
            return None, None, None, jerr("bad request", 400)
        if not isinstance(body, dict):
            return None, None, None, jerr("bad request", 400)
        tg_user = verify_init_data(str(body.get("initData", "")), ctx["bot_token"])
        if not tg_user:
            return None, None, None, jerr("unauthorized", 401)
        uid = int(tg_user["id"])
        if limiter and not limiter.allow(str(uid)):
            return None, None, None, jerr("slow down", 429)
        return uid, tg_user, body, None

    async def get_shared():
        async with app["shared_lock"]:
            cache = app["shared"]
            live_v = (ctx.get("live") or {}).get("v", 0)
            age = time.time() - cache["t"]
            has_drop = bool((cache["data"] or {}).get("drops", {}).get("current"))
            ttl = 2.0 if has_drop else 8.0
            if cache["data"] is None or age > ttl or (cache["v"] != live_v and age > 0.8):
                cache["data"] = await build_shared(ctx["db"], ctx)
                cache["t"] = time.time()
                cache["v"] = live_v
            return cache["data"]

    async def get_me(uid, tg_user, shared):
        mc = app["me_cache"]
        hit = mc.get(uid)
        if hit and time.time() - hit[0] < 8:
            return hit[1]
        cur = shared["drops"]["current"]
        me = await build_me(ctx["db"], ctx, uid, tg_user, cur["no"] if cur else None)
        if len(mc) > 5000:
            mc.clear()
        mc[uid] = (time.time(), me)
        return me

    async def compute(uid, tg_user):
        shared = await get_shared()
        me = await get_me(uid, tg_user, shared)
        return shared, me

    async def api_app(request):
        uid, tg_user, _body, err = await authed(request, app["uid_limiter"])
        if err:
            return err
        if app["waiting"] >= 150:  # overload: jaldi "busy" bolo, DB pe load mat badhao
            return jerr("busy", 503)
        app["waiting"] += 1
        try:
            async with app["sem"]:
                shared, me = await compute(uid, tg_user)
        except Exception:
            logger.exception("api_app failed")
            return jerr("server error", 500)
        finally:
            app["waiting"] -= 1
        payload = personalize(shared, uid)
        payload.update(
            ok=True, server_ms=int(time.time() * 1000), me=me,
            v=(ctx.get("live") or {}).get("v", 0),
            notice=(ctx.get("notice") or {}).get("text", ""),
            status=dict(ctx.get("status") or {}),
            reward_cfg=ctx.get("reward_cfg") or {},
        )
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    def drop_no(body):
        try:
            return int(body.get("drop"))
        except (TypeError, ValueError):
            return None

    async def action(request, name, build_args):
        uid, _u, body, err = await authed(request, app["claim_limiter"])
        if err:
            return err
        fn = ctx.get("actions", {}).get(name)
        if not fn:
            return jerr("starting", 503)
        args = build_args(uid, body)
        if args is None:
            return jerr("bad request", 400)
        res = await fn(*args)
        app["me_cache"].pop(uid, None)
        app["shared"]["t"] = 0.0
        return web.json_response({"ok": True, **res}, headers={"Cache-Control": "no-store"})

    async def api_claim(request):
        return await action(request, "claim", lambda uid, b: None if drop_no(b) is None else (uid, drop_no(b)))

    async def api_daily(request):
        return await action(request, "daily", lambda uid, b: (uid,))

    async def api_remind(request):
        return await action(request, "remind", lambda uid, b: None if drop_no(b) is None else (uid, drop_no(b)))

    async def api_redeem(request):
        return await action(request, "redeem", lambda uid, b: (uid, str(b.get("reward", ""))[:80]) if b.get("reward") else None)

    async def api_invite(request):
        return await action(
            request, "invite", lambda uid, b: (uid, str(b.get("code", ""))[:24]) if b.get("code") else None
        )

    async def api_withdraw(request):
        def build(uid, b):
            method = str(b.get("method", ""))
            if method not in ("upi", "bank", "mobile"):
                return None
            return (uid, method, str(b.get("detail", ""))[:90], str(b.get("name", ""))[:60])

        return await action(request, "withdraw", build)

    async def api_settings(request):
        return await action(request, "settings", lambda uid, b: (uid, bool(b.get("streak_remind"))))

    async def on_prepare(_request, response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    app.on_response_prepare.append(on_prepare)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/state", api_state)
    app.router.add_post("/api/app", api_app)
    app.router.add_post("/api/claim", api_claim)
    app.router.add_post("/api/daily", api_daily)
    app.router.add_post("/api/remind", api_remind)
    app.router.add_post("/api/reward/redeem", api_redeem)
    app.router.add_post("/api/invite", api_invite)
    app.router.add_post("/api/withdraw", api_withdraw)
    app.router.add_post("/api/settings", api_settings)
    return app


async def start_server(ctx: dict, port: int) -> web.AppRunner:
    app = create_app(ctx)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("Mini App + health server running on port %s", port)
    return runner
