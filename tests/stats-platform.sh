#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
for fn in _singbox_stats_libc _singbox_stats_version_gate; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
_warn() { echo "$*"; }
_err() { echo "$*"; }
ldd() { echo "$libc_output"; return 1; }
getconf() { return 1; }
libc_output='musl libc'; [[ "$(_singbox_stats_libc)" == musl ]]
libc_output='ldd (Debian GLIBC 2.41)'; [[ "$(_singbox_stats_libc)" == glibc ]]
libc_output=unknown; if _singbox_stats_libc; then exit 1; fi
sing-box() { echo "sing-box version $fixture_version"; }
curl() {
    [[ "${offline:-false}" != true ]] || return 22
    printf '%s' '[{"tag_name":"v1.15.0","draft":false,"prerelease":false},{"tag_name":"v1.14.2","draft":false,"prerelease":false},{"tag_name":"v1.14.10","draft":false,"prerelease":false},{"tag_name":"v1.14.99","draft":false,"prerelease":true}]'
}
fixture_version=1.14.10; _singbox_stats_version_gate
for fixture_version in 1.13.16 1.14.2 1.15.0; do
    if _singbox_stats_version_gate; then exit 1; fi
done
fixture_version=1.14.10; offline=true
if _singbox_stats_version_gate; then exit 1; fi
echo 'PASS libc detection, numeric latest 1.14 selection, upgrade prompt and network failure'
