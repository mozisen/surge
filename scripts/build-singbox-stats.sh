#!/usr/bin/env bash
set -euo pipefail
: "${CORE_VERSION:?}" "${CORE_ARCH:?}"
[[ "$CORE_VERSION" =~ ^[1-9][0-9]*\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
[[ "$(go env GOOS)" == linux && "$(go env GOARCH)" == "$CORE_ARCH" ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GOTOOLCHAIN=auto CGO_ENABLED=0 GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org
export GONOSUMDB= GONOPROXY= GOPRIVATE= GOFLAGS= GOBIN="$work/bin"
tags=with_gvisor,with_quic,with_wireguard,with_utls,with_acme,with_clash_api,with_v2ray_api
go install -p 2 -tags "$tags" -ldflags "-s -w -X github.com/sagernet/sing-box/constant.Version=$CORE_VERSION" "github.com/sagernet/sing-box/cmd/sing-box@v$CORE_VERSION"
go install github.com/fullstorydev/grpcurl/cmd/grpcurl@v1.9.4
"$work/bin/sing-box" version | tee "$work/version.txt"
grep -q with_v2ray_api "$work/version.txt"
[[ "$(awk '/^sing-box version / {print $3}' "$work/version.txt")" == "$CORE_VERSION" ]]
SINGBOX_TEST_BIN="$work/bin/sing-box" GRPCURL_TEST_BIN="$work/bin/grpcurl" bash tests/singbox-stats-live.sh
out="dist/v$CORE_VERSION/linux-$CORE_ARCH"
mkdir -p "$out"
tar -czf "$out/sing-box.tar.gz" -C "$work/bin" sing-box
jq -n --arg version "$CORE_VERSION" --arg arch "$CORE_ARCH" --arg tags "$tags" \
  --arg source "github.com/sagernet/sing-box@v$CORE_VERSION" --arg workflow_commit "${GITHUB_SHA:-local}" \
  --arg binary_sha256 "$(sha256sum "$work/bin/sing-box" | awk '{print $1}')" \
  --arg archive_sha256 "$(sha256sum "$out/sing-box.tar.gz" | awk '{print $1}')" \
  '{version:$version,arch:$arch,os:"linux",profile:"stats-v1",tags:$tags,source:$source,workflow_commit:$workflow_commit,binary_sha256:$binary_sha256,archive_sha256:$archive_sha256}' > "$out/manifest.json"
