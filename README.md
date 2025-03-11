# Discord Music Bot

A simple Discord bot that plays music from YouTube URLs or song names, with queue support, pause/resume, and skip features.

## Features
- Play music from YouTube URLs or by searching song names (e.g., `!play never gonna give you up`).
- Queue songs and play them sequentially.
- Commands: `!play`, `!pause`, `!resume`, `!skip`, `!queue`, `!stop`, `!leave`.

## Prerequisites
- **Discord Bot Token**: Create a bot on the Discord Developer Portal and get its token.
- **YouTube Cookies**: Export cookies from your browser to a `cookies.txt` file for YouTube authentication in Netscape format using cookie editor extention.
- **FFmpeg**: Required for audio playback (included in Docker, installed manually if running with Python).

## Configure
- Clone repo to your system.
- Copy .env.example to .env.
- Paste your discord bot token in .env
- Place cookies.txt in the project directory.

## Setup and Running

### Option 1: Using Docker Run
1. **Build the Docker Image**:
   ```bash
   docker build -t simpledcmusicbot .
2. **Run the Container**:
   ```bash
   docker run --env-file .env simpledcmuicbot
### Option 2: Using Docker Compose
1. **Build and Run**:
   ```bash
   docker-compose up -d --build
2. **Stop The Bot**:
   ```bash
   docker compose down
### Option 3: Running Directly with Python
1. **Install Dependencies**:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-pip ffmpeg
2. **Install Python packages**:
   ```bash
   pip3 install -r requirements.txt
3. **Run the Bot**:
   ```bash
   python3 music.py

## Info
I am not a programer(yet), this was just a learning project if you find anything wrong with the code please let me know.
