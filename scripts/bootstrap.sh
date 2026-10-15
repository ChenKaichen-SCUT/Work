#!/usr/bin/env bash
# Optional server bootstrap. Run only on a machine dedicated to these experiments.
set -euo pipefail
ROOT="${WM_RESEARCH_ROOT:-$HOME/wm-research}"
mkdir -p "$ROOT/baselines" "$ROOT/logs"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev build-essential git curl ca-certificates \
  openjdk-17-jdk-headless maven opam pkg-config libgmp-dev unzip time
python3 -m venv "$ROOT/runtime"
"$ROOT/runtime/bin/pip" install -r "$ROOT/project/requirements.txt"
test -d "$ROOT/baselines/Dat3M" || git clone --depth 1 https://github.com/hernanponcedeleon/Dat3M.git "$ROOT/baselines/Dat3M"
test -d "$ROOT/baselines/herdtools7" || git clone --depth 1 https://github.com/herd/herdtools7.git "$ROOT/baselines/herdtools7"
git -C "$ROOT/baselines/Dat3M" rev-parse HEAD
git -C "$ROOT/baselines/herdtools7" rev-parse HEAD
