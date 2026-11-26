#!/usr/bin/env bash
# Render Build Script
set -e

echo "=== WEXORA Build Script for Render ==="

# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Build frontend (Node.js is available on Render)
cd frontend
npm install
npm run build
cd ..

# 3. Seed benchmark master data
python backend/seed.py

echo "=== Build Complete ==="
