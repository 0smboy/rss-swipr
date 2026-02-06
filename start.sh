#!/bin/bash
# Quick start script for RSS Swipr

cd "$(dirname "$0")"

# Get port from environment variable or use default
PORT="${PORT:-5000}"

echo "Starting RSS Swipr..."
echo ""
echo "Server will run on: http://127.0.0.1:$PORT"
if [ "$PORT" != "5000" ]; then
    echo "Using custom port: $PORT"
fi
echo "Press Ctrl+C to stop"
echo ""

# Check if mise is available
if command -v mise &> /dev/null; then
    echo "Using mise + uv for dependency management"
    if [ "$PORT" != "5000" ]; then
        mise run dev-alt
    else
        mise run dev
    fi
# Check if uv is available
elif command -v uv &> /dev/null; then
    echo "Using uv for dependency management"
    uv run python app.py
# Fall back to traditional venv
elif [ -f ".venv/bin/python" ]; then
    echo "Using virtual environment"
    .venv/bin/python app.py
else
    echo "Using system Python"
    python3 app.py
fi
