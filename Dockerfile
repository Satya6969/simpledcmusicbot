# Use an official Python runtime as the base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Update package lists and install system dependencies (FFmpeg)
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY requirements.txt .

# Install and Update pip and install Python dependencies, ensuring the latest versions
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --upgrade yt-dlp  # Ensure yt-dlp is always updated

# Copy the rest of your application code
COPY . .

# Command to run the bot
CMD ["python3", "music.py"]
