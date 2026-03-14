from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import yt_dlp

logger = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """Raised when media metadata extraction fails."""


@dataclass(slots=True)
class TrackInfo:
    title: str
    webpage_url: str
    stream_url: str
    duration: int | None
    uploader: str


_YTDLP_MAX_PARALLEL = max(1, int(os.getenv("YTDLP_MAX_PARALLEL", "4")))
_YTDLP_TIMEOUT_SECONDS = max(5, int(os.getenv("YTDLP_TIMEOUT_SECONDS", "25")))
_EXTRACT_CACHE_TTL_SECONDS = max(0, int(os.getenv("YTDLP_CACHE_TTL_SECONDS", "300")))
_EXTRACT_CACHE_MAX_SIZE = max(1, int(os.getenv("YTDLP_CACHE_MAX_SIZE", "128")))
_YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
_YTDLP_COOKIES_FROM_BROWSER = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
_YTDLP_USER_AGENT = os.getenv("YTDLP_USER_AGENT", "").strip()
_YTDLP_PLAYER_CLIENTS = os.getenv("YTDLP_PLAYER_CLIENTS", "android,web").strip()

_extract_semaphore = asyncio.Semaphore(_YTDLP_MAX_PARALLEL)
_cache_lock = threading.Lock()
_extract_cache: OrderedDict[str, tuple[float, TrackInfo]] = OrderedDict()

YTDLP_OPTIONS: Dict[str, Any] = {
    "noplaylist": True,
    "playlistend": 1,
    "skip_download": True,
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "cachedir": False,
    "default_search": "ytsearch1",
    "extractor_retries": 2,
    "retries": 2,
    "socket_timeout": 10,
    "concurrent_fragment_downloads": 4,
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS: Dict[str, str] = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 "
        "-reconnect_delay_max 10 -nostdin"
    ),
    "options": "-vn -loglevel warning -bufsize 128k -thread_queue_size 1024",
}


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "unknown"

    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _parse_comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_yt_dlp_options() -> Dict[str, Any]:
    options: Dict[str, Any] = dict(YTDLP_OPTIONS)

    clients = _parse_comma_list(_YTDLP_PLAYER_CLIENTS)
    if clients:
        options["extractor_args"] = {"youtube": {"player_client": clients}}

    if _YTDLP_USER_AGENT:
        options["http_headers"] = {"User-Agent": _YTDLP_USER_AGENT}

    if _YTDLP_COOKIES_FILE:
        cookie_path = Path(_YTDLP_COOKIES_FILE)
        if not cookie_path.exists():
            raise ExtractionError(f"Configured YTDLP_COOKIES_FILE does not exist: {_YTDLP_COOKIES_FILE}")
        options["cookiefile"] = str(cookie_path)

    # Useful for local development only. In most containers there is no browser profile.
    if _YTDLP_COOKIES_FROM_BROWSER:
        options["cookiesfrombrowser"] = (_YTDLP_COOKIES_FROM_BROWSER,)

    return options


def _candidate_yt_dlp_options() -> list[Dict[str, Any]]:
    base = _build_yt_dlp_options()

    # First attempt: configured client profile.
    candidates: list[Dict[str, Any]] = [base]

    # Fallback 1: remove explicit client pinning and let yt-dlp choose extractor client.
    broad_fallback = dict(base)
    broad_fallback.pop("extractor_args", None)
    candidates.append(broad_fallback)

    # Fallback 2: keep no client pinning and slightly reduce extractor constraints.
    no_selector_fallback = dict(broad_fallback)
    no_selector_fallback["extractor_retries"] = 1
    no_selector_fallback["retries"] = 1
    candidates.append(no_selector_fallback)

    return candidates


