#!/bin/sh
# Installer tests. No robot needed. Uses a throwaway --home and a local mock "release" server.
# usage: dev/test-install.sh <assets-dir>   where <assets-dir> has vexaim-<target>.tar.gz + SHA256SUMS
#        (produce it with scripts/package.sh)
# ok/bad never fail, so `A && ok || bad` is a safe if/else here.
# shellcheck disable=SC2015
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="${1:?usage: $0 <assets-dir>}"
WORK="$(mktemp -d)"; SERVER_PID=""
trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; rm -rf "$WORK"' EXIT INT TERM
pass=0; fail=0
ok()   { pass=$((pass+1)); printf 'PASS  %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf 'FAIL  %s\n' "$1"; }
check() { # description, command...
  d="$1"; shift
  if "$@" >"$WORK/out.txt" 2>&1; then ok "$d"; else bad "$d"; sed 's/^/        /' "$WORK/out.txt"; fi
}
expect_fail() { # description, grep-pattern, command...
  d="$1"; pat="$2"; shift 2
  if "$@" >"$WORK/out.txt" 2>&1; then bad "$d (should have failed)"; else
    if grep -q "$pat" "$WORK/out.txt"; then ok "$d"; else bad "$d (wrong message)"; sed 's/^/        /' "$WORK/out.txt"; fi
  fi
}
I() { sh "$HERE/install.sh" "$@"; }

# 1. dry run changes nothing
H1="$WORK/home with spaces"; mkdir -p "$H1"
check "dry run succeeds" I --home "$H1" --dry-run --from-dir "$ASSETS"
[ -z "$(find "$H1" -type f)" ] && ok "dry run created no files" || bad "dry run created files"

# 2. install, binary + skill present for both locations
check "install from local assets" I --home "$H1" --from-dir "$ASSETS" --no-doctor
for d in .agents/skills/vex-aim .claude/skills/vex-aim; do
  [ -x "$H1/$d/bin/vexaim" ] && [ -f "$H1/$d/SKILL.md" ] && [ -f "$H1/$d/.vexaim-installed" ] && ok "installed $d" || bad "missing files in $d"
  [ -f "$H1/$d/references/sessions-and-motion.md" ] && ok "installed $d prompt/session guidance" || bad "missing session reference in $d"
done
check "installed binary runs" "$H1/.agents/skills/vex-aim/bin/vexaim" --version

# Streamed installation must fetch a release even if the caller's directory
# contains an unrelated executable. No checkout or adjacent bundle is present.
printf '#!/bin/sh\nprintf "unrelated executable\\n"\n' > "$WORK/vexaim"
chmod +x "$WORK/vexaim"
# Keep the pipe to exercise the same invocation as curl | sh.
# shellcheck disable=SC2002
stream_install() { (cd "$WORK" && cat "$HERE/install.sh" | sh -s -- --home "$WORK/streamed home"); }
check "streamed shell fetches the latest release without a checkout" stream_install
[ -x "$WORK/streamed home/.agents/skills/vex-aim/bin/vexaim" ] && ok "streamed binary installed" || bad "streamed binary missing"

# The downloadable archive is independently installable without this checkout.
EXTRACTED="$WORK/standalone bundle"; mkdir -p "$EXTRACTED"
for archive in "$ASSETS"/*.tar.gz; do tar -xzf "$archive" -C "$EXTRACTED"; done
check "extracted bundle installs offline" sh "$EXTRACTED/install.sh" --home "$WORK/offline home" --agents codex
[ -f "$WORK/offline home/.agents/skills/vex-aim/references/sessions-and-motion.md" ] && ok "offline bundle includes skill references" || bad "offline bundle missing references"
expect_fail "requested release mismatch is refused" "release version mismatch" I --home "$WORK/mismatch" --from-dir "$ASSETS" --version 0.2.99

# 3. idempotent re-run
check "re-run is idempotent" I --home "$H1" --from-dir "$ASSETS" --no-doctor

# 4. single agent selection
H2="$WORK/h2"; mkdir -p "$H2"
check "--agents claude" I --home "$H2" --agents claude --from-dir "$ASSETS" --no-doctor
[ -d "$H2/.claude/skills/vex-aim" ] && [ ! -e "$H2/.agents" ] && ok "only the claude location was written" || bad "--agents claude wrote the wrong places"

# 5. tampered archive is refused and nothing is installed
BAD="$WORK/bad"; mkdir -p "$BAD"; cp "$ASSETS"/* "$BAD"/
for f in "$BAD"/vexaim-*.tar.gz; do printf 'tampered' >> "$f"; done
H3="$WORK/h3"; mkdir -p "$H3"
expect_fail "tampered archive is rejected" "checksum mismatch" I --home "$H3" --from-dir "$BAD" --no-doctor
[ -z "$(find "$H3" -type f)" ] && ok "nothing installed after checksum failure" || bad "files installed despite bad checksum"

# 6. archive missing from SHA256SUMS is refused
NOSUM="$WORK/nosum"; mkdir -p "$NOSUM"; cp "$ASSETS"/*.tar.gz "$NOSUM"/; : > "$NOSUM/SHA256SUMS"
expect_fail "unlisted archive is rejected" "not listed in SHA256SUMS" I --home "$H3" --from-dir "$NOSUM" --no-doctor

# 7. refuses to overwrite a skill it did not install; --force overrides
H4="$WORK/h4"; mkdir -p "$H4/.agents/skills/vex-aim"; echo mine > "$H4/.agents/skills/vex-aim/SKILL.md"
expect_fail "foreign skill dir is not overwritten" "not installed by this script" I --home "$H4" --agents goose --from-dir "$ASSETS" --no-doctor
[ "$(cat "$H4/.agents/skills/vex-aim/SKILL.md")" = "mine" ] && ok "foreign skill left intact" || bad "foreign skill was modified"
check "--force overrides" I --home "$H4" --agents goose --from-dir "$ASSETS" --no-doctor --force

# 8. uninstall removes ours only
mkdir -p "$H1/.claude/skills/other"; echo keep > "$H1/.claude/skills/other/SKILL.md"
check "uninstall" I --home "$H1" --uninstall
[ ! -e "$H1/.agents/skills/vex-aim" ] && [ ! -e "$H1/.claude/skills/vex-aim" ] && ok "our skill dirs removed" || bad "skill dirs remain"
[ -f "$H1/.claude/skills/other/SKILL.md" ] && ok "unrelated skills untouched" || bad "unrelated skill removed"
H5="$WORK/h5"; mkdir -p "$H5/.agents/skills/vex-aim"; echo mine > "$H5/.agents/skills/vex-aim/SKILL.md"
check "uninstall skips foreign dir" I --home "$H5" --uninstall
[ -f "$H5/.agents/skills/vex-aim/SKILL.md" ] && ok "foreign dir survived uninstall" || bad "foreign dir deleted by uninstall"

# 9. real HTTP download from a mock release server (python3 required)
if command -v python3 >/dev/null 2>&1; then
  PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  (cd "$ASSETS" && python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1) & SERVER_PID=$!
  sleep 1
  H6="$WORK/h6"; mkdir -p "$H6"
  check "download over HTTP + verify" I --home "$H6" --base-url "http://127.0.0.1:$PORT" --no-doctor
  [ -x "$H6/.agents/skills/vex-aim/bin/vexaim" ] && ok "downloaded binary installed" || bad "no binary after download"
  kill "$SERVER_PID" 2>/dev/null; SERVER_PID=""
else
  printf 'SKIP  HTTP download test (no python3)\n'
fi

# 10. offline: clear error, nothing installed (PATH without cargo so no source fallback)
H7="$WORK/h7"; mkdir -p "$H7"
expect_fail "download failure explains options" "download failed" env PATH="/usr/bin:/bin" sh "$HERE/install.sh" --home "$H7" --base-url "http://127.0.0.1:9" --no-doctor
[ -z "$(find "$H7" -type f)" ] && ok "nothing installed after download failure" || bad "files installed after download failure"

# 11. bad arguments
expect_fail "unknown agent rejected" "unknown agent" I --home "$WORK/h8" --agents nonsense --dry-run
expect_fail "unknown option rejected" "unknown option" I --bogus

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
