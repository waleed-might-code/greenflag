#!/bin/bash
export PYTHONPATH=/root/projectexo/projects/greenflag/cyber-hunt-ai-main:$PYTHONPATH
source cyberAI/venv/bin/activate
python cyberAI/main.py "$@"
