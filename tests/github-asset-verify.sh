#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _sha256_file _pinned_github_asset_sha256 _github_sidecar_sha256 _verify_github_release_asset _install_binary; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
asset=https://github.com/XTLS/Xray-core/releases/download/v26.11.9/Xray-linux-64.zip
printf 'fixture xray\n' > "$fixture/pkg"
good=$(_sha256_file "$fixture/pkg")
bad=$(printf '%064d' 0)
# api: ok / fail / nodigest；sidecar: good / bad / none
curl() {
    local url='' dest=''
    while [[ $# -gt 0 ]]; do
        case "$1" in -o) shift; dest="$1" ;; https://*) url="$1" ;; esac
        shift
    done
    echo "$url" >> "$fixture/urls"
    case "$url" in
        https://api.github.com/*)
            case "$api" in
                ok) jq -n --arg d "sha256:$good" '{assets:[{name:"Xray-linux-64.zip",digest:$d}]}' ;;
                nodigest) echo '{"assets":[{"name":"Xray-linux-64.zip"}]}' ;;
                *) return 22 ;;
            esac ;;
        *.dgst)
            [[ "$sidecar" != none ]] || return 22
            local h=$good; [[ "$sidecar" == good ]] || h=$bad
            printf 'MD5= %032d\nSHA1= %040d\nSHA2-256= %s\nSHA2-512= %0128d\n' 0 0 "$h" 0 > "$dest" ;;
        *.sha256|*.sha256sum) return 22 ;;
        *) cp "$fixture/pkg" "$dest" ;;
    esac
}
verify() { local rc=0; _verify_github_release_asset XTLS/Xray-core 26.11.9 "$asset" "$fixture/pkg" || rc=$?; echo "$rc"; }

api=ok sidecar=none
[[ "$(verify)" == 0 ]] || exit 1
grep -q '\.dgst$' "$fixture/urls" && exit 1
api=fail sidecar=good
[[ "$(verify)" == 0 ]] || exit 1
api=nodigest sidecar=good
[[ "$(verify)" == 0 ]] || exit 1
api=fail sidecar=bad
[[ "$(verify)" == 1 ]] || exit 1
api=fail sidecar=none
[[ "$(verify)" == 2 ]] || exit 1

# 安装入口按返回值给出不同提示，且都不安装。
_info() { :; }
_ok() { :; }
_err() { echo "err:$*" >> "$fixture/msgs"; }
_warn() { echo "warn:$*" >> "$fixture/msgs"; }
check_cmd() { return 1; }
_get_latest_version() { echo 26.11.9; }
install_xray_like() { _install_binary xray XTLS/Xray-core 'https://github.com/XTLS/Xray-core/releases/download/v$version/Xray-linux-${xarch}.zip' xray; }
xarch=64
api=fail sidecar=none
if install_xray_like; then exit 1; fi
grep -q '无法获取发布方 SHA-256' "$fixture/msgs" || exit 1
grep -q 'ALLOW_UNVERIFIED_DOWNLOADS' "$fixture/msgs" || exit 1
: > "$fixture/msgs"
api=fail sidecar=bad
if install_xray_like; then exit 1; fi
grep -q '不一致' "$fixture/msgs" || exit 1
grep -q 'ALLOW_UNVERIFIED_DOWNLOADS' "$fixture/msgs" && exit 1
echo 'PASS release digest preferred, .dgst fallback when API fails, mismatch and unavailable reported separately'
