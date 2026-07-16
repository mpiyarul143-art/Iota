"""
Iota Bot — Free Real-Time Web Search Engine

Resilient, multi-source search that works even when DuckDuckGo blocks the
bot's IP (common on datacenter / hosting providers like Render). It tries
providers in order and falls back automatically:

  1. DuckDuckGo HTML  (POST, then GET — different DDG edge behaviour)
  2. DuckDuckGo Lite  (lighter HTML endpoint)
  3. DuckDuckGo Instant-Answer JSON (different infra, rarely rate-limited)
  4. Wikipedia        (factual fallback — extremely reliable, works from
                       datacenter IPs as long as we send a real User-Agent)

Every provider is wrapped so a single failure (timeout, block page, parse
error) is swallowed and the next source is tried. The AI only ever sees a
clean `search_summary()` string or "" — never a raw exception — so the
chat path stays at 0 errors.
"""
import asyncio
import itertools
import logging
import re
import time as _time
import urllib.parse
from html import unescape

import aiohttp

logger = logging.getLogger(__name__)

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
DDG_IA_URL   = "https://api.duckduckgo.com/"
WIKI_API_URL = "https://en.wikipedia.org/w/api.php"

# A small pool of realistic browser UAs. DDG blocks datacenter/empty UAs
# aggressively, so we rotate through these and send a real one each time.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]
_ua_cycle = itertools.cycle(_USER_AGENTS)


def _next_ua() -> str:
    return next(_ua_cycle)


_TAG_RE = re.compile(r"<.*?>")
_ANOMALY_RE = re.compile(r"unusual traffic|anomaly|are you a robot|bot check",
                         re.I)

# ── DuckDuckGo HTML result parser ────────────────────────────────────────
_RESULT_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'class="result__snippet"[^>]*>(.*?)</a>',
    re.S,
)
# ── DuckDuckGo Lite result parser ────────────────────────────────────────
_LITE_RE = re.compile(
    r'class="result-link"[^>]*><a href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?class="result-snippet"[^>]*>(.*?)</td>',
    re.S,
)


