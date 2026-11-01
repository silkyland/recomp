#!/usr/bin/env bash
# init_project.sh — scaffold a new Nintendo Switch static-recompilation project.
#
#   init_project.sh --pkg <game.nsp|program.nca> --keys <prod.keys> --out <project-dir>
#                   [--base <recomp-base-repo>] [--name <short-name>] [--romfs src|image|tree|none]
#                   [--no-copy] [--no-extract]
#
# What it does:
#   1. sanity-checks the legal setup (package + keys OUTSIDE the project, read-only)
#   2. copies tools/ + runtime/ + Makefile + third_party/ from a base recomp repo
#      (EoWRecomp / LASRecomp, MIT) — never the game-derived dirs
#   3. creates tools/venv (capstone, unicorn, lz4, cryptography, pillow)
#   4. extracts the dump to <project>/extracted (untracked) and inventories it
#      into docs/GAP.md + docs/STATUS.md skeletons
#
# It does NOT: commit anything, copy game files into the repo, fetch dumps or keys,
# or adapt per-game files (runtime/modules.h, rt.h, title ID, renames) — that part is
# the agent's job; see the printed checklist and references/pipeline.md.
set -euo pipefail

PKG="" KEYS="" OUT="" BASE="${RECOMP_BASE:-}" NAME="" ROMFS=src
DO_COPY=1 DO_EXTRACT=1
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [ $# -gt 0 ]; do
    case "$1" in
        --pkg)    PKG="$2"; shift 2;;
        --keys)   KEYS="$2"; shift 2;;
        --out)    OUT="$2"; shift 2;;
        --base)   BASE="$2"; shift 2;;
        --name)   NAME="$2"; shift 2;;
        --romfs)  ROMFS="$2"; shift 2;;
        --no-copy)    DO_COPY=0; shift;;
        --no-extract) DO_EXTRACT=0; shift;;
        -h|--help) sed -n '2,16p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 2;;
    esac
done

die() { echo "init_project: $*" >&2; exit 1; }
[ -n "$PKG" ] && [ -n "$KEYS" ] && [ -n "$OUT" ] || die "need --pkg, --keys and --out (see --help)"
PKG="$(cd "$(dirname "$PKG")" && pwd)/$(basename "$PKG")"
KEYS="$(cd "$(dirname "$KEYS")" && pwd)/$(basename "$KEYS")"
[ -f "$PKG" ]  || die "package not found: $PKG"
[ -f "$KEYS" ] || die "keys not found: $KEYS"
case "$ROMFS" in src|image|tree|none) ;; *) die "--romfs must be src|image|tree|none";; esac

