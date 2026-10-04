#!/usr/bin/env python3
"""
high_speed_trader.py

A stateless, high-speed, EQUITY-ONLY intraday trading loop for a Robinhood
account, built to the rules in SKILLS.md:
  - Unlimited trades per session, on a fast fixed-interval tick loop.
  - Hard stop-loss: sell a position the moment it's down 5% from its
    entry (average buy price). Take-profit is uncapped -- winners are
    never force-sold while ahead.
  - Stock/equity instrument only. No options.
  - One seed universe, watched for both momentum-long (bull) and dip-buy
    (bear) setups, is a guideline, not a boundary -- the AI may propose any
    other liquid, actively-traded US equity, which is then verified with
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
from concurrent.futures import ThreadPoolExecutor
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
    "account_number": os.environ.get("ROBINHOOD_ACCOUNT_NUMBER", "YOUR_ROBINHOOD_ACCOUNT_NUMBER"),

    # Broker MCP client. Claude Code CLI is currently the supported bridge.
    "mcp_client": os.environ.get("MCP_CLIENT", "claude").strip().lower() or "claude",
    "mcp_client_bin": os.environ.get("MCP_CLIENT_BIN", "claude").strip() or "claude",
    # MCP server name exactly as it shows in the configured client.
    "mcp_server": os.environ.get("MCP_SERVER", "robinhood").strip() or "robinhood",

    # ----- which AI proposes the entry pick -----
    # "claude": uses your Claude Code CLI. No API key. Can WebSearch for
    #           fresh catalysts out of the box.
    # "openai": uses the OpenAI chat completions API. Needs OPENAI_API_KEY
    #           set as an environment variable.
    "pick_provider": "openai",
    # CLAUDE_MODEL in .env overrides the default; applied only on calls
    # that allow WebSearch (the pick step).
    "claude_model": os.environ.get("CLAUDE_MODEL", "").strip() or "sonnet",
    # OPENAI_MODEL in .env overrides the default; used on every openai call.
    "openai_model": os.environ.get("OPENAI_MODEL", "").strip() or "gpt-6.1-sol",

    # Your own standing instructions to the AI, appended to every pick
    # prompt. Leave empty for none.
    "extra_pick_guidance": "",

    # ----- seed universe: a guideline, not a hard boundary. The AI may
    # propose a name outside this list; it is verified with the broker
    # before any order is placed. -----
    #
    # universe: liquid, actively-traded names watched for BOTH momentum-long
    # (bull) and dip-buy (bear) setups -- every symbol is checked against
    # the day-change window each scan (see scan_candidates).
    "universe": [
        "AAOI", "AEHR", "ALAB", "AMAT", "AMD", "AMZN", "APLD", "APP",
        "ASTS", "AVAV", "AVGO", "AXTI", "BE", "BKSY", "BOT", "CAT",
        "CEG", "CIEN", "CIFR", "COHR", "CRDO", "EOSE", "FLY", "FORM",
        "FPS", "FTAI", "GEV", "GLW", "GOOGL", "HUT", "INTC", "IONQ",
        "IPGP", "IREN", "ISRG", "KLAR", "LITE", "LMND", "LMT", "LRCX",
        "MDB", "META", "MOD", "MRVL", "MSFT", "MU", "MXL", "NVDA",
        "NVTS", "OKLO", "ON", "OUST", "PANW", "PENG", "PGY", "PURR",
        "QNT", "RGTI", "RKLB", "ROK", "RTX", "RVII", "SMCI", "SMTC",
        "SNDK", "SOFI", "SOLS", "SPCX", "TREE", "TSLA", "UBER", "VELO",
        "VIAV", "VICR", "VPG", "VRT", "VSAT", "VST", "WULF", "WYFI",
        "XYZ", "ZS",
    ],
    # Day-change window for a universe name to become a candidate: between
    # candidate_min_daychg and candidate_max_daychg percent, inclusive. Up
    # names are momentum-long (bull), down names are dip-buy (bear); names
    # outside the window are excluded as one-day outliers (e.g. halt/news-
    # driven moves) rather than fed to the pick step.
    "candidate_min_daychg": -8.0,
    "candidate_max_daychg": 8.0,

    # ----- entry gates (deterministic, applied after the trend lookup) -----
    # Price must be above the 200-day SMA, or between the 50-day and 200-day
    # SMA (either order) -- e.g. a name pulled back under its 200-day SMA but
    # still holding its 50-day SMA qualifies.
    # RSI(rsi_period) must be above rsi_min (not oversold) and at or below
    # rsi_max -- anything above rsi_max is overbought and rejected.
    "rsi_period": 14,
    "rsi_min": 30.0,
    "rsi_max": 70.0,
    # Price must sit in the fib_zone retracement band of the last swing
    # (highest high / lowest low over fib_lookback_days calendar days).
    # Upswing (low came first): retracement measured down from the high.
    # Downswing (high came first): retracement measured up from the low.
    "fib_lookback_days": 180,
    # 0.618 is the golden ratio the zone is centred on; the report shows how
    # far each pass sits from it, on both upswings and downswings.
    "fib_zone": (0.5, 0.764),
    "fib_golden": 0.618,
    # Forward P/E must be positive and below forward_pe_max. Forward EPS is
    # the next four quarters of consensus EPS estimates (get_earnings_results,
    # quarters not yet reported); when fewer than four are published, their
    # mean is annualized (x4). Zero or negative forward EPS rejects.
    "forward_pe_max": 50.0,

    # ----- sizing / risk (deterministic, never touched by the AI) -----
    "deploy_fraction": 0.25,        # fraction of settled cash per new entry
    "min_trade_usd": 25.0,          # skip an entry too small to matter
    "conviction_accept": ["high", "medium"],
    "stop_loss_pct": 5.0,           # hard stop: exit if price is down this percent from entry
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

    "mcp_client_timeout_sec": int(os.environ.get("MCP_CLIENT_TIMEOUT_SEC", "240")),
    # The indicator tool takes one symbol per call (4 calls per symbol), so
    # the trend lookup is split into batches run as parallel claude calls --
    # one call for the whole candidate list blows through the timeout.
    "trend_batch_size": 8,
    "trend_max_workers": 4,
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
# The configured MCP client bridge. Claude Code CLI is currently the only
# supported bridge and is also the default pick brain. Strict JSON only.
# ============================================================================
def claude_cli(prompt, allowed_tools=None, timeout=None):
    """Run `claude -p` headless and return raw stdout text, or '' on failure."""
    if CONFIG["mcp_client"] != "claude":
        log(f"unsupported MCP_CLIENT '{CONFIG['mcp_client']}'; currently supported: claude")
        return ""
    timeout = timeout or CONFIG["mcp_client_timeout_sec"]
    prompt = f"For account {CONFIG['account_number']}, {prompt}"
    args = [CONFIG["mcp_client_bin"], "-p", prompt, "--dangerously-skip-permissions",
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
        log("MCP client call timed out")
        return ""
    except FileNotFoundError:
        log(f"MCP client executable not found: {CONFIG['mcp_client_bin']}")
        return ""
    except Exception as exc:
        log(f"MCP client call failed: {exc}")
        return ""
    if proc.returncode != 0:
        log(f"MCP client exited with code {proc.returncode}: {(proc.stderr or '').strip()[:500]}")
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


def get_trend_signals(symbols):
    """Daily moving averages per symbol -- 10-day EMA, 21-day EMA, 50-day SMA,
    and 200-day SMA -- used to classify each candidate's longer-term trend as
    bullish, bearish, or neutral (see classify_trend). The AI only ever gets
    the raw numbers here; the bull/bear call itself is deterministic Python,
    same as the stop-loss.
    Runs in batches of CONFIG["trend_batch_size"] symbols, in parallel, so a
    single failed or slow batch only loses those symbols.
    Best-effort: callers should treat a failure here as missing enrichment
    data, not a reason to abandon the scan."""
    size = max(1, CONFIG["trend_batch_size"])
    batches = [symbols[k:k + size] for k in range(0, len(symbols), size)]
    merged, errors = {}, []
    with ThreadPoolExecutor(max_workers=CONFIG["trend_max_workers"]) as pool:
        for batch, (res, err) in zip(batches, pool.map(_trend_signals_batch, batches)):
            if err:
                errors.append(f"{','.join(batch)}: {err}")
            else:
                merged.update(res)
    if errors:
        log(f"scan: trend signal batches failed: {'; '.join(errors)}")
    if not merged and errors:
        return None, errors[0]
    return merged, None


def _trend_signals_batch(symbols):
    """One claude call for one batch of get_trend_signals."""
    lookback = CONFIG["fib_lookback_days"]
    prompt = (
        f"For these equity symbols: {', '.join(symbols)}, make FIVE "
        f"get_equity_technical_indicators calls per symbol -- interval=day, "
        f"bounds=regular, output=latest, start_time roughly 400 calendar days "
        f"before now (so the 200-day SMA has enough bars): (1) type=ema "
        f"period=10, (2) type=ema period=21, (3) type=sma period=50, (4) "
        f"type=sma period=200, (5) type=rsi period={CONFIG['rsi_period']}. "
        f"For each symbol report the latest value of each. ALSO make one "
        f"get_earnings_results call per symbol and report "
        f"upcoming_eps_estimates: the eps.estimate values of the quarters "
        f"whose eps.actual is null (not yet reported), oldest first, as "
        f"numbers ([] if none). ALSO make one "
        f"get_equity_historicals call for all of the symbols with "
        f"interval=day, bounds=regular, start_time {lookback} calendar days "
        f"before now, and for each symbol report swing_high (the highest bar "
        f"high in that range) with swing_high_date (YYYY-MM-DD of that bar), "
        f"and swing_low (the lowest bar low in that range) with "
        f"swing_low_date. Reply with ONLY a JSON object mapping symbol to "
        f'fields, no prose, shaped exactly like: {{"ABC": {{"ema10": 0.0, '
        f'"ema21": 0.0, "sma50": 0.0, "sma200": 0.0, "rsi": 0.0, '
        f'"swing_high": 0.0, "swing_high_date": "2026-01-01", '
        f'"swing_low": 0.0, "swing_low_date": "2026-01-01", '
        f'"upcoming_eps_estimates": [0.0, 0.0]}}}}.'
    )
    res = claude_json(prompt, allowed_tools=mcp_tools(
        "get_equity_technical_indicators", "get_equity_historicals",
        "get_earnings_results"))
    if "error" in res:
        return None, res["error"]
    return res, None


def classify_trend(price, ema10, ema21, sma50, sma200):
    """Deterministic bull/bear call from moving averages -- never left to the
    AI, same philosophy as the hard stop-loss:
      - bullish: 10-day EMA above the 21-day EMA AND price holding above
        both the 50-day and 200-day SMA.
      - bearish: price has broken below all three levels (10-day EMA at or
        below the 21-day EMA, and price under both SMAs).
      - anything else (mixed signals) is neutral.
    Returns None if any input is missing."""
    if None in (price, ema10, ema21, sma50, sma200):
        return None
    ema_bullish = ema10 > ema21
    above_sma50 = price > sma50
    above_sma200 = price > sma200
    if ema_bullish and above_sma50 and above_sma200:
        return "bullish"
    if not ema_bullish and not above_sma50 and not above_sma200:
        return "bearish"
    return "neutral"


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
def fib_retracement(price, swing_high, swing_high_date, swing_low, swing_low_date):
    """Where price sits in the last swing, as a Fibonacci retracement ratio.
      - upswing (low printed before the high): ratio = (high - price) / range,
        i.e. how far price has pulled back down from the high.
      - downswing (high printed before the low): ratio = (price - low) / range,
        i.e. how far price has bounced back up from the low.
    Returns {"swing": "up"|"down", "ratio", "zone_low", "zone_high",
    "in_zone"} where zone_low/zone_high are the prices bounding
    CONFIG["fib_zone"], or None if any input is missing or the range is flat."""
    if None in (price, swing_high, swing_low) or not swing_high_date or not swing_low_date:
        return None
    rng = swing_high - swing_low
    if rng <= 0:
        return None
    lo_r, hi_r = CONFIG["fib_zone"]
    if str(swing_low_date) <= str(swing_high_date):
        swing = "up"
        ratio = (swing_high - price) / rng
        a, b = swing_high - hi_r * rng, swing_high - lo_r * rng
    else:
        swing = "down"
        ratio = (price - swing_low) / rng
        a, b = swing_low + lo_r * rng, swing_low + hi_r * rng
    return {"swing": swing, "ratio": ratio, "zone_low": a, "zone_high": b,
            "in_zone": lo_r <= ratio <= hi_r}


def daychg_gate(dc):
    """Returns None if day change dc (percent) is inside the candidate
    window, else a short rejection reason."""
    lo, hi = CONFIG["candidate_min_daychg"], CONFIG["candidate_max_daychg"]
    if not lo <= dc <= hi:
        return f"day change {dc:+.2f}% outside {lo:+.1f}%..{hi:+.1f}% window"
    return None


def forward_pe(price, upcoming_eps_estimates):
    """Forward P/E from the next four quarters of consensus EPS estimates.
    Fewer than four published estimates are annualized from their mean.
    Returns {"forward_eps", "forward_pe", "quarters"}; forward_pe is None when
    forward EPS is zero or negative. Returns None if there are no estimates."""
    ests = []
    for v in (upcoming_eps_estimates or [])[:4]:
        try:
            ests.append(float(v))
        except (TypeError, ValueError):
            continue
    if price is None or not ests:
        return None
    eps = sum(ests) / len(ests) * 4
    return {"forward_eps": eps, "forward_pe": price / eps if eps > 0 else None,
            "quarters": len(ests)}


def sma_gate(c):
    price, sma50, sma200 = c["last"], c.get("sma50"), c.get("sma200")
    if sma200 is None:
        return "200-day SMA unavailable"
    if price <= sma200:
        if sma50 is None:
            return f"price {price:.2f} not above 200sma {sma200:.2f} and 50sma unavailable"
        if price <= sma50:
            return (f"price {price:.2f} not above 200sma {sma200:.2f} "
                    f"nor between it and 50sma {sma50:.2f}")
    return None


def rsi_gate(c):
    rsi = c.get("rsi")
    if rsi is None:
        return "RSI unavailable"
    if rsi <= CONFIG["rsi_min"]:
        return f"RSI {rsi:.1f} not above {CONFIG['rsi_min']:.0f}"
    if rsi > CONFIG["rsi_max"]:
        return f"RSI {rsi:.1f} overbought (> {CONFIG['rsi_max']:.0f})"
    return None


def fib_gate(c):
    price, fib = c["last"], c.get("fib")
    if fib is None:
        return "swing high/low unavailable"
    if not fib["in_zone"]:
        lo_r, hi_r = CONFIG["fib_zone"]
        return (f"price {price:.2f} at {fib['ratio']:.3f} retracement of {fib['swing']}swing, "
                f"outside {lo_r}-{hi_r} zone ({fib['zone_low']:.2f}-{fib['zone_high']:.2f})")
    return None


def forward_pe_gate(c):
    fpe, cap = c.get("fpe"), CONFIG["forward_pe_max"]
    if fpe is None:
        return "forward EPS estimates unavailable"
    if fpe["forward_pe"] is None:
        return f"forward EPS {fpe['forward_eps']:.2f} not positive"
    if fpe["forward_pe"] >= cap:
        return f"forward P/E {fpe['forward_pe']:.1f} not below {cap:.0f}"
    return None


# Deterministic entry gates, never left to the AI, in evaluation order.
ENTRY_GATES = (("sma", sma_gate), ("rsi", rsi_gate), ("fib", fib_gate),
               ("forward_pe", forward_pe_gate))


def entry_gate(c):
    """Returns None if the candidate passes every entry gate, else the first
    rejection reason. Missing data rejects."""
    for _, gate in ENTRY_GATES:
        reason = gate(c)
        if reason:
            return reason
    return None


def enrich_with_signals(candidates):
    """Attach trend/RSI/Fibonacci signals to each candidate in place."""
    trend_signals, err = get_trend_signals([c["symbol"] for c in candidates])
    if err:
        log(f"scan: trend signal lookup failed: {err}")
        trend_signals = {}
    for c in candidates:
        t = trend_signals.get(c["symbol"]) or {}
        for k in ("ema10", "ema21", "sma50", "sma200", "rsi", "swing_high", "swing_low"):
            v = t.get(k)
            c[k] = float(v) if v is not None else None
        c["trend"] = classify_trend(c["last"], c["ema10"], c["ema21"], c["sma50"], c["sma200"])
        c["fib"] = fib_retracement(c["last"], c["swing_high"], t.get("swing_high_date"),
                                   c["swing_low"], t.get("swing_low_date"))
        c["fpe"] = forward_pe(c["last"], t.get("upcoming_eps_estimates"))


def build_pick_prompt(candidates):
    lines = []
    for c in candidates:
        line = (
            f"- {c['symbol']}: {c['day_change_pct']:+.2f}% on the day, last {c['last']:.2f} "
            + ("(momentum long -- trading up)" if c["bull_or_bear"] == "bull"
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

        trend = c.get("trend")
        if trend:
            line += (f"; longer-term trend {trend} (10ema {c['ema10']:.2f} vs "
                      f"21ema {c['ema21']:.2f}, price vs 50sma {c['sma50']:.2f} "
                      f"/ 200sma {c['sma200']:.2f})")
        else:
            line += "; longer-term trend unavailable"
        if c.get("rsi") is not None:
            line += f"; RSI{CONFIG['rsi_period']} {c['rsi']:.1f}"
        fib = c.get("fib")
        if fib:
            line += (f"; at {fib['ratio']:.3f} Fibonacci retracement of the last "
                     f"{fib['swing']}swing (high {c['swing_high']:.2f}, low {c['swing_low']:.2f})")
        fpe = c.get("fpe")
        if fpe and fpe["forward_pe"] is not None:
            line += f"; forward P/E {fpe['forward_pe']:.1f}"
        lines.append(line)

    guidance = CONFIG.get("extra_pick_guidance", "").strip()
    guidance_block = f"\n\nAdditional standing instructions from the operator: {guidance}" if guidance else ""

    return (
        "You are picking ONE equity to buy right now in a high-speed intraday "
        "trading loop. Instrument is always common stock/shares -- no options, "
        "no derivatives. Here are today's movers from the seed watchlist (day "
        "change percent and last price), plus each name's trailing 5-day volume "
        "trend (mean volume over the last 5 trading days vs. the 5 trading days "
        "before that) and its On-Balance-Volume trend over the same window -- "
        "use these to judge sustained interest, not just today's single-day "
        "move. A big day_change_pct on a flat or falling 5-day volume trend is "
        "more likely a one-day spike than real continuation; a rising 5-day "
        "volume trend with rising OBV backing the move is a stronger case. "
        "Each name also carries a longer-term trend read: \"bullish\" means "
        "the 10-day EMA is above the 21-day EMA and price is holding above "
        "both the 50-day and 200-day SMA; \"bearish\" means price has broken "
        "below all three levels; \"neutral\" is mixed. A momentum long in a "
        "bullish trend is the strongest case for continuation; a momentum "
        "long against a bearish trend is more likely a short-lived bounce in "
        "a falling name. A dip-buy in a bearish trend is a real falling "
        "knife -- weight it down hard unless something clearly overrides the "
        "trend (e.g. an index-wide selloff, not company-specific news); a "
        "dip-buy still in a bullish trend is a much safer pullback-to-support "
        "case. "
        "Every name listed has already passed hard filters: price above the "
        "200-day SMA or between the 50-day and 200-day SMA, RSI between 30 and 70 (not oversold, not overbought), "
        "price sitting in the 0.5-0.764 Fibonacci retracement zone of "
        "its last swing high/low -- a classic pullback-entry zone -- and a "
        "positive forward P/E below 50. "
        "Names marked \"momentum long\" are up "
        "on the day and the case is continuation. Names marked \"dip-buy\" are "
        "down hard (more than the configured drop threshold) and the case is a "
        "reversal/bounce -- only take one of these if you see a real reason the "
        "drop is overdone or already stabilizing (e.g. no fresh bad news, "
        "support holding, drop is index/sector-wide rather than company-specific), "
        "not just because it's cheaper now:\n"
        + "\n".join(lines)
        + "\n\nThis watchlist is only a guideline, not a boundary: if you know of "
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
# Position management -- deterministic. The hard 5% stop-loss and the
# close-out guard are the only exit rules; take-profit is uncapped.
# ============================================================================
def stop_loss_usd(entry):
    """Per-share dollar drop from entry that triggers the hard stop."""
    return entry * CONFIG["stop_loss_pct"] / 100.0


def manage_positions(snapshot, approaching_close):
    for pos in snapshot["positions"]:
        symbol = pos["symbol"]
        quantity = pos["quantity"]
        entry = pos["average_buy_price"]
        current = pos["current_price"]
        drop = entry - current
        limit = stop_loss_usd(entry)

        if approaching_close:
            reason = "session close-out guard"
        elif drop >= limit:
            reason = (f"hard stop-loss (down ${drop:.2f}/share, limit ${limit:.2f} = "
                      f"{CONFIG['stop_loss_pct']:g}% of entry {entry:.2f})")
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
# the whole universe and returns names whose day change is within
# candidate_min_daychg..candidate_max_daychg, tagged bull_or_bear: up names
# are bull (momentum long), down names are bear (dip-buy -- a potential
# bounce). Anything outside the window is treated as a one-day outlier. Each surviving candidate is also tagged with its longer-term
# bull/bear trend (classify_trend): bullish means the 10-day EMA is above
# the 21-day EMA and price is holding both the 50-day and 200-day SMA;
# bearish means price has broken below all three levels.
# ============================================================================
def scan_candidates():
    universe = list(dict.fromkeys(CONFIG["universe"]))
    if not universe:
        return [], None

    quotes, err = get_quotes(universe)
    if err:
        return None, err

    candidates = []
    for sym in universe:
        q = quotes.get(sym) or {}
        dc, last = q.get("day_change_pct"), q.get("last")
        if dc is None or last is None:
            continue
        dc = float(dc)
        reason = daychg_gate(dc)
        if reason:
            log(f"scan: {sym} {reason}, excluding as an outlier.")
            continue
        candidates.append({"symbol": sym, "day_change_pct": dc, "last": float(last),
                            "bull_or_bear": "bull" if dc >= 0 else "bear"})

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

        enrich_with_signals(candidates)
        passed = []
        for c in candidates:
            reason = entry_gate(c)
            if reason:
                log(f"scan: {c['symbol']} rejected: {reason}")
            else:
                passed.append(c)
        candidates = passed

    return candidates, None


def check_signals(symbols):
    """Read-only: run the day-change window and every entry gate (SMA, RSI,
    Fibonacci, forward P/E) on the given symbols, and log each gate's verdict.
    Places no orders and calls no pick provider."""
    quotes, err = get_quotes(symbols)
    if err:
        log(f"check: quotes failed: {err}")
        return
    candidates = []
    for sym in symbols:
        q = quotes.get(sym) or {}
        if q.get("last") is None:
            log(f"check: {sym}: no quote")
            continue
        candidates.append({"symbol": sym, "last": float(q["last"]),
                           "day_change_pct": float(q.get("day_change_pct") or 0.0)})
    if not candidates:
        return
    enrich_with_signals(candidates)
    for c in candidates:
        fib, fpe = c["fib"] or {}, c["fpe"] or {}
        log(f"check: {c['symbol']} last={c['last']:.2f} day={c['day_change_pct']:+.2f}% "
            f"sma50={c['sma50']} sma200={c['sma200']} rsi={c['rsi']} trend={c['trend']} "
            f"swing_high={c['swing_high']} swing_low={c['swing_low']} "
            f"fib={json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in fib.items()})} "
            f"fpe={json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in fpe.items()})}")
        failed = 0
        for name, gate in (("daychg", lambda c: daychg_gate(c["day_change_pct"])),) + ENTRY_GATES:
            reason = gate(c)
            failed += bool(reason)
            log(f"check: {c['symbol']} gate {name}: " + (f"FAIL -- {reason}" if reason else "pass"))
        log(f"check: {c['symbol']}: " + (f"REJECT -- {failed} gate(s) failed" if failed else "PASS"))


# ============================================================================
# Entry logic -- unlimited per SKILLS.md: attempted every tick, no daily cap.
# ============================================================================
def maybe_enter(snapshot):
    settled = snapshot["settled_cash"]
    if settled < CONFIG["min_trade_usd"]:
        log(f"entry: settled cash {settled:.2f} below min_trade_usd, skipping.")
        return

    held_symbols = {p["symbol"] for p in snapshot["positions"]}

    candidates, err = scan_candidates()
    if err:
        log(f"entry: quotes failed: {err}")
        return

    if not candidates:
        log("entry: no candidates clear the day-change window.")
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
           f"Stop-loss active at {CONFIG['stop_loss_pct']:g}% "
           f"(${stop_loss_usd(float(fill['avg_price'])):.2f}/share) below entry.")


# ============================================================================
# One tick -- fully stateless. Every call re-reads live broker state.
# ============================================================================
def tick(simulation=False):
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
            would_sell = approaching_close or drop >= stop_loss_usd(pos["average_buy_price"])
            log(f"[SIMULATION] {pos['symbol']}: drop ${drop:+.2f}/share, would_sell={would_sell}")
        if not approaching_close:
            settled = snapshot["settled_cash"]
            if settled >= CONFIG["min_trade_usd"]:
                candidates, qerr = scan_candidates()
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

    maybe_enter(snapshot)


# ============================================================================
# Provider comparison -- one scan, the same candidate list sent to every pick
# provider. Read-only: no account snapshot, no cash gate, never places an
# order. Useful for judging the pick step even with $0 settled cash.
# Since the universe is now a single shared list, comparison runs once per
# bull_or_bear side so you still get an independent recommendation for
# momentum longs and dip-buys, not just one pick across both.
# ============================================================================
def _compare_side(label, candidates, providers):
    if not candidates:
        log(f"compare[{label}]: no candidates clear the day-change window.")
        return

    log(f"compare[{label}]: {len(candidates)} candidates: "
        + ", ".join(f"{c['symbol']} {c['day_change_pct']:+.2f}%" for c in candidates))

    original = CONFIG["pick_provider"]
    picks = {}
    try:
        for provider in providers:
            CONFIG["pick_provider"] = provider
            pick, perr = pick_name(candidates)
            picks[provider] = pick
            log(f"compare[{label}]: {provider}: {perr or json.dumps(pick)}")
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
    log(f"compare[{label}]: {verdict} -- " + ", ".join(f"{p}={s}" for p, s in chosen.items()))


def compare_providers(providers=("claude", "openai")):
    if not in_session(now_tz()):
        log("compare: outside regular exchange hours; quotes may be stale.")

    candidates, err = scan_candidates()
    if err:
        log(f"compare: quotes failed: {err}")
        return
    if not candidates:
        log("compare: no candidates clear the day-change window.")
        return

    bulls = [c for c in candidates if c["bull_or_bear"] == "bull"]
    bears = [c for c in candidates if c["bull_or_bear"] == "bear"]
    _compare_side("bull", bulls, providers)
    _compare_side("bear", bears, providers)


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
                     help="scan once and ask both claude and openai for a bull-side and a "
                          "bear-side pick; read-only, ignores cash, places no orders")
    ap.add_argument("--providers", type=str, default="claude,openai",
                     help="comma-separated pick providers for --compare-providers "
                          "(claude, openai); default: claude,openai")
    ap.add_argument("--check-signals", type=str, default=None, metavar="SYMS",
                     help="comma-separated symbols: run only the day-change window and the "
                          "SMA/RSI/Fibonacci/forward-P/E entry gates on them (any symbol); read-only")
    args = ap.parse_args()

    if CONFIG["account_number"] == "YOUR_ROBINHOOD_ACCOUNT_NUMBER":
        sys.exit("Set CONFIG['account_number'] (or the ROBINHOOD_ACCOUNT_NUMBER "
                 "env var) to your real Robinhood account number first.")

    if args.check_signals:
        check_signals([s.strip().upper() for s in args.check_signals.split(",") if s.strip()])
        return

    if args.compare_providers:
        providers = tuple(dict.fromkeys(
            p.strip().lower() for p in args.providers.split(",") if p.strip()))
        unknown = [p for p in providers if p not in ("claude", "openai")]
        if not providers or unknown:
            sys.exit(f"--providers must list claude and/or openai, got '{args.providers}'.")
        compare_providers(providers)
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

    log(f"provider={CONFIG['pick_provider']} enable_live_buys={CONFIG['enable_live_buys']} "
        f"simulation={args.simulation} interval={interval} "
        f"session={CONFIG['session_open']}-{CONFIG['session_close']} "
        f"ignore_weekday={CONFIG['ignore_weekday']}")

    if args.once:
        tick(simulation=args.simulation)
        return

    log("Starting loop. Ctrl+C to stop.")
    while True:
        try:
            tick(simulation=args.simulation)
        except KeyboardInterrupt:
            log("Stopped.")
            break
        except Exception as exc:
            log(f"tick crashed (continuing): {exc}")
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
