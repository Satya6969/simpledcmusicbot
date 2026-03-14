from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import discord

from .song_queue import SongQueue
from .utils import FFMPEG_OPTIONS, ExtractionError, extract_track

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Track:
    title: str
    webpage_url: str
    stream_url: str
    duration: int | None
    uploader: str
    requester_id: int
    queued_at_unix: float


class GuildMusicPlayer:
    """Maintains queue and playback loop for one guild."""

    def __init__(self, guild_id: int, bot_loop: asyncio.AbstractEventLoop) -> None:
        self.guild_id = guild_id
        self.bot_loop = bot_loop
        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: SongQueue[Track] = SongQueue()
        self.current: Optional[Track] = None
        self.volume = 0.5

        self._player_task: Optional[asyncio.Task[None]] = None
        self._next_track_event: asyncio.Event = asyncio.Event()
        self._track_finished_ok: bool = True

    def set_voice_client(self, voice_client: discord.VoiceClient) -> None:
        self.voice_client = voice_client

    @property
    def is_playing(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_playing())

    @property
    def is_paused(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_paused())

    def ensure_player_task(self) -> None:
        if self._player_task and not self._player_task.done():
            return
        self._player_task = asyncio.create_task(self._player_loop(), name=f"guild-player-{self.guild_id}")

    async def enqueue(self, track: Track) -> None:
        await self.queue.put(track)
        self.ensure_player_task()

    async def pause(self) -> bool:
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    async def resume(self) -> bool:
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    async def skip(self) -> bool:
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
            return True
        return False

    async def stop(self) -> None:
        await self.queue.clear()
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        self.current = None

    async def cleanup(self) -> None:
        await self.stop()

        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)

        if self._player_task and not self._player_task.done():
            self._player_task.cancel()
            try:
                await self._player_task
            except asyncio.CancelledError:
                pass

        self.voice_client = None
        self._player_task = None

    async def _ensure_voice_connection(self) -> bool:
        if self.voice_client and self.voice_client.is_connected():
            return True

        for attempt in range(1, 4):
            if self.voice_client and self.voice_client.is_connected():
                return True
            logger.warning(
                "Guild %s: voice client disconnected while preparing playback, retry %s/3",
                self.guild_id,
                attempt,
            )
            await asyncio.sleep(1.5)

        return bool(self.voice_client and self.voice_client.is_connected())

    async def _refresh_stream_url_if_stale(self, track: Track) -> Track:
        # YouTube stream URLs can expire if a track waits in queue for too long.
        track_age_seconds = time.time() - track.queued_at_unix
        if track_age_seconds < 10 * 60:
            return track

        try:
            refreshed = await extract_track(track.webpage_url)
            logger.info("Guild %s: refreshed stream URL for stale queued track %s", self.guild_id, track.title)
            track.stream_url = refreshed.stream_url
            track.duration = refreshed.duration
            track.uploader = refreshed.uploader
            return track
        except ExtractionError:
            logger.warning(
                "Guild %s: failed to refresh stale stream URL for %s, using original URL",
                self.guild_id,
                track.title,
            )
            return track

    async def _player_loop(self) -> None:
        while True:
            try:
                track = await self.queue.get()
                self.current = track

                if not await self._ensure_voice_connection():
                    logger.warning("Guild %s: dropped track because no active voice connection.", self.guild_id)
                    self.current = None
                    continue

                track = await self._refresh_stream_url_if_stale(track)

                self._next_track_event = asyncio.Event()
                self._track_finished_ok = True
                audio_source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS),
                    volume=self.volume,
                )

                def after_playback(error: Exception | None) -> None:
                    if error:
                        self._track_finished_ok = False
                        logger.error("Guild %s: playback error for track '%s': %s", self.guild_id, track.title, error)
                    self.bot_loop.call_soon_threadsafe(self._next_track_event.set)

                self.voice_client.play(audio_source, after=after_playback)
                await self._next_track_event.wait()

                if self._track_finished_ok:
                    logger.debug("Guild %s: playback completed for '%s'", self.guild_id, track.title)

                self.current = None
            except asyncio.CancelledError:
                logger.info("Guild %s: player loop cancelled.", self.guild_id)
                break
            except Exception:
                logger.exception("Guild %s: unexpected error in player loop.", self.guild_id)
                self.current = None
                await asyncio.sleep(1)
