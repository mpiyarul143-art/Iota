"""
Iota Bot — Free Real-Time Web Search Engine
Uses DuckDuckGo HTML scraping (no API key, unlimited, no rate limits).
"""
import aiohttp
import re
from html import unescape

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
}

_RESULT_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'class="result__snippet"[^>]*>(.*?)</a>',
    re.S
)
_TAG_RE = re.compile(r"<.*?>")


def _clean(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


async def web_search(query: str, max_results: int = 5) -> list:
    """
    Free web search via DuckDuckGo HTML endpoint.
    Returns list of dicts: [{"title", "url", "snippet"}, ...]
    """
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                DDG_HTML_URL,
                data={"q": query},
                headers=DDG_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    return []
                html = await r.text()
    except Exception:
        return []

    results = []
    for m in _RESULT_RE.finditer(html):
        url, title, snippet = m.groups()
        results.append({
            "title":   _clean(title),
            "url":     url,
            "snippet": _clean(snippet),
        })
        if len(results) >= max_results:
            break
    return results


async def search_summary(query: str, max_results: int = 4) -> str:
    """
    Returns a compact text block of search results, ready to inject
    into an AI context prompt for grounded, up-to-date answers.
    """
    results = await web_search(query, max_results)
    if not results:
        return ""
    lines = [f"🔍 Real-time info for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']} — {r['snippet'][:200]}")
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
    # Only skip pure greetings and very short messages
    if len(t.split()) < 2:
        return False
    skip = ["hi", "hello", "hii", "bye", "ok", "okay", "lol", "haha"]
    if t in skip:
        return False
    return True
