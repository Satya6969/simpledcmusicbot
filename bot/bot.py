from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .music import Music

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("discord_music_bot")
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.voice_client").setLevel(logging.INFO)


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

PREFIX = os.getenv("COMMAND_PREFIX", "!")
bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready() -> None:
    if bot.user:
        logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Connected to %s guild(s)", len(bot.guilds))


@bot.event
async def on_resumed() -> None:
    logger.info("Discord gateway session resumed successfully.")


@bot.event
async def on_disconnect() -> None:
    logger.warning("Bot disconnected from Discord gateway.")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Command is on cooldown. Retry in {error.retry_after:.1f}s")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: {error.param.name}")
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("This command is not available in DMs.")
        return

    if isinstance(error, commands.CommandError):
        logger.warning("Command error in guild=%s command=%s error=%s", getattr(ctx.guild, "id", None), getattr(ctx.command, "name", None), error)
        await ctx.send(str(error))
        return

    logger.exception("Unhandled command error", exc_info=error)
    await ctx.send("An unexpected error occurred.")


@bot.event
async def on_error(event_method: str, *args: object, **kwargs: object) -> None:
    logger.exception("Unhandled event error in %s", event_method)


async def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Environment variable DISCORD_BOT_TOKEN is required.")

    await bot.add_cog(Music(bot))
    await bot.start(token, reconnect=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested by user.")