def _clean(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


def _real_url(raw: str) -> str:
    """
    DuckDuckGo wraps result links in a redirector:
        //duckduckgo.com/l/?uddg=ENCODED_URL&...
    Extract the real destination so the AI (and any logging) sees a clean
    link instead of a DDG bounce URL.
    """
    if not raw:
        return raw
    m = re.search(r"uddg=([^&]+)", raw)
    if m:
        try:
            return urllib.parse.unquote(m.group(1))
        except Exception:
            return raw
    if raw.startswith("//"):
        return "https:" + raw
    return raw


async def _fetch(session: aiohttp.ClientSession, method: str, url: str,
                **kw) -> str:
    """GET/POST helper with a real UA and a sane timeout."""
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", _next_ua())
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        if method == "POST":
            async with session.post(url, headers=headers, timeout=timeout,
                                    **kw) as r:
                if r.status != 200:
                    return ""
                return await r.text()
        else:
            async with session.get(url, headers=headers, timeout=timeout,
                                   **kw) as r:
                if r.status != 200:
                    return ""
                return await r.text()
    except Exception:
        return ""


async def _ddg_html(query: str, max_results: int) -> list:
    """DuckDuckGo HTML endpoint. Tries POST first, then GET — some edge
    nodes reject one method but serve the other, so trying both makes the
    primary provider far more reliable."""
    html = ""
    async with aiohttp.ClientSession() as s:
        for method, kw in (
            ("POST", {"data": {"q": query, "kl": "us-en"}}),
            ("GET",  {"params": {"q": query, "kl": "us-en"}}),
        ):
            html = await _fetch(s, method, DDG_HTML_URL, **kw)
            if html and not _ANOMALY_RE.search(html):
                break
            html = ""
    if not html:
        return []
    out = []
    for m in _RESULT_RE.finditer(html):
        url, title, snippet = m.groups()
        out.append({
            "title":   _clean(title),
            "url":     _real_url(url),
            "snippet": _clean(snippet),
        })
        if len(out) >= max_results:
            break
    return out


async def _ddg_lite(query: str, max_results: int) -> list:
    """DuckDuckGo Lite endpoint. POST first, then GET."""
    html = ""
    async with aiohttp.ClientSession() as s:
        for method, kw in (
            ("POST", {"data": {"q": query, "kl": "us-en"},
                      "headers": {"Content-Type":
                                  "application/x-www-form-urlencoded",
                                  "Origin": "https://lite.duckduckgo.com"}}),
            ("GET",  {"params": {"q": query, "kl": "us-en"}}),
        ):
            html = await _fetch(s, method, DDG_LITE_URL, **kw)
            if html and not _ANOMALY_RE.search(html):
                break
            html = ""
    if not html:
        return []
    out = []
    for m in _LITE_RE.finditer(html):
        url, title, snippet = m.groups()
        out.append({
            "title":   _clean(title),
            "url":     _real_url(url),
            "snippet": _clean(snippet),
        })
        if len(out) >= max_results:
            break
    return out


async def _ddg_instant(query: str, max_results: int) -> list:
    """DuckDuckGo Instant-Answer JSON API. Served from different
    infrastructure than the HTML scraper and rarely rate-limited, so it's
    a great extra fallback. Returns curated abstracts + related topics —
    perfect grounding facts for the AI. Returns [] on any failure."""
    params = {"q": query, "format": "json", "no_html": "1",
              "no_redirect": "1", "skip_disambig": "1"}
    try:
        async with aiohttp.ClientSession() as s:
            txt = await _fetch(s, "GET", DDG_IA_URL, params=params)
        if not txt:
            return []
        data = _safe_json(txt)
    except Exception as e:
        logger.debug(f"ddg instant failed: {e}")
        return []
    if not data:
        return []
    out = []
    # 1. Primary abstract (best, most factual).
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        out.append({
            "title":   (data.get("Heading") or query).strip(),
            "url":     data.get("AbstractURL") or "",
            "snippet": _clean(abstract),
        })
    # 2. Direct answer (calculations, conversions, definitions).
    answer = (data.get("Answer") or "").strip()
    if answer:
        out.append({
            "title":   data.get("AnswerType") or "Answer",
            "url":     "",
            "snippet": _clean(answer),
        })
    # 3. Related topics (each has Text + FirstURL; some nest under "Topics").
    for topic in (data.get("RelatedTopics") or []):
        if len(out) >= max_results:
            break
        entries = (topic.get("Topics")
                   if isinstance(topic, dict) and "Topics" in topic
                   else [topic])
        for e in entries:
            if len(out) >= max_results:
                break
            if not isinstance(e, dict):
                continue
            text = (e.get("Text") or "").strip()
            if not text:
                continue
            out.append({
                "title":   text.split(" - ")[0][:80],
                "url":     e.get("FirstURL") or "",
                "snippet": _clean(text),
            })
    return out[:max_results]


async def _wikipedia(query: str, max_results: int) -> list:
    """Factual fallback. Wikipedia almost never blocks datacenter IPs as
    long as we identify the bot with a real User-Agent."""
    params = {
        "action": "query", "list": "search",
        "srsearch": query, "format": "json",
        "srlimit": max_results, "srprop": "snippet",
    }
    try:
        async with aiohttp.ClientSession() as s:
            txt = await _fetch(s, "GET", WIKI_API_URL, params=params,
                               headers={"User-Agent":
                                        "IotaBot/1.0 (https://t.me/Its_iotabot)"})
        if not txt:
            return []
        data = _safe_json(txt)
        hits = (data.get("query") or {}).get("search") or []
    except Exception as e:
        logger.debug(f"wikipedia search failed: {e}")
        return []
    out = []
    for h in hits:
        title = h.get("title", "")
        if not title:
            continue
        out.append({
            "title":   title,
            "url":     "https://en.wikipedia.org/wiki/" +
                      urllib.parse.quote(title.replace(" ", "_")),
            "snippet": _clean(h.get("snippet", "")),
        })
        if len(out) >= max_results:
            break
    return out


def _safe_json(txt: str):
    try:
        import json
        return json.loads(txt)
    except Exception:
        return {}


# ── Result caching (in-memory, short TTL) ─────────────────────────────────
# DuckDuckGo rate-limits datacenter IPs, so the SAME query can return results
# one moment and nothing the next. Caching makes repeated/identical queries
# return consistent, reliable answers and avoids re-hitting the flaky
# provider on every single message.
_CACHE: dict = {}
_CACHE_TTL = 900  # 15 minutes


def _cache_key(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())[:120]


def _cache_get(q: str):
    k = _cache_key(q)
    hit = _CACHE.get(k)
    if hit and (_time.time() - hit[1]) < _CACHE_TTL:
        return hit[0]
    _CACHE.pop(k, None)
    return None


def _cache_set(q: str, results: list):
    _CACHE[_cache_key(q)] = (results, _time.time())


def _is_wikipedia(url: str) -> bool:
    return bool(url) and "wikipedia.org" in url


# Romanized-Hindi function words that carry no searchable meaning for an
# English encyclopedia. Stripping them lets the Wikipedia fallback find the
# real entity in mixed queries like "Elon Musk ki networth kitni hain".
_ROMANIZED_HI = {
    "ki", "ka", "ke", "ko", "kya", "kyu", "kyun", "kon", "kaun", "kaise",
    "kahan", "kab", "kitna", "kitni", "kitne", "hai", "hain", "ho", "hoon",
    "main", "mein", "me", "se", "aur", "par", "to", "tu", "tum", "aap",
    "apna", "uska", "unki", "mera", "teri", "kuch", "bhi", "ab", "tak",
    "the", "thi", "tho", "ya", "yaar", "cutie", "de", "do", "is", "are",
    "was", "were", "kaisa", "aisa", "vaisa", "bahut", "thoda", "bohot",
}

# Quantity / attribute nouns that pollute a Wikipedia article search (e.g.
# "Elon Musk networth" matches "Zip2" badly, but "Elon Musk" matches the
# right article). Dropped only for the Wikipedia fallback search.
_WIKI_NOISE = {
    "networth", "net", "worth", "income", "price", "cost", "rate", "rates",
    "total", "current", "latest", "news", "update", "updates", "released",
    "release", "trailer", "today", "tonight", "tomorrow", "now", "live",
    "real", "time", "kimat", "kitni", "kitna", "kitne", "hain", "hai",
}


def _clean_query_for_wiki(query: str) -> str:
    """Drop romanized-Hindi / quantity filler so Wikipedia search sees the
    actual entity (e.g. 'Elon Musk ki networth kitni hain' -> 'Elon Musk').
    Falls back to the original query if nothing usable remains."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9.'-]*", query)
    kept = [t for t in toks
            if t.lower() not in _ROMANIZED_HI
            and t.lower() not in _WIKI_NOISE and len(t) > 1]
    cleaned = " ".join(kept).strip()
    return cleaned or query.strip()


def _query_entities(query: str) -> set:
    """Significant Latin tokens of the original query, used to reject
    irrelevant Wikipedia hits (so we never prepend a wrong article)."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9.'-]*", query)
    return {t.lower() for t in toks
            if t.lower() not in _ROMANIZED_HI
            and t.lower() not in _WIKI_NOISE and len(t) >= 4}


