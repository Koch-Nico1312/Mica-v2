#web_search.py
import json
import sys
import threading
import time
from pathlib import Path

from core.genai_response import response_text

# ── Gemini grounding quota circuit breaker ────────────────────────────────────
# The google_search grounding tool has its own small quota, separate from plain
# generation.  Once it is spent every call returns 429 — so retrying it at the
# top of every search only adds a dead round-trip before the DDG fallback runs.
# After a quota error, skip Gemini entirely for a cooldown period.
_QUOTA_COOLDOWN_SEC  = 900          # 15 minutes
_quota_blocked_until = 0.0
_quota_lock          = threading.Lock()


def _gemini_available() -> bool:
    with _quota_lock:
        return time.monotonic() >= _quota_blocked_until


def _note_gemini_error(exc: Exception) -> None:
    """Trip the breaker when the error is a quota / rate-limit rejection."""
    global _quota_blocked_until
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        with _quota_lock:
            already = time.monotonic() < _quota_blocked_until
            _quota_blocked_until = time.monotonic() + _QUOTA_COOLDOWN_SEC
        if not already:
            print(
                "[WebSearch] Gemini grounding quota exhausted — skipping it for "
                f"{_QUOTA_COOLDOWN_SEC // 60} min and serving results from DDG."
            )


class _QuotaCooldown(RuntimeError):
    """Raised instead of calling Gemini while the quota breaker is open."""


def _log_gemini_failure(context: str, exc: Exception) -> None:
    """Log a Gemini failure — silently when it is just the expected cooldown."""
    if isinstance(exc, _QuotaCooldown):
        return          # announced once when the breaker tripped; not a warning
    print(f"[WebSearch] \u26a0\ufe0f {context} failed ({exc}) — using DDG instead")


