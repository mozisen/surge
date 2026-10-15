#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _singbox_stats_libc _singbox_stats_platform _singbox_stats_versions _get_singbox_stats_latest _singbox_stats_has_version \
          _singbox_stats_version_gate _save_version_cache _force_get_cached_version; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
SINGBOX_STATS_REPO="mozisen/singbox-stats"
SINGBOX_STATS_TREE_URL="https://api.github.com/repos/mozisen/surge/git/trees/singbox-stats-binaries?recursive=1"
VERSION_CACHE_DIR="$fixture/cache"; mkdir -p "$VERSION_CACHE_DIR"
_init_version_cache() { :; }
_is_cache_fresh() { [[ "${cache_fresh:-false}" == true && -f "$1" ]]; }
_warn() { echo "$*"; }
_err() { echo "$*"; }
ldd() { echo "$libc_output"; return 1; }
getconf() { return 1; }
libc_output='musl libc'; [[ "$(_singbox_stats_libc)" == musl ]]
libc_output='ldd (Debian GLIBC 2.41)'; [[ "$(_singbox_stats_libc)" == glibc ]]
libc_output=unknown; if _singbox_stats_libc; then exit 1; fi

# Platform: amd64/arm64 with a known libc only.
_map_arch() { echo "$fixture_arch"; }
libc_output='ldd (Debian GLIBC 2.41)'
fixture_arch=amd64; [[ "$(_singbox_stats_platform)" == linux-amd64-glibc ]]
fixture_arch=unsupported; if _singbox_stats_platform; then exit 1; fi
fixture_arch=amd64

# Versions published for this machine, newest first by number (1.14.10 > 1.14.2), other platforms ignored.
curl() {
    [[ "${offline:-false}" != true ]] || return 22
    printf '%s' '{"tree":[{"path":"v1.14.0/linux-amd64-glibc/manifest.json"},{"path":"v1.14.2/linux-amd64-glibc/manifest.json"},
      {"path":"v1.14.10/linux-amd64-glibc/manifest.json"},{"path":"v1.14.10/linux-amd64-glibc/sing-box.tar.gz"},
      {"path":"v1.15.0/linux-arm64-musl/manifest.json"},{"path":"README.md"}]}'
}
[[ "$(_singbox_stats_versions | tr '\n' ' ')" == '1.14.10 1.14.2 1.14.0 ' ]]
[[ "$(_get_singbox_stats_latest true)" == 1.14.10 ]]
[[ "$(cat "$VERSION_CACHE_DIR/mozisen_singbox-stats")" == 1.14.10 ]]
_singbox_stats_has_version 1.14.2
if _singbox_stats_has_version 1.15.0; then exit 1; fi        # built for arm64 musl only
if _singbox_stats_has_version 1.14.3; then exit 1; fi        # official release without a statistics build
offline=true; [[ "$(_get_singbox_stats_latest false true)" == 1.14.10 ]]   # stale cache when offline
offline=false

# Repair gate: the running version must have a statistics build.
sing-box() { echo "sing-box version $fixture_version"; }
fixture_version=1.14.2; _singbox_stats_version_gate
for fixture_version in 1.13.16 1.14.3 1.15.0; do
    if _singbox_stats_version_gate >/dev/null; then exit 1; fi
done
fixture_version=1.14.3; _singbox_stats_version_gate | grep -q '最新统计版 v1.14.10'
fixture_version=1.14.2; offline=true
if _singbox_stats_version_gate >/dev/null; then exit 1; fi
echo 'PASS libc and platform detection, statistics builds per machine sorted numerically, cache fallback, repair gate by published builds'
