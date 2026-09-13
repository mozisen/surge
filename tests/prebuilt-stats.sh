#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _download_singbox_stats_core _singbox_stats_build_version _sha256_file; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
_err() { echo "$*" >&2; }
_singbox_stats_libc() { echo glibc; }
mkdir "$fixture/source" "$fixture/ok" "$fixture/bad" "$fixture/missing"
printf 'fixture binary\n' > "$fixture/source/sing-box"
tar -czf "$fixture/source/pkg" -C "$fixture/source" sing-box
jq -n --arg archive "$(_sha256_file "$fixture/source/pkg")" --arg binary "$(_sha256_file "$fixture/source/sing-box")" \
  '{version:"1.14.0",arch:"amd64",libc:"glibc",os:"linux",profile:"stats-v1",archive_sha256:$archive,binary_sha256:$binary}' > "$fixture/source/manifest"
curl() {
    [[ "$missing" != true ]] || return 22
    local url='' dest=''
    while [[ $# -gt 0 ]]; do
        case "$1" in https://*) url="$1" ;; -o) shift; dest="$1" ;; esac
        shift
    done
    if [[ "$url" == */manifest.json ]]; then cp "$fixture/source/manifest" "$dest"; else cp "$fixture/source/pkg" "$dest"; fi
}
_download_singbox_stats_core 1.14.0 amd64 "$fixture/ok"
cmp "$fixture/source/sing-box" "$fixture/ok/bin/sing-box"
printf 'corrupt\n' >> "$fixture/source/pkg"
if _download_singbox_stats_core 1.14.0 amd64 "$fixture/bad"; then exit 1; fi
[[ ! -e "$fixture/bad/bin/sing-box" ]]
missing=true
if _download_singbox_stats_core 1.15.0 amd64 "$fixture/missing"; then exit 1; fi
[[ ! -e "$fixture/missing/bin/sing-box" ]]
if _download_singbox_stats_core 1.14.0 armv7 "$fixture/missing"; then exit 1; fi
echo 'PASS verified prebuilt extraction; corrupt/missing/unsupported packages refused without installing or compiling'
