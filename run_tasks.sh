#!/usr/bin/env bash
set -euo pipefail

# Directory containing task files and README
TASK_DIR="tasks"
README="$TASK_DIR/README.md"

for TASK_FILE in "$TASK_DIR"/[0-9][0-9]-*.md; do
  echo "=== Processing $TASK_FILE ==="
  codex --profile scripted "Review the task file '$TASK_FILE' and the tasks README at '$README'. If the 'Complete' checkbox for this task is not marked with [X], complete the task as described. After completion, update the 'Complete' checkbox for this task in the README to '[X]', commit the changes and add the new commit hash under 'Related Commit'. Add a very brief description of what was done under the task entry in the README."
done
