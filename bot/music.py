from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict

import discord
from discord.ext import commands

from .player import GuildMusicPlayer, Track
from .utils import ExtractionError, extract_track, format_duration

logger = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: Dict[int, GuildMusicPlayer] = {}

    def _get_or_create_player(self, guild_id: int) -> GuildMusicPlayer:
        player = self.players.get(guild_id)
        if player is None:
            loop = asyncio.get_running_loop()
            player = GuildMusicPlayer(guild_id, loop)
            self.players[guild_id] = player
        return player

    async def _connect_or_move_voice(
        self,
        user_channel: discord.VoiceChannel | discord.StageChannel,
        voice_client: discord.VoiceClient | None,
    ) -> discord.VoiceClient:
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                if voice_client is None:
                    return await user_channel.connect(timeout=20, reconnect=True)
                if not voice_client.is_connected():
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception:
                        logger.debug("Ignoring disconnect failure while reconnecting voice client", exc_info=True)
                    voice_client = await user_channel.connect(timeout=20, reconnect=True)
                    return voice_client
                if voice_client.channel != user_channel:
                    await voice_client.move_to(user_channel)
                return voice_client
            except (discord.ClientException, asyncio.TimeoutError, discord.DiscordException) as exc:
                last_error = exc
                logger.warning("Voice connect/move attempt %s failed: %s", attempt, exc)
                await asyncio.sleep(1.2)

        raise commands.CommandError(f"Failed to connect to voice channel: {last_error}")

    async def _ensure_voice(self, ctx: commands.Context, player: GuildMusicPlayer) -> discord.VoiceClient:
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError("You need to be in a voice channel first.")

        user_channel = ctx.author.voice.channel
        voice_client = ctx.voice_client

        voice_client = await self._connect_or_move_voice(user_channel, voice_client)

        player.set_voice_client(voice_client)
        return voice_client

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return

        player = self._get_or_create_player(ctx.guild.id)
        await self._ensure_voice(ctx, player)

        try:
            info = await extract_track(query)
        except ExtractionError as exc:
            logger.warning("Guild %s: extraction failed for query '%s': %s", ctx.guild.id, query, exc)
            await ctx.send(f"Could not find a playable result: {exc}")
            return
        except Exception:
            logger.exception("Guild %s: failed to extract media info.", ctx.guild.id)
            await ctx.send("Failed to retrieve audio information. Please try again.")
            return

        track = Track(
            title=info.title,
            webpage_url=info.webpage_url,
            stream_url=info.stream_url,
            duration=info.duration,
            uploader=info.uploader,
            requester_id=ctx.author.id,
            queued_at_unix=time.time(),
        )

        await player.enqueue(track)
        logger.info("Guild %s: queued '%s' by user %s", ctx.guild.id, track.title, ctx.author.id)
        await ctx.send(
            f"Queued: **{track.title}** ({format_duration(track.duration)}) | requested by <@{track.requester_id}>"
        )

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.get(ctx.guild.id)
        if not player or not await player.pause():
            await ctx.send("Nothing is currently playing.")
            return

        await ctx.send("Paused playback.")

    @commands.command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.get(ctx.guild.id)
        if not player or not await player.resume():
            await ctx.send("Nothing is currently paused.")
            return

        await ctx.send("Resumed playback.")

    @commands.command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.get(ctx.guild.id)
        if not player or not await player.skip():
            await ctx.send("Nothing to skip.")
            return

        await ctx.send("Skipped current track.")

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.get(ctx.guild.id)
        if not player:
            await ctx.send("Player is idle.")
            return

        await player.stop()
        await ctx.send("Stopped playback and cleared queue.")

    @commands.command(name="queue")
    async def queue(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.get(ctx.guild.id)
        if not player:
            await ctx.send("Queue is empty.")
            return

        upcoming = await player.queue.snapshot()
        if not player.current and not upcoming:
            await ctx.send("Queue is empty.")
            return

        lines = []
        if player.current:
            lines.append(
                f"Now playing: **{player.current.title}** ({format_duration(player.current.duration)})"
            )

        if upcoming:
            for idx, track in enumerate(upcoming[:10], start=1):
                lines.append(f"{idx}. {track.title} ({format_duration(track.duration)})")

            if len(upcoming) > 10:
                lines.append(f"...and {len(upcoming) - 10} more.")

        await ctx.send("\n".join(lines))

    @commands.command(name="leave")
    async def leave(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        player = self.players.pop(ctx.guild.id, None)
        if player:
            await player.cleanup()
        elif ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)

        await ctx.send("Disconnected from voice channel.")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if not self.bot.user or member.id != self.bot.user.id:
            return

        if member.guild is None:
            return

        if before.channel and not after.channel:
            logger.warning("Guild %s: bot disconnected from voice channel.", member.guild.id)

    async def cog_unload(self) -> None:
        for guild_id, player in list(self.players.items()):
            try:
                await player.cleanup()
            except Exception:
                logger.exception("Failed to cleanup player for guild %s", guild_id)
