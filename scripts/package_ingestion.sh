#!/usr/bin/env bash
set -euo pipefail

# Packaging script for ingestion Lambda
# Produces: agents/ingestion/ingestion.zip
# Zip layout:
#  - main.py              (root)
#  - prompt.txt (optional)
#  - ingestion.py         (module file)
#  - any vendored dependencies installed into the archive root

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd)"
PKG_DIR="$REPO_ROOT/agents/ingestion"
BUILD_DIR="$PKG_DIR/build"
ZIP_PATH="$PKG_DIR/ingestion.zip"

echo "Packaging ingestion lambda..."
rm -rf "$BUILD_DIR" "$ZIP_PATH"
mkdir -p "$BUILD_DIR"

# 1) Install dependencies into build/ if requirements.txt exists
if [ -f "$PKG_DIR/requirements.txt" ]; then
  echo "Installing python dependencies into build/"
  pip install -r "$PKG_DIR/requirements.txt" -t "$BUILD_DIR"
fi

# 2) Copy everything from the outer ingestion folder into build/ so the zip root contains files directly
#    Exclude the build directory itself and any existing ingestion zip file
if command -v rsync >/dev/null 2>&1; then
  echo "Copying package files into build/ using rsync"
  rsync -a --exclude 'build' --exclude 'ingestion.zip' "$PKG_DIR/" "$BUILD_DIR/"
else
  echo "rsync not available; falling back to cp (will skip build and zip if present)"
  for f in "$PKG_DIR"/*; do
    name=$(basename "$f")
    if [ "$name" = "build" ] || [ "$name" = "ingestion.zip" ]; then
      continue
    fi
    cp -r "$f" "$BUILD_DIR/"
  done
fi

# 3) Create zip: contents of build/ become the archive root
echo "Creating zip: $ZIP_PATH"
( cd "$BUILD_DIR" && zip -r "$ZIP_PATH" . )

echo "Wrote $ZIP_PATH"

echo "Archive contents (top-level):"
unzip -l "$ZIP_PATH" | sed -n '1,200p'

# Print SHA256 base64 for terraform
if command -v openssl >/dev/null 2>&1; then
  echo "\nBase64 SHA256 (for Terraform source_code_hash):"
  openssl dgst -sha256 -binary "$ZIP_PATH" | base64
fi

# 4) Clean up build directory to avoid leaving temporary files
rm -rf "$BUILD_DIR"
echo "Cleaned up build directory: $BUILD_DIR"
