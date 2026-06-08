#!/bin/bash
# Auto-deploy poller — checks GitHub for new commits, pulls + restarts only if
# changes touch runtime code (Python, templates, static, ingest/parsers).
# Run via cron every minute.
REPO_DIR="$HOME/servers/budget-buddy"
LOG_FILE="/tmp/budget-buddy-autodeploy.log"

# Patterns that trigger a service restart — everything else is docs-only
RUNTIME_PATTERNS=(
    "*.py"
    "*.html"
    "*.js"
    "*.css"
    "requirements.txt"
)

cd "$REPO_DIR" || exit 1

BEFORE=$(git rev-parse HEAD 2>/dev/null)
git fetch origin main 2>/dev/null
AFTER=$(git rev-parse origin/main 2>/dev/null)

if [ "$BEFORE" = "$AFTER" ] || [ -z "$AFTER" ]; then
    # Log heartbeat once per hour
    [ "$(date +%M)" = "00" ] && echo "[$(date -Iseconds)] No changes (HEAD: ${BEFORE:0:8})" >> "$LOG_FILE"
    exit 0
fi

echo "[$(date -Iseconds)] New commits: ${BEFORE:0:8} → ${AFTER:0:8}" >> "$LOG_FILE"

# Check if any changed file matches runtime patterns
NEEDS_RESTART=false
CHANGED_FILES=$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null)

for file in $CHANGED_FILES; do
    for pattern in "${RUNTIME_PATTERNS[@]}"; do
        if [[ "$file" == $pattern ]]; then
            NEEDS_RESTART=true
            break 2
        fi
    done
done

git pull origin main 2>&1 >> "$LOG_FILE"
echo "[$(date -Iseconds)] Pull complete ($(echo "$CHANGED_FILES" | wc -l) files changed)" >> "$LOG_FILE"

if $NEEDS_RESTART; then
    echo "[$(date -Iseconds)] Runtime files changed, restarting service" >> "$LOG_FILE"
    pkill -9 -f "uvicorn main:app.*8000" 2>/dev/null
    sleep 2
    cd "$REPO_DIR"
    nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --root-path /budget-buddy > /tmp/budget-buddy.log 2>&1 &
    echo "[$(date -Iseconds)] Service restarted" >> "$LOG_FILE"
else
    echo "[$(date -Iseconds)] Docs-only changes, skipping restart" >> "$LOG_FILE"
fi
