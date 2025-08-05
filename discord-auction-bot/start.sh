#!/bin/bash

# Start Discord bot in background
python bot.py &

# Start web server in foreground
uvicorn bot:app --host 0.0.0.0 --port $PORT