# --- legal guard: neither file may live inside the project tree ---
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
case "$PKG"  in "$OUT"/*) die "the game package must live OUTSIDE the project (read-only, never committed)";; esac
case "$KEYS" in "$OUT"/*) die "prod.keys must live OUTSIDE the project (read-only, never committed)";; esac
[ -z "$(find "$OUT" -mindepth 1 -not -name '.git*' -print -quit)" ] || [ "$DO_COPY" = 0 ] \
    || die "$OUT is not empty — use --no-copy or an empty dir"
chmod a-w "$PKG" "$KEYS" 2>/dev/null || true   # read-only intent; ignore FS that refuses

# --- package format gate ---
case "${PKG,,}" in
    *.nsz|*.xcz) die "compressed package: decompress first — nsz -D --keys <prod.keys> <file> (then re-run on the .nsp/.xci)";;
    *.xci)       die "XCI: extract the program NCA first (hactool <xci>, secure partition) or repack to NSP, then re-run";;
    *.nsp|*.nca) ;;
    *) echo "init_project: warning: unknown extension — expecting .nsp or .nca" >&2;;
esac

# --- find the base repo ---
looks_like_base() { [ -f "$1/tools/nso.py" ] && [ -f "$1/runtime/rt.h" ] && [ -f "$1/Makefile" ]; }
if [ "$DO_COPY" = 1 ]; then
    if [ -z "$BASE" ]; then
        for c in "$HOME"/Sites/*/ "$HOME"/Sites/Labs/*/ "$HOME"/*/ ../*; do
            looks_like_base "${c%/}" && { BASE="${c%/}"; break; }
        done
    fi
    [ -n "$BASE" ] && looks_like_base "$BASE" \
        || die "no base repo found — pass --base <repo> or set RECOMP_BASE (a dir with tools/nso.py + runtime/rt.h)"
    echo "init_project: base repo: $BASE"
fi

# --- 1. copy base (code only; never game-derived dirs) ---
if [ "$DO_COPY" = 1 ]; then
    for d in tools runtime third_party; do
        [ -d "$BASE/$d" ] || die "base is missing $d/"
        mkdir -p "$OUT/$d"
        (cd "$BASE/$d" && tar cf - --exclude='venv' --exclude='__pycache__' --exclude='.DS_Store' .) \
            | (cd "$OUT/$d" && tar xf -)
    done
    for f in Makefile LICENSE CONTRIBUTING.md; do
        [ -f "$BASE/$f" ] && cp "$BASE/$f" "$OUT/$f"
    done
    echo "init_project: copied tools/ runtime/ third_party/ Makefile from $BASE"
fi

mkdir -p "$OUT/docs" "$OUT/extracted"
# .gitignore from the skill template (dumps/keys/extracted/generated) — install BEFORE first commit
if [ -f "$SKILL_DIR/templates/gitignore" ] && [ ! -f "$OUT/.gitignore" ]; then
    sed "s|<PROJECT>|${NAME:-game}|g" "$SKILL_DIR/templates/gitignore" > "$OUT/.gitignore"
fi
[ -f "$SKILL_DIR/templates/STATUS.md" ] && [ ! -f "$OUT/docs/STATUS.md" ] \
    && cp "$SKILL_DIR/templates/STATUS.md" "$OUT/docs/STATUS.md" || true
[ -f "$SKILL_DIR/templates/CLAUDE.md" ] && [ ! -f "$OUT/CLAUDE.md" ] \
    && cp "$SKILL_DIR/templates/CLAUDE.md" "$OUT/CLAUDE.md" || true

# --- 2. venv ---
PY="$OUT/tools/venv/bin/python"
if [ ! -x "$PY" ]; then
    python3 -m venv "$OUT/tools/venv"
    "$OUT/tools/venv/bin/pip" install -q capstone unicorn lz4 cryptography pillow
fi
echo "init_project: venv ok ($PY)"

# --- 3. extract ---
if [ "$DO_EXTRACT" = 1 ]; then
    echo "== package info =="
    (cd "$OUT" && "$PY" -I tools/nca_extract.py "$KEYS" "$PKG" extracted --info) | tee /tmp/recomp_nca_info.$$
    case "$ROMFS" in
        src)   RFLAGS="--no-romfs --romfs-src";;
        image) RFLAGS="--no-romfs --romfs-image";;
        none)  RFLAGS="--no-romfs";;
        tree)  RFLAGS="";;
    esac
    echo "== extracting (romfs=$ROMFS) =="
    (cd "$OUT" && "$PY" -I tools/nca_extract.py "$KEYS" "$PKG" extracted $RFLAGS)
    ls "$OUT/extracted/exefs/"
fi

# --- 4. inventory ---
if [ "$DO_EXTRACT" = 1 ] && [ -d "$OUT/extracted/exefs" ]; then
    (cd "$OUT/tools" && "$PY" -I nso.py ../extracted/exefs/*) | tee "$OUT/docs/modules.txt"
    if [ -f "$OUT/tools/inventory.py" ]; then
        (cd "$OUT" && "$PY" -I tools/inventory.py extracted/exefs > docs/GAP.md) || true
        echo "init_project: wrote docs/GAP.md (rerun with --lift for the instruction census)"
    fi
fi

cat <<EOF

=== scaffolded: $OUT ===
Next (agent's checklist — see the recomp skill's references/pipeline.md):
  1. git init && git status --ignored   # dumps/keys/extracted/generated MUST be ignored
  2. Fill docs/STATUS.md: title ID, version, per-module build IDs (docs/modules.txt) — PIN ONE BUILD
  3. Adapt runtime/modules.h (bases/spans from measured image sizes) and runtime/rt.h (heap)
  4. Rename pass: binary, game lib, .ini, env-var prefix — deliberate, then grep for leftovers
  5. make gen   → gate: 0 "Unsupported" (implement missing encodings in lifter.py, test vs Unicorn)
  6. Build deps + make -j (see the base repo's docs/linux.md / BUILD-*.md)
  7. Boot → services → first frame → first correct image (verify with screenshots, not hope)
EOF
