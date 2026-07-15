"""
Async shim for youtube-search-python.

The upstream PyPI package dropped its ``youtubesearchpython.aio`` submodule,
and the original custom fork is no longer available. This module re-exposes
the same async ``VideosSearch`` / ``Playlist.get`` interface the bot expects,
backed by the synchronous ``youtubesearchpython`` classes (run off the event
loop via asyncio.to_thread so the bot never blocks).
"""
import asyncio

from youtubesearchpython import VideosSearch as _VideosSearch


class VideosSearch:
    def __init__(self, query, limit: int = 1, region=None):
        self._query = query
        self._limit = limit

    async def next(self):
        def _run():
            return _VideosSearch(self._query, self._limit).next()

        return await asyncio.to_thread(_run)


class Playlist:
    """Backed by yt-dlp at the call site (the upstream youtube-search-python
    package no longer ships a Playlist class). Raise here so the caller's
    existing yt-dlp fallback is used."""

    @classmethod
    async def get(cls, link: str):
        raise RuntimeError("Playlist class unavailable; use yt-dlp fallback")
