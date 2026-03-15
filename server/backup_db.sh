#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="/home/pi/mk-market/server"
BACKUP_DIR="$BASE_DIR/backups"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)
cp "$BASE_DIR/app.db" "$BACKUP_DIR/app-$STAMP.db"
find "$BACKUP_DIR" -type f -name 'app-*.db' -mtime +14 -delete
