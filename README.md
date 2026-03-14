# Discord Music Bot

Production-ready Discord music bot built with Python 3.11+, `discord.py`, `yt-dlp`, and FFmpeg.

## Features

- Automatic voice channel join on music commands
- Play from YouTube URL or search query
- Streams audio directly via FFmpeg when possible
- Per-guild independent queue and playback state
- Async architecture with blocking extraction offloaded to executor
- Commands:
  - `!play <url or search query>`
  - `!pause`
  - `!resume`
  - `!skip`
  - `!stop`
  - `!queue`
  - `!leave`
- Structured logging and command-level error handling

## Project Structure

```text
musicbot/
│
├── bot/
│   ├── bot.py
│   ├── music.py
│   ├── player.py
│   ├── song_queue.py
│   └── utils.py
│
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Python 3.11+
- FFmpeg installed (if running locally)
- Discord application and bot token

## Discord Bot Setup

1. Create a new app at the Discord Developer Portal.
2. Create a bot under the app.
3. Enable the **Message Content Intent** in the bot settings.
4. Copy the bot token.
5. Invite the bot to your server with voice and message permissions.

## Local Run

1. Copy environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set `DISCORD_BOT_TOKEN`.

3. Install dependencies:

   ```bash
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Start bot:

   ```bash
   python -m bot.bot
   ```

## Docker Run

1. Copy environment file and set your token:

   ```bash
   cp .env.example .env
   ```

2. Build and run:

   ```bash
   docker compose up --build -d
   ```

3. View logs:

   ```bash
   docker compose logs -f
   ```

4. Stop:

   ```bash
   docker compose down
   ```

## Notes

- Search queries are resolved with `yt-dlp` using `ytsearch1` (first result).
- Audio is streamed from extracted URLs rather than downloaded full files.
- Each guild has an isolated `GuildMusicPlayer` instance for queue independence.
- ffmpeg is configured with reconnect and queue buffering flags for better stream stability.
- yt-dlp extraction uses bounded parallel workers, timeout protection, and short-lived cache.

## Optional Performance Tuning

Environment variables:

- `YTDLP_MAX_PARALLEL`: max concurrent extractions (default: 4)
- `YTDLP_TIMEOUT_SECONDS`: extraction timeout per request (default: 25)
- `YTDLP_CACHE_TTL_SECONDS`: metadata cache duration in seconds (default: 300)
- `YTDLP_CACHE_MAX_SIZE`: max cached query entries (default: 128)
- `YTDLP_PLAYER_CLIENTS`: youtube client order for extraction (default: `android,web`)
- `YTDLP_USER_AGENT`: optional custom user agent for yt-dlp HTTP requests
- `YTDLP_COOKIES_FILE`: path to exported `cookies.txt` for authenticated YouTube requests
- `YTDLP_COOKIES_FROM_BROWSER`: browser profile for local cookie extraction (local only, not typical in Docker)

## Troubleshooting

- If you see voice connection errors, verify the bot has permission to connect and speak.
- If extraction fails, ensure outbound internet access and that YouTube is reachable.
- If audio does not play locally, verify FFmpeg is installed and on PATH.
- If you see `Sign in to confirm you're not a bot`, provide YouTube cookies:
   1. Export `cookies.txt` from a logged-in browser using a trusted extension.
   2. Place it at `./cookies/youtube.txt` in your project root.
   3. Set `YTDLP_COOKIES_FILE=/cookies/youtube.txt` in your `.env`.
   4. Recreate container: `docker compose down && docker compose up --build -d`.
- For local (non-Docker) runs, you can set either:
   - `YTDLP_COOKIES_FILE=C:/path/to/cookies.txt`
   - or `YTDLP_COOKIES_FROM_BROWSER=chrome` (if supported on your system)
