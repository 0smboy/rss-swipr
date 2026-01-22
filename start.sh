#!/bin/bash
# Quick start script for RSS Swipr

cd "$(dirname "$0")"

echo "Starting RSS Swipr..."
echo ""
echo "Server will run on: http://127.0.0.1:5000"
echo "Press Ctrl+C to stop"
echo ""

# Activate virtual environment if it exists
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

$PYTHON app.py
