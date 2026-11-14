#!/bin/bash
# Run once from inside the unzipped rescuers folder:  bash setup_repo.sh
set -e
# copy your downloaded map data into data/ (skipped if not found)
cp ~/Downloads/amherst_* data/ 2>/dev/null || true
git init -q
git add .
git commit -q -m "Project setup: README, environment, data scripts, demo case"
if command -v gh >/dev/null 2>&1; then
  gh repo create rescuers --public --source=. --push
  echo "Done. Repo created and pushed."
else
  echo "GitHub CLI not installed. Run:"
  echo "  brew install gh && gh auth login"
  echo "  gh repo create rescuers --public --source=. --push"
fi
