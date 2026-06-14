#!/usr/bin/env bash
# build-deb.sh — Build a Debian package for llm-usage-indicator.
#
# Usage:
#   ./build-deb.sh [VERSION]
#
# If VERSION is omitted, the latest git tag is used (or 0.0.0 as fallback).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    VERSION=$(git -C "$SCRIPT_DIR" describe --tags --abbrev=0 2>/dev/null \
        | sed 's/^v//' || echo "0.0.0")
fi

# Debian version: convert pre-release separator (e.g. 1.2.3-dev.abc → 1.2.3~dev.abc)
DEB_VERSION=$(echo "$VERSION" | sed 's/-dev\./~dev./g')

ARTIFACT="llm-usage-indicator_${DEB_VERSION}_all"
PKG_DIR="${SCRIPT_DIR}/dist/deb/${ARTIFACT}"
OUT="${SCRIPT_DIR}/dist/${ARTIFACT}.deb"

echo "[build-deb] version=${VERSION}  deb_version=${DEB_VERSION}"

# ── Assemble package tree ─────────────────────────────────────────────────────
rm -rf "${PKG_DIR}"
mkdir -p "${PKG_DIR}/DEBIAN"
mkdir -p "${PKG_DIR}/usr/share/llm-usage-indicator"

cp -r \
    "${SCRIPT_DIR}/daemon" \
    "${SCRIPT_DIR}/gui" \
    "${SCRIPT_DIR}/systemd" \
    "${SCRIPT_DIR}/waybar" \
    "${SCRIPT_DIR}/config.example.toml" \
    "${SCRIPT_DIR}/requirements.txt" \
    "${SCRIPT_DIR}/install.sh" \
    "${PKG_DIR}/usr/share/llm-usage-indicator/"

# Clean Python cache
find "${PKG_DIR}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "${PKG_DIR}" -name "*.pyc" -delete 2>/dev/null || true

chmod +x "${PKG_DIR}/usr/share/llm-usage-indicator/install.sh"
chmod +x "${PKG_DIR}/usr/share/llm-usage-indicator/waybar/module.sh"

# ── DEBIAN/control ────────────────────────────────────────────────────────────
INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)

sed \
    -e "s/^Version: .*/Version: ${DEB_VERSION}/" \
    "${SCRIPT_DIR}/debian/control" > "${PKG_DIR}/DEBIAN/control"
echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKG_DIR}/DEBIAN/control"

# ── DEBIAN/postinst + prerm ───────────────────────────────────────────────────
cp "${SCRIPT_DIR}/debian/postinst" "${PKG_DIR}/DEBIAN/postinst"
cp "${SCRIPT_DIR}/debian/prerm"    "${PKG_DIR}/DEBIAN/prerm"
chmod 755 "${PKG_DIR}/DEBIAN/postinst" "${PKG_DIR}/DEBIAN/prerm"

# ── Build ─────────────────────────────────────────────────────────────────────
mkdir -p "${SCRIPT_DIR}/dist"
dpkg-deb --build "${PKG_DIR}" "${OUT}"
echo "[build-deb] Built: ${OUT} ($(du -sh "${OUT}" | cut -f1))"
