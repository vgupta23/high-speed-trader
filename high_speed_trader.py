#!/usr/bin/env python3
"""
high_speed_trader.py

A stateless, high-speed, EQUITY-ONLY intraday trading loop for a Robinhood
account, built to the rules in SKILLS.md:
  - Unlimited trades per session, on a fast fixed-interval tick loop.
  - Hard stop-loss: sell a position the moment it's down $0.50/share from
    its entry (average buy price). Take-profit is uncapped -- winners are
    never force-sold while ahead.
  - Stock/equity instrument only. No options.
  - Two seed universes (up_universe for momentum longs, down_universe for
    dip-buy bounces) are a guideline, not a boundary -- the AI may propose
    any other liquid, actively-traded US equity, which is then verified with
    the broker before it's ever bought.
  - Runs only during regular exchange hours, and flattens every open
    position shortly before the close (the loop that enforces the stop isn't
    watching once the session ends).
  - No state is stored anywhere. Every tick re-reads live broker state
    (cash, positions, current prices) fresh; nothing is cached or persisted
    between ticks or between runs.

The broker rail -- quotes, positions, account cash, and orders -- always
runs through the Robinhood agentic MCP via the Claude Code CLI, no matter
which AI is choosing the pick. That means Claude Code must be installed and
the Robinhood MCP authorized regardless of pick_provider.

The entry PICK (which name to buy) comes from your chosen AI:
  "claude": Claude Code CLI, no API key, can WebSearch for fresh catalysts.
  "openai": OpenAI chat completions API, needs OPENAI_API_KEY.
All risk math -- sizing, the stop-loss, the close-out guard -- is plain
deterministic Python. The AI only ever chooses WHAT to buy.

READ SKILLS.md AND sample.py's WARNING BEFORE RUNNING THIS WITH REAL MONEY.
This is experimental, not a money machine. It can place real orders with no
approval prompt once enable_live_buys is turned on. Equities can still lose
significant value between ticks. The code is unaudited. Not financial
advice. Use money you can afford to lose, and start tiny.
"""

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================================
# .env loading (stdlib only -- no python-dotenv dependency). Reads simple
# KEY=VALUE lines from a .env file next to this script into os.environ,
# WITHOUT overriding a variable the shell environment already set. This is
# the only place secrets (account number, API keys, Telegram token) should
# live -- .env is gitignored and must never be committed.
# ============================================================================
def load_dotenv(path=None):
    path = path or (Path(__file__).resolve().parent / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

# ============================================================================
# CONFIG
# ============================================================================
CONFIG = {
    # The agentic-enabled Robinhood account the bot trades. Ask Claude
    # "list my robinhood accounts" once the MCP is authorized, and put your
    # own account number here -- never commit a real one.
    "account_number": os.environ.get("ROBINHOOD_ACCOUNT_NUMBER", "YOUR_ACCOUNT_NUMBER_HERE"),

    # MCP server name exactly as it shows in `claude mcp list`.
    "mcp_server": "robinhood",

    # ----- which AI proposes the entry pick -----
    # "claude": uses your Claude Code CLI. No API key. Can WebSearch for
    #           fresh catalysts out of the box.
    # "openai": uses the OpenAI chat completions API. Needs OPENAI_API_KEY
    #           set as an environment variable.
    "pick_provider": "openai",
    "claude_bin": "claude",
    "claude_model": "sonnet",   # applied only on calls that allow WebSearch
    "openai_model": "gpt-5.6-luna",  # applied only on calls that allow WebSearch

    # Your own standing instructions to the AI, appended to every pick
    # prompt. Leave empty for none.
    "extra_pick_guidance": "",

    # ----- seed universes: a guideline, not a hard boundary. The AI may
    # propose a name outside these lists; it is verified with the broker
    # before any order is placed. -----
    #
    # up_universe: momentum longs -- names trading up on the day.
    "up_universe": [
        "AHER", "APP", "ALAB", "VRT", "MRVL",
        "AXTI", "AAOI", "LITE", "COHR", "CRDO",
        "PENG", "META", "GLW", "GOOGL", "BE",
        "AMZN", "CEG", "VST", "OUST", "RVII",
        "ASTS", "VSAT", "RKLB", "GEV", "ISRG",
        "SPCX", "LRCX", "VICR", "MU", "SMTC",
    ],
    # down_universe: dip-buy candidates -- liquid names that can gap down
    # hard on a bad print or broad sell-off and snap back just as fast.
    # Defaults to the same liquid names as up_universe; edit independently
    # if you want a different watchlist for the dip side.
    "down_universe": [
        "EOSE", "CIFR", "HUT", "WYFI", "MRVL",
        "AXTI", "AAOI", "FORM", "AMD", "CRDO",
        "PENG", "META", "GLW", "GOOGL", "AVGO",
        "WULF", "CEG", "VST", "OUST", "RVII",
        "ASTS", "VSAT", "RKLB", "GEV", "ISRG",
        "SPCX", "LRCX", "VICR", "MU", "SMTC",
        "FPS","LMND","CAT","LMT","RTX","PURR",
        "MSFT","XYZ","ROK","SOLS"
    ],
    # Minimum day-change percent (up) for an up_universe name to become a
    # momentum candidate.
    "candidate_min_daychg": 0.5,
    # Minimum absolute day-change percent (down) for a down_universe name to
    # become a dip-buy candidate, e.g. 5.0 == down more than 5%.
    "candidate_min_down_daychg": 5.0,
    # Maximum day-change percent (up) for an up_universe name to still be
    # considered -- names up more than this are excluded as one-day outliers
    # (e.g. halt/news-driven spikes) rather than fed to the pick step.
    "candidate_max_daychg": 10.0,

    # ----- sizing / risk (deterministic, never touched by the AI) -----
    "deploy_fraction": 0.25,        # fraction of settled cash per new entry
    "min_trade_usd": 25.0,          # skip an entry too small to matter
    "conviction_accept": ["high", "medium"],
    "stop_loss_usd": 0.50,          # hard stop: exit if price is down this many dollars from entry
    "close_out_minutes_before_close": 15,  # flatten everything this close to the bell

    # ----- loop -----
    "tick_interval_sec": 15,        # seconds between ticks; override with --interval

    # Safety gate. Sells (stop-loss, close-out) always run live -- they only
    # reduce risk. Buys stay OFF until you've dry-run with --simulation and
    # deliberately flip this to True.
    "enable_live_buys": False,

    # ----- session: regular exchange hours only -----
    "tz": "America/New_York",
    "session_open": "09:30",
    "session_close": "16:00",
    "ignore_weekday": False,   # testing only -- override with --ignore-weekday

    "claude_timeout_sec": 240,
    "http_timeout_sec": 90,
}

# Activity trail only -- timestamps and messages for a human to read. This is
# NOT trading state: it is never read back to decide what to do, so it stays
# consistent with "no state is stored."
LOG_PATH = Path.home() / ".high_speed_trader.log"


def log(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def notify(text):
    """Send a Telegram message if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are
    set. No-op (and never raises) if they are missing."""
    log(text)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        urllib.request.urlopen(url, data=data, timeout=15).read()
    except Exception as exc:
        log(f"notify failed: {exc}")


# ============================================================================
# Small JSON / HTTP helpers
# ============================================================================
def extract_json(text):
    if not text:
        return {"error": "empty model output"}
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {"error": f"no JSON found: {cleaned[:300]}"}
    try:
        return json.loads(cleaned[start:end + 1])
    except Exception as exc:
        return {"error": f"JSON parse failed: {exc}: {cleaned[:300]}"}


def http_post(url, headers, payload, timeout):
    import urllib.request
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ============================================================================
# The Claude Code headless bridge. This is the ONLY broker rail (quotes,
# account, equity orders) regardless of pick_provider, and is also the
# default pick brain. Strict JSON only.
# ============================================================================
def claude_cli(prompt, allowed_tools=None, timeout=None):
    """Run `claude -p` headless and return raw stdout text, or '' on failure."""
    timeout = timeout or CONFIG["claude_timeout_sec"]
    prompt = f"For account {CONFIG['account_number']}, {prompt}"
    args = [CONFIG["claude_bin"], "-p", prompt, "--dangerously-skip-permissions",
            "--output-format", "text"]

    tool_names = []
    if allowed_tools:
        if isinstance(allowed_tools, str):
            tool_names = [item.strip() for item in allowed_tools.split(",") if item.strip()]
        else:
            tool_names = [str(item).strip() for item in allowed_tools if str(item).strip()]
        args += ["--allowedTools", ",".join(tool_names)]

    # Only force a specific Claude model when WebSearch is explicitly
    # allowed (the pick step). Broker-rail calls use Claude Code's default.
    if any(t == "WebSearch" or t.startswith("WebSearch(") for t in tool_names) \
            and CONFIG.get("claude_model"):
        args += ["--model", CONFIG["claude_model"]]

    run_kwargs = {"capture_output": True, "text": True, "timeout": timeout}
    if platform.system() == "Windows":
        run_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    try:
        proc = subprocess.run(args, **run_kwargs)
    except subprocess.TimeoutExpired:
        log("claude call timed out")
        return ""
    except FileNotFoundError:
        log("claude binary not found on PATH")
        return ""
    except Exception as exc:
        log(f"claude call failed: {exc}")
        return ""
    if proc.returncode != 0:
        log(f"claude exited with code {proc.returncode}: {(proc.stderr or '').strip()[:500]}")
    return (proc.stdout or "").strip()


def claude_json(prompt, allowed_tools=None, timeout=None):
    return extract_json(claude_cli(prompt, allowed_tools, timeout))


def mcp_tools(*mcp_commands):
    """Only Robinhood MCP tools are ever referenced -- this is the sole
    broker rail. Equity-only: no option tool names appear anywhere."""
    s = CONFIG["mcp_server"]
    if mcp_commands:
        return [f"mcp__{s}__{c}" for c in mcp_commands]
    return [f"mcp__{s}__*"]


# ============================================================================
# Broker reads and writes -- equity only, every call scoped to the exact
# Robinhood MCP tool(s) it needs.
# ============================================================================
def get_account_snapshot():
    """Fresh, live broker state: settled cash plus every open equity
    position with its current price attached. Nothing here is cached or
    reused from a previous tick."""
    portfolio_prompt = (
        "Make get_portfolio call. Reply with ONLY a JSON object, no prose, "
        'shaped exactly like: {"cash": 0.0}.'
    )
    portfolio_res = claude_json(portfolio_prompt, allowed_tools=mcp_tools("get_portfolio"))
    if "error" in portfolio_res:
        return None, f"portfolio lookup failed: {portfolio_res['error']}"

    positions_prompt = (
        "Make get_equity_positions call. Reply with ONLY a JSON object, no prose, "
        'shaped exactly like: {"positions": '
        '[{"symbol": "ABC", "quantity": 0.0, "average_buy_price": 0.0}]}.'
    )
    positions_res = claude_json(positions_prompt, allowed_tools=mcp_tools("get_equity_positions"))
    if "error" in positions_res:
        return None, f"equity positions lookup failed: {positions_res['error']}"

    positions = [p for p in (positions_res.get("positions") or []) if valid_stock_position(p)]
    if positions:
        symbols = [p["symbol"] for p in positions]
        quotes, err = get_quotes(symbols)
        if err:
            return None, f"quote lookup failed for held positions: {err}"
        for p in positions:
            q = quotes.get(p["symbol"]) or {}
            last = q.get("last")
            if last is None:
                return None, f"no current price for held position {p['symbol']}"
            p["quantity"] = float(p["quantity"])
            p["average_buy_price"] = float(p["average_buy_price"])
            p["current_price"] = float(last)

    return {
        "settled_cash": float(portfolio_res.get("cash") or 0.0),
        "positions": positions,
    }, None


def valid_stock_position(position):
    if not isinstance(position, dict):
        return False
    symbol = str(position.get("symbol") or "").strip().upper()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalpha():
        return False
    try:
        return float(position.get("quantity") or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def get_quotes(symbols):
    prompt = (
        f"Get current equity quotes for these symbols: {', '.join(symbols)}. "
        f"For each, compute day change percent as "
        f"(last - previous_close) / previous_close * 100. "
        f"Reply with ONLY a JSON object mapping symbol to fields, no prose, "
        f'shaped exactly like: {{"ABC": {{"last": 0.0, "day_change_pct": 0.0}}}}'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools("get_equity_quotes"))
    if "error" in res:
        return None, res["error"]
    return res, None


def get_volume_momentum(symbols):
    """Trailing 5-trading-day volume trend per symbol -- deliberately NOT a
    single day's volume. Cross-checks two independent broker-rail sources so
    the read isn't hostage to one noisy metric:
      - get_equity_historicals: daily volume bars, used to compare the mean
        of the most recent 5 trading days against the 5 trading days before
        that (volume_momentum_pct).
      - get_equity_technical_indicators (OBV): confirms whether cumulative
        On-Balance-Volume is actually rising over that same window, since a
        raw volume average can rise on heavy two-sided (not just buying)
        activity.
    Best-effort: callers should treat a failure here as missing enrichment
    data, not a reason to abandon the scan."""
    prompt = (
        f"For these equity symbols: {', '.join(symbols)}, make BOTH calls: "
        f"(1) get_equity_historicals with interval=day, bounds=regular, "
        f"covering roughly the last 15 calendar days, to get daily volume "
        f"bars; (2) get_equity_technical_indicators with type=obv, "
        f"interval=day, covering that same range, to get On-Balance-Volume. "
        f"For each symbol, using the historicals volume bars: take the most "
        f"recent 5 trading days as the recent window and the 5 trading days "
        f"immediately before that as the baseline window, then compute "
        f"avg_volume_recent5 (mean volume, recent window), avg_volume_prior5 "
        f"(mean volume, baseline window), and volume_momentum_pct = "
        f"(avg_volume_recent5 - avg_volume_prior5) / avg_volume_prior5 * 100. "
        f"Using the OBV series, report obv_trend as \"rising\" if the latest "
        f"OBV value is clearly above its value from 5 trading days ago, "
        f"\"falling\" if clearly below, else \"flat\". "
        f"Reply with ONLY a JSON object mapping symbol to fields, no prose, "
        f'shaped exactly like: {{"ABC": {{"volume_momentum_pct": 0.0, '
        f'"obv_trend": "rising"}}}}.'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools(
        "get_equity_historicals", "get_equity_technical_indicators"))
    if "error" in res:
        return None, res["error"]
    return res, None


def is_tradable_equity(symbol):
    """Guard for names the AI proposes outside the seed universe -- confirm
    the broker actually recognizes and can trade this equity before any
    order is placed against it."""
    prompt = (
        f"Make get_equity_tradability call for symbol {symbol}. Reply with ONLY "
        f'a JSON object, no prose, shaped exactly like: {{"tradable": true}}.'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools("get_equity_tradability"))
    if "error" in res:
        log(f"tradability check failed for {symbol}: {res['error']}")
        return False
    return bool(res.get("tradable"))


def place_buy(symbol, dollars):
    if not CONFIG["enable_live_buys"]:
        return None, "live buys disabled (CONFIG['enable_live_buys'] is False)"
    acct = CONFIG["account_number"]
    prompt = (
        f"On Robinhood account {acct}, FIRST review, THEN place a real market "
        f"BUY of {symbol} for a dollar amount of {dollars:.2f} (dollar-based, "
        f"fractional allowed). After it fills, reply with ONLY a JSON object, "
        f'no prose, shaped exactly like: {{"filled": true, "symbol": "{symbol}", '
        f'"avg_price": 0.0, "quantity": 0.0, "order_id": "..."}}. If it did not '
        f'fill, reply {{"filled": false, "reason": "..."}}.'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools("review_equity_order", "place_equity_order"))
    if "error" in res:
        return None, res["error"]
    if not res.get("filled"):
        return None, res.get("reason", "buy not filled")
    return res, None


def place_sell_all(symbol, quantity):
    acct = CONFIG["account_number"]
    prompt = (
        f"On Robinhood account {acct}, place a real market SELL closing the "
        f"entire {symbol} position (quantity {quantity}). After it fills, reply "
        f'with ONLY a JSON object, no prose, shaped exactly like: {{"filled": '
        f'true, "symbol": "{symbol}", "avg_price": 0.0, "quantity": 0.0, '
        f'"order_id": "..."}}. If it did not fill, reply {{"filled": false, '
        f'"reason": "..."}}.'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools("place_equity_order"))
    if "error" in res:
        return None, res["error"]
    if not res.get("filled"):
        return None, res.get("reason", "sell not filled")
    return res, None


# ============================================================================
# The single AI judgment for entries: pick one name to buy, or pass. Never
# used for exits -- the stop-loss and close-out guard are deterministic.
# ============================================================================
def build_pick_prompt(candidates):
    lines = []
    for c in candidates:
        line = (
            f"- {c['symbol']}: {c['day_change_pct']:+.2f}% on the day, last {c['last']:.2f} "
            + ("(momentum long -- trading up)" if c["direction"] == "up"
               else "(dip-buy -- trading down hard, look for a bounce)")
        )
        vmp = c.get("volume_momentum_pct")
        if vmp is not None:
            line += f"; 5-day avg volume vs prior 5 days: {vmp:+.1f}%"
            obv = c.get("obv_trend")
            if obv:
                line += f", OBV {obv}"
        else:
            line += "; 5-day volume trend unavailable"
        lines.append(line)

    guidance = CONFIG.get("extra_pick_guidance", "").strip()
    guidance_block = f"\n\nAdditional standing instructions from the operator: {guidance}" if guidance else ""

    return (
        "You are picking ONE equity to buy right now in a high-speed intraday "
        "trading loop. Instrument is always common stock/shares -- no options, "
        "no derivatives. Here are today's movers from two seed watchlists (day "
        "change percent and last price), plus each name's trailing 5-day volume "
        "trend (mean volume over the last 5 trading days vs. the 5 trading days "
        "before that) and its On-Balance-Volume trend over the same window -- "
        "use these to judge sustained interest, not just today's single-day "
        "move. A big day_change_pct on a flat or falling 5-day volume trend is "
        "more likely a one-day spike than real continuation; a rising 5-day "
        "volume trend with rising OBV backing the move is a stronger case. "
        "Names marked \"momentum long\" are up "
        "on the day and the case is continuation. Names marked \"dip-buy\" are "
        "down hard (more than the configured drop threshold) and the case is a "
        "reversal/bounce -- only take one of these if you see a real reason the "
        "drop is overdone or already stabilizing (e.g. no fresh bad news, "
        "support holding, drop is index/sector-wide rather than company-specific), "
        "not just because it's cheaper now:\n"
        + "\n".join(lines)
        + "\n\nThese watchlists are only a guideline, not a boundary: if you know of "
        "a better, currently liquid and actively-traded US-listed equity opportunity "
        "right now (momentum or dip), you may pick that symbol instead, even if it's "
        "not listed above. Avoid illiquid or halted names, and avoid anything "
        "reporting earnings today."
        + guidance_block
        + "\nRate your conviction high, medium, or low, and pick the single best "
        "trade, or pass. Reply with ONLY a JSON object, no prose, shaped exactly "
        'like: {"decision": "buy", "symbol": "ABC", "conviction": "high", '
        '"reason": "one short line"} or {"decision": "pass", "reason": "one short line"}.'
    )


def pick_via_claude(prompt):
    # Broker MCP tools are deliberately NOT allowed here -- the pick step
    # only reasons and may WebSearch; it never touches the account directly.
    return claude_json(prompt, allowed_tools=["WebSearch"])


def pick_via_openai(prompt):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"error": "OPENAI_API_KEY not set"}
    try:
        data = http_post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            {"model": CONFIG["openai_model"], "messages": [{"role": "user", "content": prompt}]},
            CONFIG["http_timeout_sec"],
        )
        text = data["choices"][0]["message"]["content"]
        return extract_json(text)
    except Exception as exc:
        return {"error": f"openai call failed: {exc}"}


def pick_name(candidates):
    prompt = build_pick_prompt(candidates)
    provider = CONFIG["pick_provider"].lower()
    if provider == "claude":
        res = pick_via_claude(prompt)
    elif provider == "openai":
        res = pick_via_openai(prompt)
    else:
        return None, f"unknown pick_provider '{provider}' (use 'claude' or 'openai')"
    if "error" in res:
        return None, res["error"]
    return res, None


# ============================================================================
# Session clock -- regular exchange hours only, per SKILLS.md.
# ============================================================================
def now_tz():
    return dt.datetime.now(ZoneInfo(CONFIG["tz"]))


def parse_hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


def in_session(now):
    if now.weekday() >= 5 and not CONFIG.get("ignore_weekday"):
        return False
    oh, om = parse_hhmm(CONFIG["session_open"])
    ch, cm = parse_hhmm(CONFIG["session_close"])
    open_t = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    close_t = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return open_t <= now <= close_t


def in_close_out_window(now):
    ch, cm = parse_hhmm(CONFIG["session_close"])
    close_t = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    minutes_to_close = (close_t - now).total_seconds() / 60.0
    return 0 <= minutes_to_close <= CONFIG["close_out_minutes_before_close"]


# ============================================================================
# Position management -- deterministic. The hard $0.50 stop-loss and the
# close-out guard are the only exit rules; take-profit is uncapped.
# ============================================================================
def manage_positions(snapshot, approaching_close):
    for pos in snapshot["positions"]:
        symbol = pos["symbol"]
        quantity = pos["quantity"]
        entry = pos["average_buy_price"]
        current = pos["current_price"]
        drop = entry - current

        if approaching_close:
            reason = "session close-out guard"
        elif drop >= CONFIG["stop_loss_usd"]:
            reason = f"hard stop-loss (down ${drop:.2f}/share, limit ${CONFIG['stop_loss_usd']:.2f})"
        else:
            log(f"{symbol}: holding, P&L ${(current - entry) * quantity:+.2f} "
                f"({current - entry:+.2f}/share). Upside uncapped.")
            continue

        notify(f"{symbol}: selling all {quantity} shares at ~{current:.2f} ({reason}).")
        fill, err = place_sell_all(symbol, quantity)
        if err:
            notify(f"{symbol}: SELL FAILED: {err}. Will retry next tick.")
            continue
        proceeds = float(fill["avg_price"]) * float(fill["quantity"])
        cost = entry * quantity
        notify(f"{symbol}: closed at {float(fill['avg_price']):.2f}. Realized {proceeds - cost:+.2f}.")


# ============================================================================
# Candidate scan -- shared by the live entry path and --simulation. Quotes
# both seed universes and returns day movers tagged by direction:
#   up_universe names trading up at least candidate_min_daychg but no more
#   than candidate_max_daychg (momentum longs -- above the max is treated as
#   a one-day outlier, not a candidate) and down_universe names trading down
#   more than candidate_min_down_daychg (dip-buy candidates -- a potential
#   bounce).
# ============================================================================
def scan_candidates(direction=None):
    """direction: None scans both universes (default); "up" or "down"
    restricts the scan to just that side, e.g. for --up/--down."""
    up_universe = list(dict.fromkeys(CONFIG["up_universe"])) if direction in (None, "up") else []
    down_universe = list(dict.fromkeys(CONFIG["down_universe"])) if direction in (None, "down") else []
    all_symbols = list(dict.fromkeys(up_universe + down_universe))
    if not all_symbols:
        return [], None

    quotes, err = get_quotes(all_symbols)
    if err:
        return None, err

    candidates = []
    for sym in up_universe:
        q = quotes.get(sym) or {}
        dc, last = q.get("day_change_pct"), q.get("last")
        if dc is None or last is None:
            continue
        dc = float(dc)
        if dc > CONFIG["candidate_max_daychg"]:
            log(f"scan: {sym} up {dc:+.2f}% exceeds candidate_max_daychg "
                f"({CONFIG['candidate_max_daychg']:.1f}%), excluding as an outlier.")
            continue
        if dc >= CONFIG["candidate_min_daychg"]:
            candidates.append({"symbol": sym, "day_change_pct": dc,
                                "last": float(last), "direction": "up"})
    for sym in down_universe:
        q = quotes.get(sym) or {}
        dc, last = q.get("day_change_pct"), q.get("last")
        if dc is None or last is None:
            continue
        if float(dc) <= -CONFIG["candidate_min_down_daychg"]:
            candidates.append({"symbol": sym, "day_change_pct": float(dc),
                                "last": float(last), "direction": "down"})

    candidates.sort(key=lambda c: abs(c["day_change_pct"]), reverse=True)

    if candidates:
        vol, err = get_volume_momentum([c["symbol"] for c in candidates])
        if err:
            log(f"scan: volume momentum lookup failed, continuing without it: {err}")
            vol = {}
        for c in candidates:
            v = vol.get(c["symbol"]) or {}
            c["volume_momentum_pct"] = v.get("volume_momentum_pct")
            c["obv_trend"] = v.get("obv_trend")

    return candidates, None


# ============================================================================
# Entry logic -- unlimited per SKILLS.md: attempted every tick, no daily cap.
# ============================================================================
def maybe_enter(snapshot, direction=None):
    settled = snapshot["settled_cash"]
    if settled < CONFIG["min_trade_usd"]:
        log(f"entry: settled cash {settled:.2f} below min_trade_usd, skipping.")
        return

    held_symbols = {p["symbol"] for p in snapshot["positions"]}

    candidates, err = scan_candidates(direction)
    if err:
        log(f"entry: quotes failed: {err}")
        return

    if not candidates:
        log("entry: no candidates clear the up/down day-change floors.")
        return

    pick, err = pick_name(candidates)
    if err:
        log(f"entry: pick failed: {err}")
        return
    if pick.get("decision") != "buy":
        log(f"entry: pass -- {pick.get('reason', 'no reason given')}")
        return

    symbol = str(pick.get("symbol", "")).strip().upper()
    if not symbol:
        log("entry: pick had no symbol, skipping.")
        return
    if symbol in held_symbols:
        log(f"entry: already holding {symbol}, skipping to avoid pyramiding.")
        return

    conviction = str(pick.get("conviction", "")).lower()
    if conviction not in CONFIG["conviction_accept"]:
        log(f"entry: {symbol} was {conviction} conviction, below the gate. No trade.")
        return

    if not is_tradable_equity(symbol):
        log(f"entry: {symbol} failed the broker tradability check. No trade.")
        return

    dollars = round(settled * CONFIG["deploy_fraction"], 2)
    if dollars < CONFIG["min_trade_usd"]:
        log(f"entry: sized trade {dollars:.2f} below min_trade_usd, skipping.")
        return

    notify(f"Entering {symbol} ({conviction} conviction): {pick.get('reason', '')}. "
           f"Deploying {dollars:.2f}.")
    fill, err = place_buy(symbol, dollars)
    if err:
        notify(f"{symbol}: BUY FAILED/SKIPPED: {err}.")
        return
    notify(f"{symbol}: filled {fill['quantity']} at {float(fill['avg_price']):.2f}. "
           f"Stop-loss active at ${CONFIG['stop_loss_usd']:.2f}/share below entry.")


# ============================================================================
# One tick -- fully stateless. Every call re-reads live broker state.
# ============================================================================
def tick(simulation=False, direction=None):
    now = now_tz()
    if not in_session(now):
        log("Outside regular exchange hours. Idle.")
        return

    snapshot, err = get_account_snapshot()
    if err or snapshot is None:
        log(f"tick: account snapshot failed: {err}. Skipping this tick.")
        return

    approaching_close = in_close_out_window(now)
    log(f"tick: {now.isoformat()} cash={snapshot['settled_cash']:.2f} "
        f"positions={[p['symbol'] for p in snapshot['positions']]} "
        f"approaching_close={approaching_close}")

    if simulation:
        log("[SIMULATION] Evaluating only -- no sells or buys will be placed.")
        for pos in snapshot["positions"]:
            drop = pos["average_buy_price"] - pos["current_price"]
            would_sell = approaching_close or drop >= CONFIG["stop_loss_usd"]
            log(f"[SIMULATION] {pos['symbol']}: drop ${drop:+.2f}/share, would_sell={would_sell}")
        if not approaching_close:
            settled = snapshot["settled_cash"]
            if settled >= CONFIG["min_trade_usd"]:
                candidates, qerr = scan_candidates(direction)
                if not qerr and candidates:
                    pick, perr = pick_name(candidates)
                    if not perr:
                        log(f"[SIMULATION] pick: {pick}")
        return

    if snapshot["positions"]:
        manage_positions(snapshot, approaching_close)

    if approaching_close:
        log("Within close-out window; no new entries.")
        return

    maybe_enter(snapshot, direction)

    return


# ============================================================================
# Provider comparison -- one scan, the same candidate list sent to every pick
# provider. Read-only: no account snapshot, no cash gate, never places an
# order. Useful for judging the pick step even with $0 settled cash.
# ============================================================================
def compare_providers(direction=None, providers=("claude", "openai")):
    if not in_session(now_tz()):
        log("compare: outside regular exchange hours; quotes may be stale.")

    candidates, err = scan_candidates(direction)
    if err:
        log(f"compare: quotes failed: {err}")
        return
    if not candidates:
        log("compare: no candidates clear the up/down day-change floors.")
        return

    log(f"compare: {len(candidates)} candidates: "
        + ", ".join(f"{c['symbol']} {c['day_change_pct']:+.2f}%" for c in candidates))

    original = CONFIG["pick_provider"]
    picks = {}
    try:
        for provider in providers:
            CONFIG["pick_provider"] = provider
            pick, perr = pick_name(candidates)
            picks[provider] = pick
            log(f"compare: {provider}: {perr or json.dumps(pick)}")
    finally:
        CONFIG["pick_provider"] = original

    chosen = {}
    for provider, pick in picks.items():
        if pick is None:
            chosen[provider] = "error"
        elif pick.get("decision") == "buy":
            chosen[provider] = str(pick.get("symbol", "")).strip().upper()
        else:
            chosen[provider] = "pass"
    verdict = "AGREE" if len(set(chosen.values())) == 1 else "DISAGREE"
    log(f"compare: {verdict} -- " + ", ".join(f"{p}={s}" for p, s in chosen.items()))


def main():
    ap = argparse.ArgumentParser(description="Stateless high-speed equity trader (Robinhood MCP).")
    ap.add_argument("--once", action="store_true", help="run a single tick (for a scheduler)")
    ap.add_argument("--loop", action="store_true", help="run a foreground poll loop")
    ap.add_argument("--interval", type=int, default=None,
                     help="seconds between ticks (default: CONFIG['tick_interval_sec'])")
    ap.add_argument("--simulation", action="store_true",
                     help="dry-run: evaluate positions and the pick, place no orders")
    ap.add_argument("--session-open", type=str, default=None,
                     help="override CONFIG['session_open'], e.g. 09:30")
    ap.add_argument("--session-close", type=str, default=None,
                     help="override CONFIG['session_close'], e.g. 16:00")
    ap.add_argument("--ignore-weekday", action="store_true",
                     help="testing only: treat weekends as in-session too")
    ap.add_argument("--compare-providers", action="store_true",
                     help="scan once and ask both claude and openai for a pick on the "
                          "same candidates; read-only, ignores cash, places no orders")
    scan_group = ap.add_mutually_exclusive_group()
    scan_group.add_argument("--up", action="store_true",
                             help="only scan up_universe (momentum longs); skip down_universe")
    scan_group.add_argument("--down", action="store_true",
                             help="only scan down_universe (dip-buy candidates); skip up_universe")
    args = ap.parse_args()

    if CONFIG["account_number"] == "YOUR_ACCOUNT_NUMBER_HERE":
        sys.exit("Set CONFIG['account_number'] (or the ROBINHOOD_ACCOUNT_NUMBER "
                 "env var) to your real Robinhood account number first.")

    if args.compare_providers:
        direction = "up" if args.up else "down" if args.down else None
        log(f"compare-providers scan={direction or 'both'}")
        compare_providers(direction)
        return

    if not args.once and not args.loop:
        ap.print_help()
        sys.exit(1)

    interval = args.interval if args.interval is not None else CONFIG["tick_interval_sec"]
    if args.session_open is not None:
        CONFIG["session_open"] = args.session_open
    if args.session_close is not None:
        CONFIG["session_close"] = args.session_close
    if args.ignore_weekday:
        CONFIG["ignore_weekday"] = True

    direction = "up" if args.up else "down" if args.down else None

    log(f"provider={CONFIG['pick_provider']} enable_live_buys={CONFIG['enable_live_buys']} "
        f"simulation={args.simulation} interval={interval} "
        f"session={CONFIG['session_open']}-{CONFIG['session_close']} "
        f"ignore_weekday={CONFIG['ignore_weekday']} scan={direction or 'both'}")

    if args.once:
        tick(simulation=args.simulation, direction=direction)
        return

    log("Starting loop. Ctrl+C to stop.")
    while True:
        try:
            tick(simulation=args.simulation, direction=direction)
        except KeyboardInterrupt:
            log("Stopped.")
            break
        except Exception as exc:
            log(f"tick crashed (continuing): {exc}")
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
