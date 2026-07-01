#!/bin/bash
# Launch paper trading bot as a detached daemon
cd /home/ubuntu/btc-agent-system
exec /home/ubuntu/.hermes/hermes-agent/venv/bin/python main.py