def _run_bounded(fn, timeout: float, label: str = "task"):
    """Run fn() in a daemon thread; return its result, or None if it overruns."""
    box = [None]

    def _run():
        try:
            box[0] = fn()
        except Exception as e:
            _log_gemini_failure(label, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print(f"[WebSearch] {label} exceeded {timeout:.0f}s — moving on")
    return box[0]

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    if not _gemini_available():
        raise _QuotaCooldown("Gemini grounding is in quota cooldown")

    from google import genai

    client = genai.Client(api_key=_get_api_key())
    try:
        chat = client.chats.create(
            model="gemini-flash-latest",
            config={"tools": [{"google_search": {}}]},
        )
        response = chat.send_message(query)
    except Exception as e:
        _note_gemini_error(e)
        raise

    text = response_text(response)
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _get_ddgs():
    """
    Returns the DDGS class.  The package was renamed duckduckgo-search -> ddgs;
    the legacy package's endpoints are now rejected by DuckDuckGo (news() gets a
    403 Ratelimit, text() silently returns zero results), so warn loudly if we
    end up on it instead of failing in silence.
    """
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        print(
            "[WebSearch] ⚠️ Using the deprecated 'duckduckgo-search' package — "
            "DuckDuckGo blocks its endpoints, so every search will come back "
            "empty.  Fix with:  pip install -U ddgs"
        )
        return DDGS


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("href",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG text() failed: {e}")
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
    # Also covers the legacy-package case, where news() returns an empty list
    # instead of raising.
    if not results:
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Price Comparison (Punkt 35) ───────────────────────────────────────────────

def compare_prices(items: list, aspect: str = "price") -> str:
    """
    Vergleiche Preise für mehrere Produkte.
    
    Args:
        items: Liste von Produkten zum Vergleichen
        aspect: Vergleichsaspekt (price, specs, reviews, features)
        
    Returns:
        Formatierter Vergleich
    """
    if not items or len(items) < 2:
        return "Benötige mindestens 2 Produkte zum Vergleichen"
    
    comparison_results = []
    
    for item in items:
        query = f"{item} {aspect} comparison price"
        try:
            results = _ddg_search(query, max_results=3)
            if results:
                item_info = {
                    "name": item,
                    "results": results
                }
                comparison_results.append(item_info)
        except Exception as e:
            print(f"[PriceCompare] Error for {item}: {e}")
    
    if not comparison_results:
        return "Keine Vergleichsergebnisse gefunden"
    
    # Formatierung für Gemini-zusammenfassung
    comparison_text = f"Price comparison for: {', '.join(items)}\n\n"
    for item_data in comparison_results:
        comparison_text += f"{item_data['name']}:\n"
        for result in item_data['results'][:2]:  # Top 2 Ergebnisse
            comparison_text += f"  - {result.get('title', 'N/A')}\n"
            comparison_text += f"    {result.get('snippet', 'N/A')[:100]}\n"
        comparison_text += "\n"
    
    # Versuche Gemini-Zusammenfassung
    try:
        from google import genai
        client = genai.Client(api_key=_get_api_key())
        chat = client.chats.create(
            model="gemini-flash-latest",
            config={"tools": [{"google_search": {}}]},
        )
        summary_prompt = (
            f"Compare these {aspect} for the products: {', '.join(items)}. "
            f"Focus on {aspect}. Provide a clear comparison with recommendations. "
            f"Here is the raw data:\n{comparison_text}"
        )
        response = chat.send_message(summary_prompt)
        return response_text(response)
    except Exception as e:
        print(f"[PriceCompare] Summary failed: {e}")
        return comparison_text


# ── Opening Hours (Punkt 36) ────────────────────────────────────────────────────

def find_opening_hours(location: str) -> str:
    """
    Suche Öffnungszeiten für ein Geschäft oder Ort.
    
    Args:
        location: Name des Geschäfts oder Orts
        
    Returns:
        Öffnungszeiten Information
    """
    query = f"{location} opening hours today"
    
    try:
        results = _ddg_search(query, max_results=5)
        if not results:
            return f"Keine Öffnungszeiten gefunden für: {location}"
        
        # Extrahiere Öffnungszeiten aus den Ergebnissen
        hours_info = f"Opening hours for {location}:\n\n"
        for i, result in enumerate(results, 1):
            hours_info += f"{i}. {result.get('title', 'N/A')}\n"
            snippet = result.get('snippet', '')
            if snippet:
                hours_info += f"   {snippet[:150]}\n"
            hours_info += f"   Source: {result.get('url', 'N/A')}\n\n"
        
        return hours_info
    except Exception as e:
        print(f"[OpeningHours] Error: {e}")
        return f"Fehler bei der Suche nach Öffnungszeiten für {location}"


# ── Route Search (Punkt 37) ────────────────────────────────────────────────────

def search_route(origin: str, destination: str, transport_mode: str = "car") -> str:
    """
    Suche Route zwischen zwei Orten.
    
    Args:
        origin: Startort
        destination: Zielort
        transport_mode: Verkehrsmittel (car, public_transport, walking, bike)
        
    Returns:
        Routeninformation
    """
    query = f"route from {origin} to {destination} by {transport_mode} distance time"
    
    try:
        results = _ddg_search(query, max_results=5)
        if not results:
            return f"Keine Route gefunden von {origin} nach {destination}"
        
        route_info = f"Route from {origin} to {destination} ({transport_mode}):\n\n"
        
        for i, result in enumerate(results, 1):
            route_info += f"{i}. {result.get('title', 'N/A')}\n"
            snippet = result.get('snippet', '')
            if snippet:
                route_info += f"   {snippet[:150]}\n"
            route_info += f"   Source: {result.get('url', 'N/A')}\n\n"
        
        # Versuche detailliertere Information durch Gemini
        try:
            from google import genai
            client = genai.Client(api_key=_get_api_key())
            chat = client.chats.create(
                model="gemini-flash-latest",
                config={"tools": [{"google_search": {}}]},
            )
            detail_prompt = (
                f"Get detailed route information from {origin} to {destination} "
                f"using {transport_mode}. Include distance, estimated time, "
                f"and alternative routes if available."
            )
            response = chat.send_message(detail_prompt)
            detailed_info = response_text(response)
            
            if detailed_info and len(detailed_info) > 50:
                route_info += f"\nDetailed information:\n{detailed_info}"
        except Exception as e:
            print(f"[RouteSearch] Detail search failed: {e}")
        
        return route_info
    except Exception as e:
        print(f"[RouteSearch] Error: {e}")
        return f"Fehler bei der Routensuche von {origin} nach {destination}"


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    chat = client.chats.create(
        model="gemini-flash-latest",
        config={"tools": [{"google_search": {}}]},
    )
    response = chat.send_message(
        f"Current world news: {n} headlines. Numbered list, titles only."
    )
    raw = response_text(response)

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini search", e)
        results = _ddg_search(query)
        return _format_ddg(query, results)


def _news(query: str) -> str:
    """
    DDG first, Gemini as backup.

    The old version raced both backends in parallel and kept the first answer.
    That burned one google_search grounding call on *every* news request —
    including the startup briefing — even when DDG had already won the race.
    Grounding has a small quota, so it ran dry after a handful of launches and
    then 429'd for everything else (research/compare), which are the modes that
    actually need a synthesised answer.

    DDG news returns in well under a second and gives raw headlines, which is
    exactly what the briefing wants, so it goes first and Gemini is only touched
    when DDG comes back empty.
    """
    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    def _ddg_attempt() -> str:
        return _format_news(ddg_query, _ddg_news(ddg_query, max_results=8))

    text = _run_bounded(_ddg_attempt, timeout=5.0, label="DDG news")
    if text and len(text) > 60 and not text.startswith("No news found"):
        return text

    text = _run_bounded(
        lambda: _gemini_search(gemini_query), timeout=6.0, label="Gemini news"
    )
    if text and len(text) > 60:
        return text

    return f"No news found for: {query}"


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        _log_gemini_failure("Gemini research", e)
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        _log_gemini_failure("Gemini price", e)
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini compare", e)

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"
    
    # Neue Parameter für erweiterte Funktionen
    origin = params.get("origin", "").strip()
    destination = params.get("destination", "").strip()
    transport_mode = params.get("transport_mode", "car").strip()

    if mode == "route" and (not origin or not destination):
        return "Route search requires both origin and destination parameters"
    if mode != "route" and not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] mode={mode!r} query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        if mode == "opening_hours":
            return find_opening_hours(query)
        if mode == "route":
            return search_route(origin, destination, transport_mode)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"
