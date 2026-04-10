#!/usr/bin/env bash
set -euo pipefail

# Create a clean export of this repository with only runtime code,
# deployment/config files, tests, and key documentation.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

timestamp="$(date +%Y%m%d-%H%M%S)"
DEFAULT_OUT="${SRC_ROOT}-clean-${timestamp}"
OUT_DIR="$DEFAULT_OUT"
DRY_RUN=false

for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then
    DRY_RUN=true
  else
    OUT_DIR="$arg"
  fi
done

if ! command -v rsync >/dev/null 2>&1; then
  echo "Error: rsync is required but not found."
  exit 1
fi

if [ "$DRY_RUN" = "false" ] && [ -e "$OUT_DIR" ]; then
  echo "Error: output path already exists: $OUT_DIR"
  echo "Pass a different target path as the first argument."
  exit 1
fi

TMP_INCLUDE="$(mktemp)"
TMP_KEEP="$(mktemp)"
TMP_DROP="$(mktemp)"
TMP_ALL="$(mktemp)"
trap 'rm -f "$TMP_INCLUDE" "$TMP_KEEP" "$TMP_DROP" "$TMP_ALL"' EXIT

cat > "$TMP_INCLUDE" <<'EOF'
# Keep essential directories
/.github/***
/backend/***
/frontend/***
/tests/***
/scripts/***
/docs/***
/demo/***
/LiveTestData/***
/icons/***
/topology_icons/***
/data_fabric/***
/decision_memory/***
/anops/***
/integration/***
/k8s/***
/data/***

# Keep key root-level docs/specs
/README.md
/PRODUCT_SPEC.md
/PRODUCT_SPEC_INTERNAL.md
/PRODUCT_SPEC_EXTERNAL.md

# Keep root-level runtime/config files
/.env.example
/.env.cloud.example
/.gitignore
/pytest.ini
/requirements.txt
/requirements-cloud.txt
/package.json
/package-lock.json
/Dockerfile
/Dockerfile.ollama
/docker-compose.yml
/docker-compose.cloud.yml
/Caddyfile

# Keep startup and runner scripts
/startup.sh
/startup_local.sh
/startup_prod.sh
/run_demo.sh
/run_frontend.sh
/demo_startup.sh

# Keep license if present
/LICENSE

# Exclude everything else
*
EOF

echo "Building tracked-file retention report (full-depth)..."
if git -C "$SRC_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$SRC_ROOT" ls-files > "$TMP_ALL"

  while IFS= read -r relpath; do
    keep=false

    case "$relpath" in
      .github/*|backend/*|frontend/*|tests/*|scripts/*|docs/*|demo/*|LiveTestData/*|icons/*|topology_icons/*|data_fabric/*|decision_memory/*|anops/*|integration/*|k8s/*|data/*)
        keep=true
        ;;
      README.md|PRODUCT_SPEC.md|PRODUCT_SPEC_INTERNAL.md|PRODUCT_SPEC_EXTERNAL.md|.env.example|.env.cloud.example|.gitignore|pytest.ini|requirements.txt|requirements-cloud.txt|package.json|package-lock.json|Dockerfile|Dockerfile.ollama|docker-compose.yml|docker-compose.cloud.yml|Caddyfile|startup.sh|startup_local.sh|startup_prod.sh|run_demo.sh|run_frontend.sh|demo_startup.sh|LICENSE)
        keep=true
        ;;
    esac

    # Forced excludes from otherwise-kept trees
    case "$relpath" in
      docs/archive/*|frontend/node_modules/*|frontend/.next/*|frontend/out/*|frontend/tsconfig.tsbuildinfo)
        keep=false
        ;;
    esac

    if [ "$keep" = "true" ]; then
      printf "%s\n" "$relpath" >> "$TMP_KEEP"
    else
      printf "%s\n" "$relpath" >> "$TMP_DROP"
    fi
  done < "$TMP_ALL"

  total_count="$(wc -l < "$TMP_ALL" | tr -d ' ')"
  keep_count="$(wc -l < "$TMP_KEEP" | tr -d ' ')"
  drop_count="$(wc -l < "$TMP_DROP" | tr -d ' ')"

  echo "Tracked files total: $total_count"
  echo "Tracked files kept : $keep_count"
  echo "Tracked files dropped: $drop_count"

  PLAN_PATH="$SRC_ROOT/CLEAN_COPY_PLAN.txt"
  {
    echo "Clean copy plan generated: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    echo "Source: $SRC_ROOT"
    echo "Tracked files total: $total_count"
    echo "Tracked files kept: $keep_count"
    echo "Tracked files dropped: $drop_count"
    echo
    echo "=== KEPT (tracked) ==="
    sort "$TMP_KEEP"
    echo
    echo "=== DROPPED (tracked) ==="
    sort "$TMP_DROP"
  } > "$PLAN_PATH"

  echo "Plan report written: $PLAN_PATH"
else
  echo "Warning: Not a git repository. Skipping tracked-file audit report."
fi

if [ "$DRY_RUN" = "true" ]; then
  echo "Dry run requested. No copy created."
  exit 0
fi

echo "Creating clean copy at: $OUT_DIR"
mkdir -p "$OUT_DIR"

rsync -a --prune-empty-dirs \
  --include-from="$TMP_INCLUDE" \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.DS_Store' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.pyd' \
  --exclude='node_modules/' \
  --exclude='frontend/.next/' \
  --exclude='frontend/out/' \
  --exclude='frontend/tsconfig.tsbuildinfo' \
  "$SRC_ROOT/" "$OUT_DIR/"

echo "Pruning optional noisy subtrees from copied docs..."
rm -rf "$OUT_DIR/docs/archive" || true

echo "Writing export manifest..."
{
  echo "Clean copy generated: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  echo "Source: $SRC_ROOT"
  echo "Target: $OUT_DIR"
  echo
  echo "Top-level contents:"
  find "$OUT_DIR" -mindepth 1 -maxdepth 1 -print | sed "s#^$OUT_DIR/##" | sort
} > "$OUT_DIR/CLEAN_COPY_MANIFEST.txt"

echo "Done."
echo "Review: $OUT_DIR"
echo "Manifest: $OUT_DIR/CLEAN_COPY_MANIFEST.txt"
