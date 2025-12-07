#!/usr/bin/env bash

set -euo pipefail

cd /home/ubuntu/money-keeper

mkdir -p logs

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  echo "virtualenv .venv not found" >&2
  exit 1
fi

python run_agent.py >> logs/run_agent-cron.log 2>&1

