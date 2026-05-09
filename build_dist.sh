#!/usr/bin/env bash
# build_dist.sh — Build DevTrack distribution zip
set -euo pipefail

VERSION=$(python3 -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['version'])")
DIST_DIR="dist"
ZIP_NAME="DevTrack-${VERSION}-install.zip"

echo "Building DevTrack v${VERSION}..."

# Clean previous
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}/DevTrack"

# Copy source
cp -r devtrack/ "${DIST_DIR}/DevTrack/devtrack/"
cp pyproject.toml "${DIST_DIR}/DevTrack/"
cp README.md "${DIST_DIR}/DevTrack/" 2>/dev/null || true
cp Modelfile.qwen-dev "${DIST_DIR}/DevTrack/" 2>/dev/null || true

# Clean pyc artifacts
find "${DIST_DIR}/DevTrack" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${DIST_DIR}/DevTrack" -name "*.pyc" -delete 2>/dev/null || true

# Create zip
cd "${DIST_DIR}"
zip -r "${ZIP_NAME}" DevTrack/
cd ..

SIZE=$(du -sh "${DIST_DIR}/${ZIP_NAME}" | cut -f1)
echo "Done: ${DIST_DIR}/${ZIP_NAME} (${SIZE})"
