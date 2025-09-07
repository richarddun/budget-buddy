#!/usr/bin/env bash
set -euo pipefail

# Directory containing task files and README
TASK_DIR="tasks"
README="$TASK_DIR/README.md"

for TASK_FILE in "$TASK_DIR"/[0-9][0-9]-*.md; do
  echo "=== Processing $TASK_FILE ==="
  codex exec --profile scripted "You have been assigned a development task which will be reviewed asynchronously by the end of the week.  Do not offer any follow-ups or additional suggestions after completing the task, but if you absolutely must - see the task instructions for details on documenting the final outcome of your task (you can add suggestions or follow-up ideas there for later review).  **Task Instructions** : Review the task file '$TASK_FILE' and the tasks README at '$README'. Each assigned task has a 'Complete' checkbox, marked with [X] when complete.  You might be assigned a task that is already complete.  If so - simply respond to the assignment with 'Task is already complete', you will be credited for the review all the same. If the 'Complete' checkbox for this task is not marked with [X], complete the task as described to the best of your ability. After completion, update the 'Complete' checkbox for this task in the README to [X], commit the changes and add the new commit hash under 'Related Commit'. Add a brief description of what was done under the task entry in the README."
done