async def _wiki_extract(title: str, max_len: int = 420) -> str:
    """Fetch the lead extract of a Wikipedia article via the REST summary
    API. This is EXTREMELY reliable from datacenter IPs (it's what the
    Wikipedia apps use) and returns the actual factual prose — usually
    including the exact figure the user asked for (e.g. a net-worth number),
    not just a truncated teaser. Returns '' on any failure."""
    api = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + urllib.parse.quote(title.replace(" ", "_")))
    try:
        async with aiohttp.ClientSession() as s:
            txt = await _fetch(
                s, "GET", api,
                headers={"User-Agent": "IotaBot/1.0 (https://t.me/Its_iotabot)"}
            )
        if not txt:
            return ""
        data = _safe_json(txt)
        ex = (data.get("extract") or "").strip()
        return ex[:max_len] if ex else ""
    except Exception as e:
        logger.debug(f"_wiki_extract failed for {title!r}: {e}")
        return ""


async def _enrich_with_wikipedia(results: list, max_results: int) -> list:
    """Replace shallow search snippets of Wikipedia hits with their real
    lead extract, so the AI gets grounded facts instead of a clipped teaser.
    Non-Wikipedia results are kept as-is. Bounded: at most 3 extract fetches,
    run concurrently to cap latency."""
    wiki_idx = [i for i, r in enumerate(results) if _is_wikipedia(r.get("url", ""))]
    if not wiki_idx:
        return results
    titles = []
    for i in wiki_idx[:3]:
        u = results[i].get("url", "")
        m = re.search(r"/wiki/([^?#]+)", u)
        titles.append(urllib.parse.unquote(m.group(1)) if m else "")
    extracts = await asyncio.gather(*(_wiki_extract(t) for t in titles))
    for idx, ex in zip(wiki_idx[:3], extracts):
        if ex:
            results[idx]["snippet"] = ex
    return results


async def _wikipedia_full(query: str, max_results: int) -> list:
    """Reliable fall-back used when DuckDuckGo returns nothing: Wikipedia
    search + lead extracts. Keeps factual queries answerable even when DDG
    is blocking the datacenter IP. The query is cleaned of romanized-Hindi
    filler first so mixed queries ('Elon Musk ki networth kitni hain')
    resolve to the right article."""
    clean = _clean_query_for_wiki(query)
    try:
        hits = await _wikipedia(clean, max_results)
    except Exception:
        hits = []
    if not hits:
        return []
    titles = [h["title"] for h in hits[:max_results]]
    extracts = await asyncio.gather(*(_wiki_extract(t) for t in titles))
    out = []
    for h, ex in zip(hits[:max_results], extracts):
        if ex:
            out.append({"title": h["title"], "url": h["url"], "snippet": ex})
        if len(out) >= max_results:
            break
    return out


