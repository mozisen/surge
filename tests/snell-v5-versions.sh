#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _get_snell_v5_versions_from_kb _get_snell_latest_version _init_version_cache _save_version_cache _get_release_versions; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
VERSION_CACHE_DIR="$fixture/cache"
SNELL_DEFAULT_VERSION="5.0.1"
_err() { echo "$*" >&2; }
_is_cache_fresh() { return 1; }
_get_cached_version() { [[ -f "$VERSION_CACHE_DIR/surge-networks_snell" ]] && cat "$VERSION_CACHE_DIR/surge-networks_snell"; }
_is_plain_version() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; }
# Release notes list every Snell line, newest first: 6.x above 5.x.
_get_snell_versions_from_kb() { printf '%s\n' 6.0.0 6.0.0b4 5.0.2b1 5.0.1 5.0.0 4.1.1 | head -n "${1:-10}"; }
[[ "$(_get_snell_v5_versions_from_kb 10 | tr '\n' ' ')" == '5.0.2b1 5.0.1 5.0.0 ' ]]
[[ "$(_get_snell_latest_version false true)" == 5.0.1 ]]          # stable 5.x only, never 6.0.0
[[ "$(cat "$VERSION_CACHE_DIR/surge-networks_snell")" == 5.0.1 ]]
[[ "$(_get_release_versions surge-networks/snell 10 stable | tr '\n' ' ')" == '5.0.1 5.0.0 ' ]]
# A cache written by an older script with 6.0.0 is dropped; a 5.x one is kept.
echo 6.0.0 > "$VERSION_CACHE_DIR/surge-networks_snell"
printf '6.0.0\n5.0.1\n' > "$VERSION_CACHE_DIR/surge-networks_snell_releases_all"
_init_version_cache
[[ ! -e "$VERSION_CACHE_DIR/surge-networks_snell" && ! -e "$VERSION_CACHE_DIR/surge-networks_snell_releases_all" ]]
echo 5.0.1 > "$VERSION_CACHE_DIR/surge-networks_snell"
_init_version_cache
[[ "$(cat "$VERSION_CACHE_DIR/surge-networks_snell")" == 5.0.1 ]]
# No 5.x in the notes: the built-in default.
_get_snell_versions_from_kb() { printf '%s\n' 6.1.0 6.0.0; }
[[ "$(_get_snell_latest_version false true)" == 5.0.1 ]]
echo 'PASS Snell v5 versions come from the 5.x line only; stale 6.x caches dropped'
