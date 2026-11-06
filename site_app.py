"""
site_app.py — Telegram Mini App server for ASB FreeCodes Bot (aiohttp)

Routes
  GET  /            -> Mini App page (static/index.html)
  GET  /health      -> plain "OK" (Koyeb health check + UptimeRobot monitor)
  POST /api/app     -> sab tabs ka data (Home, Entries, Drops, Winners, Board, Profile)
  POST /api/claim   -> live drop claim
  POST /api/daily   -> daily bonus claim
  POST /api/remind  -> drop reminder ON

Har /api/* request me Telegram ka signed `initData` chahiye — bina Telegram ke koi data nahi dekh sakta.
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


def iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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
async def drop_shared(db: dict, d: dict, wall_limit: int) -> dict:
    cur = db["drop_claims"].find({"drop": d["_id"], "rank": {"$ne": None}}).sort("rank", 1).limit(wall_limit)
    wall = [
        {"uid": w.get("uid"), "rank": w.get("rank"), "name": short_name(w.get("name")), "ms": w.get("ms", 0)}
        async for w in cur
    ]
    return {
        "no": d["_id"],
        "label": d.get("label", "Redeem Code"),
        "status": d.get("status"),
        "total": d.get("total", 0),
        "claimed": d.get("claimed_count", 0),
        "go_live_at": iso(d.get("go_live_at")),
        "live_at": iso(d.get("live_at")),
        "ended_at": iso(d.get("ended_at")),
        "end_reason": d.get("end_reason"),
        "wall": wall,
        "_reminders": set(d.get("reminders", [])),
    }


async def build_shared(db: dict) -> dict:
    users, entries, winners = db["users"], db["entries"], db["winners"]
    sponsors, config, drops = db["sponsors"], db["config"], db["drops"]

    gw = await config.find_one({"_id": "giveaway"})
    shared = {
        "giveaway": {
            "active": bool(gw and not gw.get("closing")),
            "closing": bool(gw and gw.get("closing")),
        },
        "totals": {
            "users": await users.count_documents({"junk": {"$ne": True}}),
            "winners": await winners.count_documents({}),
        },
        "entries_total": await entries.count_documents({}),
        "entries": [],
        "winners": [],
        "board": {"refs": [], "streaks": []},
        "sponsors": [],
        "drops": {"current": None, "history": []},
    }
    shared["giveaway"]["entries"] = shared["entries_total"]

    async for e in entries.find({}).sort("entered_at", -1).limit(100):
        shared["entries"].append(
            {"uid": e["_id"], "name": short_name(e.get("name")), "tickets": int(e.get("tickets", 1)),
             "at": iso(e.get("entered_at"))}
        )
    async for w in winners.find({}).sort("declared_at", -1).limit(20):
        shared["winners"].append(
            {"uid": w.get("winner_id"), "name": short_name(w.get("name")), "at": iso(w.get("declared_at")),
             "no": w.get("giveaway_no"), "entries": w.get("entries_count", 0)}
        )
    async for u in users.find({"ref_count": {"$gt": 0}}).sort("ref_count", -1).limit(20):
        shared["board"]["refs"].append({"uid": u["_id"], "name": short_name(u.get("name")), "count": u.get("ref_count", 0)})
    async for u in users.find({"best_streak": {"$gt": 0}}).sort("best_streak", -1).limit(20):
        shared["board"]["streaks"].append({"uid": u["_id"], "name": short_name(u.get("name")), "count": u.get("best_streak", 0)})
    async for s in sponsors.find({"active": True}):
        shared["sponsors"].append({"title": s.get("title", "Sponsor"), "link": s.get("link", "")})

    active = await drops.find_one({"status": {"$in": ["scheduled", "live"]}})
    if active:
        shared["drops"]["current"] = await drop_shared(db, active, 60)
    async for d in drops.find({"status": "ended"}).sort("_id", -1).limit(5):
        shared["drops"]["history"].append(await drop_shared(db, d, 12))
    return shared


def drop_public(v: dict, uid: int) -> dict:
    return {
        "no": v["no"], "label": v["label"], "status": v["status"], "total": v["total"], "claimed": v["claimed"],
        "go_live_at": v["go_live_at"], "live_at": v["live_at"], "ended_at": v["ended_at"],
        "end_reason": v["end_reason"], "reminded": uid in v["_reminders"],
        "wall": [{"rank": w["rank"], "name": w["name"], "ms": w["ms"], "me": w["uid"] == uid} for w in v["wall"]],
    }


def personalize(sh: dict, uid: int) -> dict:
    cur = sh["drops"]["current"]
    return {
        "giveaway": sh["giveaway"],
        "totals": sh["totals"],
        "sponsors": sh["sponsors"],
        "entries_total": sh["entries_total"],
        "entries": [{"name": e["name"], "tickets": e["tickets"], "at": e["at"], "me": e["uid"] == uid} for e in sh["entries"]],
        "winners": [{"name": w["name"], "at": w["at"], "no": w["no"], "entries": w["entries"], "me": w["uid"] == uid} for w in sh["winners"]],
        "board": {
            k: [{"name": x["name"], "count": x["count"], "me": x["uid"] == uid} for x in sh["board"][k]]
            for k in ("refs", "streaks")
        },
        "drops": {
            "current": drop_public(cur, uid) if cur else None,
            "history": [drop_public(h, uid) for h in sh["drops"]["history"]],
        },
    }


async def build_me(db: dict, ctx: dict, uid: int, tg_user: dict) -> dict:
    users, entries, drop_claims = db["users"], db["entries"], db["drop_claims"]
    ref_link = f"https://t.me/{ctx['public']['bot_username']}?start=ref_{uid}"
    u = await users.find_one({"_id": uid})
    if not u:
        return {"registered": False, "name": tg_user.get("first_name", ""), "ref_link": ref_link, "my_claims": []}

    entry = await entries.find_one({"_id": uid})
    refs = int(u.get("ref_count", 0))
    best = int(u.get("best_streak", 0))
    today = datetime.now(IST).date().isoformat()
    my_claims = []
    async for c in drop_claims.find({"uid": uid, "rank": {"$ne": None}}).sort("at", -1).limit(10):
        my_claims.append({"drop": c.get("drop"), "code": c.get("code"), "rank": c.get("rank"), "ms": c.get("ms", 0), "at": iso(c.get("at"))})
    return {
        "registered": True,
        "name": u.get("name") or tg_user.get("first_name", ""),
        "verified": bool(u.get("verified")),
        "entered": entry is not None,
        "tickets": int(entry.get("tickets", 1)) if entry else int(u.get("bonus_tickets", 0)),
        "refs": refs,
        "rank_refs": (await users.count_documents({"ref_count": {"$gt": refs}}) + 1) if refs > 0 else None,
        "rank_streak": (await users.count_documents({"best_streak": {"$gt": best}}) + 1) if best > 0 else None,
        "streak": int(u.get("streak", 0)),
        "best_streak": best,
        "claimed_today": u.get("last_claim") == today,
        "ref_link": ref_link,
        "my_claims": my_claims,
    }


# ---------------------------------------------------------------- app
def create_app(ctx: dict) -> web.Application:
    """
    ctx = {
      "db": {...collections, bot start hone ke baad bharta hai...},
      "public": {...page par jaane wali non-secret settings...},
      "bot_token": "...",   # sirf initData verify karne ke liye (HTML me kabhi nahi jata)
      "actions": {"claim": fn, "daily": fn, "remind": fn},   # bot.py ke functions
    }
    """
    app = web.Application()
    app["ctx"] = ctx
    app["shared"] = {"t": 0.0, "data": None}
    app["shared_lock"] = asyncio.Lock()
    app["ip_limiter"] = RateLimiter(240)
    app["uid_limiter"] = RateLimiter(90)
    app["claim_limiter"] = RateLimiter(30)

    html_raw = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    cfg_json = json.dumps(ctx["public"], ensure_ascii=False).replace("</", "<\\/")
    page = html_raw.replace("/*__CONFIG__*/{}", cfg_json)

    async def index(_request):
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-cache"})

    async def health(_request):
        return web.Response(text="OK ✅ ASB FreeCodes Bot is running")

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
            cur = (cache["data"] or {}).get("drops", {}).get("current")
            ttl = 2 if cur else 6
            if cache["data"] is None or time.time() - cache["t"] > ttl:
                cache["data"] = await build_shared(ctx["db"])
                cache["t"] = time.time()
            return cache["data"]

    async def api_app(request):
        uid, tg_user, _body, err = await authed(request, app["uid_limiter"])
        if err:
            return err
        try:
            shared = await get_shared()
            me = await build_me(ctx["db"], ctx, uid, tg_user)
        except Exception:
            logger.exception("api_app failed")
            return jerr("server error", 500)
        payload = personalize(shared, uid)
        payload.update(ok=True, server_ms=int(time.time() * 1000), me=me)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    def drop_no(body):
        try:
            return int(body.get("drop"))
        except (TypeError, ValueError):
            return None

    async def api_claim(request):
        uid, _u, body, err = await authed(request, app["claim_limiter"])
        if err:
            return err
        no = drop_no(body)
        if no is None or "claim" not in ctx.get("actions", {}):
            return jerr("bad request", 400)
        res = await ctx["actions"]["claim"](uid, no)
        app["shared"]["t"] = 0.0
        return web.json_response({"ok": True, **res}, headers={"Cache-Control": "no-store"})

    async def api_daily(request):
        uid, _u, _body, err = await authed(request, app["claim_limiter"])
        if err:
            return err
        if "daily" not in ctx.get("actions", {}):
            return jerr("starting", 503)
        res = await ctx["actions"]["daily"](uid)
        return web.json_response({"ok": True, **res}, headers={"Cache-Control": "no-store"})

    async def api_remind(request):
        uid, _u, body, err = await authed(request, app["claim_limiter"])
        if err:
            return err
        no = drop_no(body)
        if no is None or "remind" not in ctx.get("actions", {}):
            return jerr("bad request", 400)
        res = await ctx["actions"]["remind"](uid, no)
        app["shared"]["t"] = 0.0
        return web.json_response({"ok": True, **res}, headers={"Cache-Control": "no-store"})

    async def on_prepare(_request, response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    app.on_response_prepare.append(on_prepare)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/api/app", api_app)
    app.router.add_post("/api/claim", api_claim)
    app.router.add_post("/api/daily", api_daily)
    app.router.add_post("/api/remind", api_remind)
    return app


async def start_server(ctx: dict, port: int) -> web.AppRunner:
    app = create_app(ctx)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("Mini App + health server running on port %s", port)
    return runner