async def web_search(query: str, max_results: int = 5) -> list:
    """
    Free, RESILIENT web search. Returns list of dicts:
        [{"title", "url", "snippet"}, ...]
    Strategy (ordered, each step never raises):
      1. Cache hit -> return immediately (consistent + avoids rate limits).
      2. DuckDuckGo HTML (POST+GET) -> Lite (POST+GET) -> Instant-Answer
         JSON for broad web coverage across multiple endpoint shapes.
      3. Enrich any Wikipedia hits with their REAL lead extract so the AI
         sees grounded facts, not a clipped teaser.
      4. If DDG gave nothing, fall back to Wikipedia search + extracts
         (very reliable from datacenter IPs).
    Always returns a (possibly empty) list — never raises — so callers stay
    at 0 errors.
    """
    if not query or not query.strip():
        return []
    query = query.strip()

    cached = _cache_get(query)
    if cached is not None:
        logger.debug(f"search('{query}') -> cache hit ({len(cached)} results)")
        return cached

    # 1. DuckDuckGo across multiple endpoint shapes. DDG rate-limits
    #    datacenter IPs inconsistently, so whichever shape isn't blocked
    #    right now will answer.
    results = []
    for provider in (_ddg_html, _ddg_lite, _ddg_instant):
        try:
            results = await provider(query, max_results)
        except Exception as e:
            logger.debug(f"search provider {provider.__name__} failed: {e}")
            results = []
        if results:
            break

    # 2. Enrich Wikipedia hits with real article extracts (failure-safe:
    #    if enrichment ever errors, the original DDG results are kept so a
    #    transient Wikipedia hiccup can never blank out the whole search).
    if results:
        try:
            results = await _enrich_with_wikipedia(results, max_results)
        except Exception as e:
            logger.debug(f"wiki enrich failed (keeping DDG results): {e}")
        # If DDG returned only non-Wikipedia results, still fetch the
        # canonical Wikipedia extract for the cleaned entity and PREPEND it,
        # so the AI always has a grounded factual anchor.
        if not any(_is_wikipedia(r.get("url", "")) for r in results):
            try:
                wiki = await _wikipedia_full(query, max_results)
                # Relevance guard: only prepend Wikipedia hits whose title
                # actually contains an entity from the user's query. This
                # stops a bad Wikipedia search from injecting a WRONG fact.
                ents = _query_entities(query)
                if wiki and ents:
                    wiki = [w for w in wiki
                            if ents & {t.lower()
                                       for t in re.findall(r"[A-Za-z]+",
                                                           w["title"])}]
                if wiki:
                    results = wiki + results
            except Exception as e:
                logger.debug(f"wiki prepend failed: {e}")
        _cache_set(query, results)
        logger.debug(f"search('{query}') -> {len(results)} results (DDG+wiki)")
        return results

    # 3. Wikipedia-only fallback (reliable from datacenter IPs)
    try:
        wiki = await _wikipedia_full(query, max_results)
        if wiki:
            _cache_set(query, wiki)
            logger.debug(f"search('{query}') -> {len(wiki)} results (wikipedia)")
            return wiki
    except Exception as e:
        logger.debug(f"wikipedia fallback failed: {e}")

    logger.debug(f"search('{query}') -> no results from any provider")
    return []


async def search_summary(query: str, max_results: int = 4) -> str:
    """
    Returns a compact text block of search results, ready to inject
    into an AI context prompt for grounded, up-to-date answers.
    Returns "" when no provider could find anything (so the AI falls back
    to its own graceful reply).
    """
    results = await web_search(query, max_results)
    if not results:
        return ""
    lines = [f"🔍 Real-time info for '{query}':"]
    for i, r in enumerate(results, 1):
        snip = (r.get("snippet") or "")[:400]
        lines.append(f"{i}. {r.get('title', '')} — {snip}")
    return "\n".join(lines)


# Kept for backwards compatibility with any handlers that still import it
def needs_search(text: str) -> bool:
    """
    DEPRECATED — ai_chat.py now uses its own _should_attempt_search()
    with broader, trigger-free logic. This function is kept only so older
    imports (fun.py truth/dare) don't break.
    Returns True for almost everything non-trivial.
    """
    t = text.lower().strip()
    if len(t.split()) < 2:
        return False
    skip = ["hi", "hello", "hii", "bye", "ok", "okay", "lol", "haha"]
    if t in skip:
        return False
    return True
