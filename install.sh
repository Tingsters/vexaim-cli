#!/bin/sh
# Install vexaim and its matching general-purpose skill; no robot required.
# --agents all|goose|codex|claude --version VERSION --from-dir RELEASE_ASSETS
# --home DIR --dry-run --uninstall --force --udev --from-source
# An extracted platform bundle installs its own files offline.
set -eu
REPO=https://github.com/Tingsters/vexaim-cli
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
TARGET_HOME=$HOME; AGENTS=all; VERSION=''; BASE_URL=''; FROM_DIR=''
FROM_SOURCE=0; DRY=0; UNINSTALL=0; FORCE=0; UDEV=0
MARKER=.vexaim-installed
say() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
valid_version() { printf '%s\n' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --agents|--version|--base-url|--from-dir|--home)
      [ $# -ge 2 ] || die "$1 needs a value"
      case "$1" in --agents) AGENTS=$2 ;; --version) VERSION=$2 ;; --base-url) BASE_URL=$2 ;;
        --from-dir) FROM_DIR=$2 ;; --home) TARGET_HOME=$2 ;; esac
      shift 2 ;;
    --from-source) FROM_SOURCE=1; shift ;; --dry-run) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;; --force) FORCE=1; shift ;;
    --udev) UDEV=1; shift ;; --no-doctor) shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;; *) die "unknown option: $1" ;;
  esac
done
USE_AGENTS=0; USE_CLAUDE=0
for a in $(printf '%s' "$AGENTS" | tr ',' ' '); do
  case "$a" in goose|codex) USE_AGENTS=1 ;; claude) USE_CLAUDE=1 ;;
    all) USE_AGENTS=1; USE_CLAUDE=1 ;; *) die "unknown agent: $a" ;; esac
done
set --
[ "$USE_AGENTS" -eq 0 ] || set -- "$@" "$TARGET_HOME/.agents/skills/vex-aim"
[ "$USE_CLAUDE" -eq 0 ] || set -- "$@" "$TARGET_HOME/.claude/skills/vex-aim"
[ $# -gt 0 ] || die 'no agents selected'
for d do
  [ ! -L "$d" ] || die "refusing linked skill folder: $d"
  if [ "$UNINSTALL" -eq 1 ]; then
    if [ -f "$d/$MARKER" ]; then
      if [ "$DRY" -eq 1 ]; then say "would remove $d"; else rm -rf -- "$d"; fi
    elif [ -e "$d" ]; then say "$d was not installed by this script: left alone"; fi
  elif [ -e "$d" ] && [ ! -f "$d/$MARKER" ] && [ "$FORCE" -eq 0 ]; then
    die "$d was not installed by this script; move it away or use --force"
  fi
done
[ "$UNINSTALL" -eq 0 ] || exit 0
[ -z "$VERSION" ] || valid_version "$VERSION" || die 'invalid release version'
OS=$(uname -s); ARCH=$(uname -m)
case "$OS/$ARCH" in Linux/x86_64) TARGET=linux-x86_64 ;; Darwin/arm64) TARGET=macos-arm64 ;;
  Darwin/x86_64) TARGET=macos-x86_64 ;; *) TARGET='' ;; esac
[ -n "$TARGET" ] || [ "$FROM_SOURCE" -eq 1 ] || die "no prebuilt binary for $OS/$ARCH; see source build instructions"
ARCHIVE=vexaim-$TARGET.tar.gz
if [ "$DRY" -eq 1 ]; then
  for d do say "would install matching executable and skill into $d"; done
  say 'dry run: nothing changed'; exit 0
fi
TMP=$(mktemp -d); trap 'rm -rf -- "$TMP"' EXIT INT TERM
fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 2 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1"
  else die 'need curl or wget'; fi
}
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
bundle=$TMP
if [ "$FROM_SOURCE" -eq 1 ]; then
  command -v cargo >/dev/null 2>&1 || die 'source builds require an existing Rust toolchain'
  cargo build --locked --release --manifest-path "$HERE/cli/Cargo.toml"
  cp "$HERE/cli/target/release/vexaim" "$TMP/vexaim"
  cp "$HERE/VERSION" "$TMP/VERSION"; cp -R "$HERE/skill" "$TMP/skill"
