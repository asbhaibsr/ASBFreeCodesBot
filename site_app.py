"""
site_app.py — Website + API server for ASB FreeCodes Bot (aiohttp)

Routes
  GET  /            -> website (static/index.html)
  GET  /health      -> plain "OK" (Koyeb health check + UptimeRobot monitor)
  GET  /api/stats   -> public live stats (cached 20s, names masked)
  POST /api/me      -> personal dashboard for Telegram Mini App (initData verified)
"""

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
STATS_TTL = 20  # seconds


# ---------------------------------------------------------------- helpers
def mask_name(name) -> str:
    """'Ravi Kumar' -> 'Ra***' (privacy ke liye public jagah par)."""
    n = str(name or "").strip() or "User"
    return (n[:2] if len(n) > 2 else n[:1]) + "***"


def iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400):
    """Telegram Mini App initData ko verify karta hai. Valid ho to user dict, warna None."""
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


# ---------------------------------------------------------------- stats
async def build_stats(db: dict) -> dict:
    users, entries, winners = db["users"], db["entries"], db["winners"]
    sponsors, config = db["sponsors"], db["config"]

    gw = await config.find_one({"_id": "giveaway"})
    data = {
        "ready": True,
        "giveaway": {
            "active": bool(gw and not gw.get("closing")),
            "closing": bool(gw and gw.get("closing")),
            "entries": await entries.count_documents({}),
        },
        "users": await users.count_documents({"junk": {"$ne": True}}),
        "winners_total": await winners.count_documents({}),
        "recent_winners": [],
        "top_referrers": [],
        "recent_entries": [],
        "sponsors": [],
    }
    async for w in winners.find({}).sort("declared_at", -1).limit(6):
        data["recent_winners"].append(
            {"name": mask_name(w.get("name")), "at": iso(w.get("declared_at")), "no": w.get("giveaway_no")}
        )
    async for u in users.find({"ref_count": {"$gt": 0}}).sort("ref_count", -1).limit(5):
        data["top_referrers"].append({"name": mask_name(u.get("name")), "refs": u.get("ref_count", 0)})
    async for e in entries.find({}).sort("entered_at", -1).limit(5):
        data["recent_entries"].append({"name": mask_name(e.get("name")), "at": iso(e.get("entered_at"))})
    async for s in sponsors.find({"active": True}):
        data["sponsors"].append({"title": s.get("title", "Sponsor"), "link": s.get("link", "")})
    return data


# ---------------------------------------------------------------- handlers
def create_app(ctx: dict) -> web.Application:
    """
    ctx = {
      "db": {...collections, bot start hone ke baad bharta hai...},
      "public": {...website par dikhne wali non-secret settings...},
      "bot_token": "...",   # sirf initData verify karne ke liye (HTML me kabhi nahi jata)
    }
    """
    app = web.Application()
    app["ctx"] = ctx
    app["stats_cache"] = {"t": 0.0, "data": None}
    app["me_limiter"] = RateLimiter(30)
    app["stats_limiter"] = RateLimiter(120)

    html_raw = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    cfg_json = json.dumps(ctx["public"], ensure_ascii=False).replace("</", "<\\/")
    page = html_raw.replace("/*__CONFIG__*/{}", cfg_json)

    async def index(_request):
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-cache"})

    async def health(_request):
        return web.Response(text="OK ✅ ASB FreeCodes Bot is running")

    async def stats(request):
        if not ctx["db"]:
            return web.json_response({"ready": False}, status=503)
        if not request.app["stats_limiter"].allow(client_ip(request)):
            return web.json_response({"error": "too many requests"}, status=429)
        cache = request.app["stats_cache"]
        if cache["data"] is None or time.time() - cache["t"] > STATS_TTL:
            try:
                cache["data"] = await build_stats(ctx["db"])
                cache["t"] = time.time()
            except Exception:
                logger.exception("stats build failed")
                if cache["data"] is None:
                    return web.json_response({"ready": False}, status=500)
        return web.json_response(cache["data"], headers={"Cache-Control": "no-store"})

    async def me(request):
        if not ctx["db"]:
            return web.json_response({"error": "starting"}, status=503)
        if not request.app["me_limiter"].allow(client_ip(request)):
            return web.json_response({"error": "too many requests"}, status=429)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        user = verify_init_data(str(body.get("initData", "")), ctx["bot_token"])
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)

        uid = int(user["id"])
        db = ctx["db"]
        u = await db["users"].find_one({"_id": uid})
        ref_link = f"https://t.me/{ctx['public']['bot_username']}?start=ref_{uid}"
        if not u:
            return web.json_response({"registered": False, "ref_link": ref_link})

        entry = await db["entries"].find_one({"_id": uid})
        refs = int(u.get("ref_count", 0))
        rank = None
        if refs > 0:
            rank = await db["users"].count_documents({"ref_count": {"$gt": refs}}) + 1
        today = datetime.now(IST).date().isoformat()
        return web.json_response(
            {
                "registered": True,
                "name": u.get("name") or user.get("first_name", ""),
                "verified": bool(u.get("verified")),
                "entered": entry is not None,
                "tickets": int(entry.get("tickets", 1)) if entry else int(u.get("bonus_tickets", 0)),
                "refs": refs,
                "rank": rank,
                "streak": int(u.get("streak", 0)),
                "best_streak": int(u.get("best_streak", 0)),
                "claimed_today": u.get("last_claim") == today,
                "ref_link": ref_link,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def on_prepare(_request, response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    app.on_response_prepare.append(on_prepare)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/stats", stats)
    app.router.add_post("/api/me", me)
    return app


async def start_server(ctx: dict, port: int) -> web.AppRunner:
    app = create_app(ctx)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("Website + health server running on port %s", port)
    return runner
