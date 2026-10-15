#!/usr/bin/env bash
set -euo pipefail
ROOT="${WM_RESEARCH_ROOT:-$HOME/wm-research}"
case "${1:-}" in
  dartagnan)
    cd "$ROOT/baselines/Dat3M"
    export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
    export MAVEN_OPTS='-Xmx4g'
    mvn -B -s "$ROOT/project/scripts/maven-settings.xml" -pl dartagnan -am package -DskipTests
    ;;
  herd)
    export OPAMROOT="$ROOT/opam"
    export OPAMYES=1
    opam init --bare --disable-sandboxing -y
    opam switch create wm-herd ocaml-base-compiler.4.14.2 --jobs=4 -y
    eval "$(opam env --switch=wm-herd --set-switch)"
    cd "$ROOT/baselines/herdtools7"
    opam install . --deps-only --jobs=4 -y
    # Current checkout also has the nested aslref package. A target build keeps
    # that package visible; '-p herdtools7' would hide it and fail resolution.
    make Version.ml PREFIX="$ROOT/herd-install"
    dune build -j4 --profile release herd/herd.exe
    ;;
  *) echo 'usage: build_baselines.sh dartagnan|herd' >&2; exit 2;;
esac