elif [ -z "$FROM_DIR" ] && [ -z "$BASE_URL" ] && [ -f "$HERE/vexaim" ]; then
  bundle=$HERE
else
  assets=$FROM_DIR
  if [ -z "$assets" ]; then
    if [ -z "$BASE_URL" ]; then
      if [ -z "$VERSION" ]; then
        fetch "$REPO/releases/latest/download/VERSION" "$TMP/latest" || die 'download failed; retry or use --from-dir'
        VERSION=$(tr -d '\r\n' < "$TMP/latest")
      fi
      valid_version "$VERSION" || die 'invalid release version'
      BASE_URL=$REPO/releases/download/v$VERSION
    fi
    fetch "$BASE_URL/$ARCHIVE" "$TMP/$ARCHIVE" && fetch "$BASE_URL/SHA256SUMS" "$TMP/SHA256SUMS" || die 'download failed; retry or use --from-dir (no automatic source build)'
    assets=$TMP
  fi
  want=$(awk -v name="$ARCHIVE" '$2 == name { print $1 }' "$assets/SHA256SUMS")
  [ ${#want} -eq 64 ] || die "$ARCHIVE is not listed in SHA256SUMS exactly once"
  [ "$want" = "$(sha256_of "$assets/$ARCHIVE")" ] || die "checksum mismatch for $ARCHIVE"
  tar -xzf "$assets/$ARCHIVE" -C "$TMP"
fi
[ -f "$bundle/skill/vex-aim/SKILL.md" ] && [ -f "$bundle/VERSION" ] || die 'incomplete release bundle: missing skill or VERSION'
bundled_version=$(tr -d '\r\n' < "$bundle/VERSION")
valid_version "$bundled_version" || die 'invalid bundled version'
chmod +x "$bundle/vexaim"
actual=$("$bundle/vexaim" --version) || die 'the vexaim binary cannot run on this machine'
[ "$actual" = "vexaim $bundled_version" ] || die 'release version mismatch; no skill folders changed'
[ -z "$VERSION" ] || [ "$VERSION" = "$bundled_version" ] || die 'release version mismatch; no skill folders changed'
first=$1
for d do
  stage=$d.stage-$$; backup=$d.backup-$$
  [ ! -e "$stage" ] && [ ! -e "$backup" ] || die 'staging folder already exists'
  mkdir -p "$(dirname "$d")"
  cp -R "$bundle/skill/vex-aim" "$stage"; mkdir -p "$stage/bin"
  cp "$bundle/vexaim" "$stage/bin/vexaim"; chmod +x "$stage/bin/vexaim"
  printf 'vexaim-cli %s\n' "$bundled_version" > "$stage/$MARKER"
  if [ -e "$d" ]; then mv -- "$d" "$backup"; fi
  if ! mv -- "$stage" "$d"; then
    [ ! -e "$backup" ] || mv -- "$backup" "$d"
    rm -rf -- "$stage"; die 'installation failed; close active sessions before updating'
  fi
  rm -rf -- "$backup"
  if [ "$OS" = Darwin ]; then xattr -d com.apple.quarantine "$d/bin/vexaim" 2>/dev/null || true; fi
  say "installed $bundled_version executable and skill: $d"
done
if [ "$OS" = Linux ]; then
  if [ -f /etc/udev/rules.d/99-vex-aim.rules ]; then say 'udev rule already installed'
  elif [ "$UDEV" -eq 1 ]; then sh "$first/linux/install-udev.sh"
  else say "For Linux USB, ask before running: sh '$first/linux/install-udev.sh' (sudo). Reconnect USB afterward."; fi
fi
say "DONE. Tool: $first/bin/vexaim"
say 'Start a NEW agent session to load vex-aim. Then check readiness using your chosen USB or Bluetooth transport.'
