#!/usr/bin/env bash
set -euo pipefail

NODE_VERSION="22.23.4"
EXPECTED_SHA256="1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce"
ARCHIVE_NAME="node-v${NODE_VERSION}-linux-x64.tar.xz"
DOWNLOAD_URL="https://nodejs.org/dist/v${NODE_VERSION}/${ARCHIVE_NAME}"

echo "=== BOOTSTRAPPING NODE ${NODE_VERSION} ==="
if command -v node >/dev/null 2>&1; then
    CURRENT_VERSION=$(node -v | sed 's/v//')
    if [ "$CURRENT_VERSION" = "$NODE_VERSION" ]; then
        echo "✓ Node.js ${NODE_VERSION} is already installed."
        exit 0
    fi
fi

echo "Downloading ${ARCHIVE_NAME}..."
curl -fsSL "$DOWNLOAD_URL" -o "$ARCHIVE_NAME"

echo "Verifying SHA256 checksum..."
ACTUAL_SHA256=$(sha256sum "$ARCHIVE_NAME" | cut -d' ' -f1)
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
    echo "❌ SHA256 mismatch!"
    echo "Expected: $EXPECTED_SHA256"
    echo "Actual:   $ACTUAL_SHA256"
    rm -f "$ARCHIVE_NAME"
    exit 1
fi
echo "✓ Checksum verified: ${ACTUAL_SHA256}"

echo "Extracting ${ARCHIVE_NAME}..."
tar -xJf "$ARCHIVE_NAME"
INSTALL_DIR="$(pwd)/node-v${NODE_VERSION}-linux-x64/bin"

if [ -n "${GITHUB_PATH:-}" ]; then
    echo "$INSTALL_DIR" >> "$GITHUB_PATH"
fi
export PATH="$INSTALL_DIR:$PATH"

echo "✓ Node $(node -v) and npm $(npm -v) successfully bootstrapped."
