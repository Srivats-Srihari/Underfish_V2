#!/usr/bin/env bash
set -e
chmod +x ./stockfish || true
export STOCKFISH_PATH=${STOCKFISH_PATH:-./stockfish}
python main.py