def _pick_stream_url_from_formats(info: Dict[str, Any]) -> str | None:
    requested_downloads = info.get("requested_downloads") or []
    if isinstance(requested_downloads, list):
        for item in requested_downloads:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])

    requested_formats = info.get("requested_formats") or []
    if isinstance(requested_formats, list):
        for item in requested_formats:
            if isinstance(item, dict) and item.get("url") and item.get("acodec") not in (None, "none"):
                return str(item["url"])

    direct_url = info.get("url")
    if direct_url:
        return str(direct_url)

    formats = info.get("formats") or []
    if not isinstance(formats, list):
        return None

    def _to_float(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip().lower()
            if not text or text in {"none", "nan", "inf", "-inf", "audio only"}:
                return 0.0
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    audio_candidates = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        url = fmt.get("url")
        acodec = fmt.get("acodec")
        if not url:
            continue
        if acodec in (None, "none"):
            continue
        score = (
            _to_float(fmt.get("abr")),
            _to_float(fmt.get("asr")),
            _to_float(fmt.get("tbr")),
        )
        audio_candidates.append((score, str(url)))

    if not audio_candidates:
        return None

    audio_candidates.sort(reverse=True)
    return audio_candidates[0][1]


def _cache_get(query: str) -> TrackInfo | None:
    if _EXTRACT_CACHE_TTL_SECONDS <= 0:
        return None

    now = time.time()
    with _cache_lock:
        cached = _extract_cache.get(query)
        if cached is None:
            return None

        inserted_at, track = cached
        if now - inserted_at > _EXTRACT_CACHE_TTL_SECONDS:
            _extract_cache.pop(query, None)
            return None

        _extract_cache.move_to_end(query)
        return track


def _cache_set(query: str, track: TrackInfo) -> None:
    if _EXTRACT_CACHE_TTL_SECONDS <= 0:
        return

    with _cache_lock:
        _extract_cache[query] = (time.time(), track)
        _extract_cache.move_to_end(query)

        while len(_extract_cache) > _EXTRACT_CACHE_MAX_SIZE:
            _extract_cache.popitem(last=False)


def _extract_info_sync(query: str) -> TrackInfo:
    search_query = query if is_url(query) else f"ytsearch1:{query}"
    info: Dict[str, Any] | None = None
    last_download_error: Exception | None = None

    candidates = _candidate_yt_dlp_options()
    for attempt, ytdlp_options in enumerate(candidates, start=1):
        try:
            with yt_dlp.YoutubeDL(ytdlp_options) as ydl:
                info = ydl.extract_info(search_query, download=False)
            break
        except yt_dlp.utils.DownloadError as exc:
            last_download_error = exc
            message = str(exc)

            if "Sign in to confirm you're not a bot" in message:
                raise ExtractionError(
                    "YouTube requires authentication for this request. Set YTDLP_COOKIES_FILE to a valid cookies.txt "
                    "(and mount it into Docker), then retry."
                ) from exc

            if "Requested format is not available" in message and attempt < len(candidates):
                logger.warning(
                    "Extractor returned no usable default format for '%s'; retrying profile %s/%s",
                    query,
                    attempt + 1,
                    len(candidates),
                )
                continue

            raise ExtractionError(f"yt-dlp failed for query: {query}") from exc
        except Exception as exc:
            logger.exception("yt-dlp unexpected exception for query '%s'", query)
            raise ExtractionError(f"unexpected extraction error for query: {query} ({type(exc).__name__}: {exc})") from exc

    if info is None and last_download_error is not None:
        raise ExtractionError(
            "No playable stream format was available for this video. Try another video or update YTDLP_PLAYER_CLIENTS."
        ) from last_download_error

    if info is None:
        raise ExtractionError("No media information returned by yt-dlp.")

    if "entries" in info:
        entries = info.get("entries") or []
        if not entries:
            raise ExtractionError("No search results found.")
        info = entries[0]

    if info.get("is_live"):
        logger.info("Live stream detected: %s", info.get("title", "unknown"))

    stream_url = info.get("url")
    webpage_url = info.get("webpage_url")
    title = info.get("title")

    stream_url = _pick_stream_url_from_formats(info)

    if not stream_url or not webpage_url or not title:
        raise ExtractionError("Unable to parse required stream metadata.")

    return TrackInfo(
        title=title,
        webpage_url=webpage_url,
        stream_url=stream_url,
        duration=info.get("duration"),
        uploader=info.get("uploader", "unknown"),
    )


async def extract_track(query: str) -> TrackInfo:
    cached = _cache_get(query)
    if cached is not None:
        logger.debug("yt-dlp cache hit for query: %s", query)
        return cached

    start = time.perf_counter()
    async with _extract_semaphore:
        try:
            track = await asyncio.wait_for(
                asyncio.to_thread(_extract_info_sync, query),
                timeout=_YTDLP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ExtractionError("Timed out while extracting media info.") from exc

    _cache_set(query, track)
    logger.debug("yt-dlp extraction completed in %.2fs for query: %s", time.perf_counter() - start, query)
    return track
