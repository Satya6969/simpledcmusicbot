import discord
from discord.ext import commands
import yt_dlp
import asyncio
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# YTDL options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'cookiefile': 'cookies.txt',  # Update this if needed
}

# Store voice clients and queues
voice_clients = {}
queues = {}

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

def play_next(ctx):
    """Plays the next song in the queue."""
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        title, url = queues[ctx.guild.id].pop(0)
        voice_client = voice_clients[ctx.guild.id]
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            url2 = info['url']
            voice_client.play(discord.FFmpegPCMAudio(url2, **FFMPEG_OPTIONS), after=lambda e: play_next(ctx))
        asyncio.run_coroutine_threadsafe(ctx.send(f"Now playing: {title}"), bot.loop)
    else:
        asyncio.run_coroutine_threadsafe(ctx.send("Queue is empty!"), bot.loop)
        if ctx.guild.id in voice_clients:
            asyncio.run_coroutine_threadsafe(voice_clients[ctx.guild.id].disconnect(), bot.loop)
            del voice_clients[ctx.guild.id]

@bot.command()
async def play(ctx, *, query: str):
    """Plays a song from a URL or searches by song name."""
    try:
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel to play music!")
            return

        channel = ctx.author.voice.channel
        if ctx.guild.id not in voice_clients:
            voice_client = await channel.connect()
            voice_clients[ctx.guild.id] = voice_client
        else:
            voice_client = voice_clients[ctx.guild.id]

        # Check if query is a URL or a search term
        if query.startswith("http://") or query.startswith("https://"):
            url = query
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title')
        else:
            # Search YouTube using yt-dlp
            search_options = {
                'format': 'bestaudio/best',
                'noplaylist': True,
                'quiet': True,
                'cookiefile': 'cookies.txt',
                'default_search': 'ytsearch',  # Use YouTube search
                'max_downloads': 1,  # Limit to 1 result
            }
            with yt_dlp.YoutubeDL(search_options) as ydl:
                info = ydl.extract_info(query, download=False)
                if 'entries' not in info or not info['entries']:
                    await ctx.send("No results found for that song!")
                    return
                url = info['entries'][0]['url']
                title = info['entries'][0]['title']

        # If nothing is playing, start immediately
        if not voice_client.is_playing():
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                url2 = info['url']
                voice_client.play(discord.FFmpegPCMAudio(url2, **FFMPEG_OPTIONS), after=lambda e: play_next(ctx))
                await ctx.send(f"Now playing: {title}")
        else:
            # Add to queue
            if ctx.guild.id not in queues:
                queues[ctx.guild.id] = []
            queues[ctx.guild.id].append((title, url))
            await ctx.send(f"Added to queue: {title}")

    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")
        if ctx.guild.id in voice_clients and not voice_clients[ctx.guild.id].is_playing():
            await voice_clients[ctx.guild.id].disconnect()
            del voice_clients[ctx.guild.id]

@bot.command()
async def pause(ctx):
    """Pauses the current song."""
    if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
        voice_clients[ctx.guild.id].pause()
        await ctx.send("Paused the music.")
    else:
        await ctx.send("Nothing is playing!")

@bot.command()
async def resume(ctx):
    """Resumes the paused song."""
    if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_paused():
        voice_clients[ctx.guild.id].resume()
        await ctx.send("Resumed the music.")
    else:
        await ctx.send("Nothing is paused!")

@bot.command()
async def skip(ctx):
    """Skips the current song."""
    if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
        voice_clients[ctx.guild.id].stop()
        await ctx.send("Skipped the current song.")
    else:
        await ctx.send("Nothing is playing to skip!")

@bot.command()
async def queue(ctx):
    """Displays the current queue."""
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        queue_list = "\n".join([f"{i+1}. {title}" for i, (title, _) in enumerate(queues[ctx.guild.id])])
        await ctx.send(f"Current queue:\n{queue_list}")
    else:
        await ctx.send("The queue is empty!")

@bot.command()
async def stop(ctx):
    """Stops the music and clears the queue."""
    if ctx.guild.id in voice_clients:
        voice_clients[ctx.guild.id].stop()
        if ctx.guild.id in queues:
            del queues[ctx.guild.id]
        await voice_clients[ctx.guild.id].disconnect()
        del voice_clients[ctx.guild.id]
        await ctx.send("Stopped and disconnected.")
    else:
        await ctx.send("I'm not playing anything!")

@bot.command()
async def leave(ctx):
    """Makes the bot leave the voice channel."""
    if ctx.guild.id in voice_clients:
        if ctx.guild.id in queues:
            del queues[ctx.guild.id]
        await voice_clients[ctx.guild.id].disconnect()
        del voice_clients[ctx.guild.id]
        await ctx.send("Left the voice channel.")
    else:
        await ctx.send("I'm not in a voice channel!")

# Run the bot
bot.run(TOKEN)
