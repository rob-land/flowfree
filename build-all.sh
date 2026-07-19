#!/usr/bin/env bash
# build-all.sh — build Flow flatpak bundles for x86_64 and aarch64.
#
# Usage:
#   ./build-all.sh                  # build both arches, write bundles
#   ./build-all.sh --arch x86_64    # build only one arch
#   ./build-all.sh --install        # also install host-arch bundle (--user)
#
# Outputs:
#   flow-x86_64.flatpak
#   flow-aarch64.flatpak

set -euo pipefail

cd "$(dirname "$0")"

ARCHES=(x86_64 aarch64)
INSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --arch)    ARCHES=("$2"); shift 2 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── qemu-binfmt sanity check for cross-arch builds ────────────────────────
HOST_ARCH=$(uname -m)
for a in "${ARCHES[@]}"; do
    if [[ "$a" != "$HOST_ARCH" && ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
        echo
        echo "Warning: cross-arch build requested but qemu binfmt is not registered."
        echo "         Register it with:  sudo systemctl restart systemd-binfmt"
        echo
    fi
done

mkdir -p repo

# ── Build + bundle each arch ──────────────────────────────────────────────
for arch in "${ARCHES[@]}"; do
    builddir="_flatpak_${arch}"
    bundle="flow-${arch}.flatpak"
    echo
    echo "==== Building Flow for ${arch} ===="
    flatpak-builder --arch="$arch" --repo=repo --force-clean \
        "$builddir" build-aux/flatpak/land.rob.flow.json
    echo "==== Bundling ${bundle} ===="
    flatpak build-bundle --arch="$arch" repo "$bundle" land.rob.flow
    ls -lh "$bundle"
done

# ── Optional: install the host-arch bundle ────────────────────────────────
if $INSTALL; then
    bundle="flow-${HOST_ARCH}.flatpak"
    if [[ -f "$bundle" ]]; then
        echo
        echo "==== Installing $bundle ===="
        flatpak install --user --noninteractive --reinstall --bundle "$bundle"
    else
        echo "Note: no $bundle to install (host arch not in build set)."
    fi
fi

echo
echo "Done."
