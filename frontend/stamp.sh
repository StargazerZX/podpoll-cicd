#!/bin/sh
# stamp.sh SRC_DIR OUT_DIR -- runs at IMAGE BUILD time (see Dockerfile), with the build-args in env.
#
# Writes OUT_DIR/{index.html, build.json, version.txt} plus the static assets. Every value can come
# from a branch name or a CI variable, so it is sanitised first, with the SAME rules as api/app.py
# (api/tests/test_stamp_parity.py checks that the two agree):
#   APP_VERSION -> [0-9A-Za-z.+-]    (anything else becomes "-"; "feature/x" -> "feature-x")
#   GIT_SHA     -> 7-40 hex chars, else "unknown"
#   URLs        -> http(s) and a quote-free character set, else ""
# After that, no value can contain "|", a quote or a backslash, so the "|" sed delimiter and
# the JSON below are safe. "&" is still escaped because sed treats it specially.
set -eu
export LC_ALL=C
SRC="$1"
OUT="$2"

trim() { printf '%s' "$1" | tr -d '\r\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

# clean VALUE ALLOWED_BRACKET_BODY DEFAULT MAX_LEN
clean() {
  v=$(trim "$1")
  if [ -z "$v" ]; then printf '%s' "$3"; return; fi
  printf '%s' "$v" | sed "s/[^$2]/-/g" | cut -c1-"$4"
}
clean_sha() {
  v=$(trim "$1" | tr 'A-F' 'a-f')
  if printf '%s' "$v" | grep -Eq '^[0-9a-f]{7,40}$'; then printf '%s' "$v"; else printf 'unknown'; fi
}
clean_url() {
  v=$(trim "$1")
  if [ "${#v}" -le 512 ] && printf '%s' "$v" | grep -Eq '^https?://[0-9A-Za-z._~:/?#@!$&()*+,;=%-]+$'; then
    printf '%s' "$v"
  fi
}
clean_time() {
  v=$(trim "$1")
  if printf '%s' "$v" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
    printf '%s' "$v"; else printf 'unknown'; fi
}
sed_escape() { printf '%s' "$1" | sed 's/[&|\\]/\\&/g'; }

VERSION=$(clean "${APP_VERSION:-}" '0-9A-Za-z.+-' dev 64)
MAJOR=$(printf '%s' "$VERSION" | sed -n 's/^v\{0,1\}0*\([0-9][0-9]*\).*/\1/p')
SHA=$(clean_sha "${GIT_SHA:-}")
SHORT=unknown; [ "$SHA" = unknown ] || SHORT=$(printf '%s' "$SHA" | cut -c1-7)
REF=$(clean "${GIT_REF:-}" '0-9A-Za-z._/+-' unknown 128)
BID=$(clean "${BUILD_ID:-}" '0-9A-Za-z._-' local 64)
BURL=$(clean_url "${BUILD_URL:-}")
CI=$(clean "${CI_SYSTEM:-}" '0-9a-z-' local 32)
BTIME=$(clean_time "${BUILD_TIME:-}")
SRCURL=$(clean_url "${SOURCE_URL:-}")
COMMIT=""; [ -n "$SRCURL" ] && [ "$SHA" != unknown ] && COMMIT="$SRCURL/commit/$SHA"

mkdir -p "$OUT"
sed -e "s|__APP_VERSION__|$(sed_escape "$VERSION")|g" \
    -e "s|__APP_MAJOR__|$(sed_escape "$MAJOR")|g" \
    -e "s|__GIT_SHA__|$(sed_escape "$SHA")|g" \
    -e "s|__GIT_REF__|$(sed_escape "$REF")|g" \
    -e "s|__BUILD_ID__|$(sed_escape "$BID")|g" \
    -e "s|__BUILD_URL__|$(sed_escape "$BURL")|g" \
    -e "s|__CI_SYSTEM__|$(sed_escape "$CI")|g" \
    -e "s|__BUILD_TIME__|$(sed_escape "$BTIME")|g" \
    -e "s|__SOURCE_URL__|$(sed_escape "$SRCURL")|g" \
    "$SRC/index.html" > "$OUT/index.html"

cat > "$OUT/build.json" <<JSON
{"version":"$VERSION","git_sha":"$SHA","git_sha_short":"$SHORT","git_ref":"$REF","build_id":"$BID","build_url":"$BURL","ci_system":"$CI","build_time":"$BTIME","source_url":"$SRCURL","commit_url":"$COMMIT"}
JSON
printf '%s\n' "$VERSION" > "$OUT/version.txt"
cp "$SRC/app.js" "$SRC/logic.js" "$SRC/app.css" "$OUT/"
