#!/usr/bin/env bash
# Restarts an agent in its own tab, optionally as another agent. The new one
# starts beside the old one (same tab labels), gets a short handoff, then the
# old one ends, so the tab keeps its name and place. A coordinator restarted
# without an argv runs the assistant template again (edited instructions apply).
# Its workers get herdr.coordinator=<tab> so they stay nested under the new one.
# Usage: restart.sh <old address> [argv as JSON array]
# Prints the new agent's address.
# For the chat mod (mods/chat), two optional environment variables:
#   HERDR_RESTART_CHAT=<chat pane>  the new agent starts parked behind that chat pane
#                                   (herdr.chat label) instead of getting a pane in the tab.
#   HERDR_RESTART_RESUME=1          argv resumes the same conversation: no handoff is sent.
set -u
old=$1 argv=${2:-}
info=$(hc get "$old" --json) || exit 1
get() { jq -r "$1 // empty" <<<"$info"; }
space=$(get '.labels["herdr.space"]') tab=$(get '.labels["herdr.tab"]') role=$(get '.labels["herdr.role"]')
# Assistants start from the assistant template (earlier ones from "coordinator").
case $(get .template) in assistant|coordinator) role=coordinator ;; esac
cwd=$(get .cwd) app=$(get .status.app) pid=$(get .foreground.pid) created=$(get .created_ms)
# A parked agent (behind a chat) has no tab labels: the chat names where it goes instead.
# A coordinator in Chat mode says where it lives in its own labels (its workers name that tab).
[ -n "$tab" ] || tab=$(get '.labels["herdr.coordinator.tab"]')
[ -n "$space" ] && [ -n "$tab" ] || [ -n "${HERDR_RESTART_CHAT:-}" ] || [ -n "$(get '.labels["herdr.chat"]')" ] || exit 1

# Every start goes through launch admission (mods/tasks/bin/herdr_task/launch_admission.py), which plans it (L2): a
# restart continuing the old agent's conversation keeps the provider binding that agent recorded (--replaces: its
# terminal), and a new conversation plans from today's settings; an earlier start of the same Assistant or tab still
# open refuses, and it is claimed, rechecked and recorded as sent before hc runs. Checked here first, before this
# script changes anything (the old agent's workers, its handoff).
owner="$(cd "$(dirname "$0")/../tasks/bin" && pwd)/herdr-task"
# herdr-core's templates, where the owner reads them too (its HERDR_TASK_TEMPLATES, else herdr-core's own folder).
tdir=${HERDR_TASK_TEMPLATES:-$HOME/.config/herdr-core/templates}
aspace=${space:-$(get '.labels["herdr.coordinator.space"]')}
aspace=${aspace:-unplaced}
if [ "$role" = coordinator ]; then
  admit=(--role coordinator --space "$aspace")
else
  # A parked agent is named by its chat pane, as the chat names its start (mods/chat); else by its tab.
  aslot=${HERDR_RESTART_CHAT:-$(get '.labels["herdr.chat"]')}
  aslot=${aslot:-$tab}
  admit=(--role agent --space "$aspace" --slot "$aslot")
fi
admit+=(--replaces "$old")
# What it will run, for the owner to plan: the argv given, else (an Assistant) its template's command.
if [ -n "$argv" ]; then
  plan=(--argv "$argv")
elif [ "$role" = coordinator ]; then
  plan=(--new-start assistant --source assistant)
else
  plan=()
fi
# A Claude Code agent's own folder (its CLAUDE_CONFIG_DIR, read from its process as C1's rule reads it): where its
# session log is, and carried into the agent this starts so a restart keeps its profile. Unreadable refuses here,
# before any change. A start of another CLI (an argv naming it) carries none.
cdir=$HOME/.claude carry=""
if [ "$app" = claude-code ] && [ -n "$pid" ]; then
  first=$(jq -r '.[0] // empty' <<<"${argv:-[]}")
  if found=$("$owner" launch folder "$pid" 2>&1); then
    cdir=$found
  elif [ -n "$argv" ] && [ "${first##*/}" != claude ]; then
    : # switching to another CLI carries nothing: its log is looked for under ~/.claude, as before
  else
    printf '%s\n' "${found#herdr-task: }" >&2
    exit 1
  fi
  if [ "$cdir" != "$HOME/.claude" ] && { [ -z "$argv" ] || [ "${first##*/}" = claude ]; }; then
    carry=$cdir
    admit+=(--config-dir "$carry")
  fi
fi
# An Assistant restarted from a template with no command line has nowhere to carry another folder: refused now.
if [ -n "$carry" ] && [ -z "$argv" ] && [ "$role" = coordinator ] && \
    [ -z "$(awk '/^---[[:space:]]*$/ {f++; next} f == 1 && sub(/^command:[ \t]*/, "") {print; exit}' "$tdir/assistant.md" 2>/dev/null)" ]; then
  echo "This Assistant uses $carry, and its template has no command to start it there again. Nothing was started." >&2
  exit 1
fi
# start <hc run words>: hc's reply (--json) on stdout; a refusal's words on stderr, and nothing started.
start() {
  local out code
  out=$("$owner" launch run "${admit[@]}" ${plan[@]+"${plan[@]}"} --json -- "$@"); code=$?
  [ "$code" -eq 0 ] || jq -r '.error // empty' <<<"$out" >&2
  printf '%s\n' "$out"
  return "$code"
}
pre=$("$owner" launch run "${admit[@]}" ${plan[@]+"${plan[@]}"} --check --json) || { jq -r '.error // empty' <<<"$pre" >&2; exit 1; }
route=$(jq -r '.route // empty' <<<"$pre")

# What the previous agent did: its screen, and its session log when we can find it.
dir=${HERDR_APP_HOME:-$HOME/.config/herdr-app}/data/coordinator/handoff
mkdir -p "$dir"
screen="$dir/$old-$(date +%s).txt"
hc read "$old" --lines 400 >"$screen" 2>/dev/null
log=""
if [ "$app" = claude-code ] && [ -n "$pid" ]; then
  sid=$(jq -r '.sessionId // empty' "$cdir/sessions/$pid.json" 2>/dev/null)
  [ -n "$sid" ] && log=$(find "$cdir/projects" -name "$sid.jsonl" 2>/dev/null | head -1)
fi
if [ -z "$log" ] && [ -n "$created" ]; then
  log=$(find "$cdir/projects" "$HOME/.codex/sessions" "$HOME/.pi/agent/sessions" "$HOME/.local/share/opencode" \
      -type f \( -name '*.jsonl' -o -name '*.json' \) -newermt "@$((created / 1000))" 2>/dev/null \
    | xargs -r grep -l -F "\"$cwd\"" 2>/dev/null | xargs -r ls -t 2>/dev/null | head -1)
fi
was=${app:-the previous agent}
handoff="You are taking over this tab from $was ($old), which was restarted."
[ -n "$log" ] && handoff+=" Its session log is $log: read the recent part to pick up where it left off."
handoff+=" Its last screen is saved in $screen."

if [ "$role" = coordinator ]; then
  workers=$( { hc ls --json | jq -r --arg c "$old" '.terminals[] | select(.parent == $c) | .address'
    hc ls --json --label "herdr.coordinator=$tab" | jq -r --arg c "$old" '.terminals[] | select(.address != $c) | .address'; } | sort -u)
  if [ -n "$workers" ]; then
    list=""
    for w in $workers; do
      hc label "$w" "herdr.coordinator=$tab" >/dev/null 2>&1
      list+=" $w ($(hc get "$w" --json | jq -r '.name // .labels.where // ""'))"
    done
    handoff+=" Workers the previous coordinator started, still running:$list. They report to $old: watch each with hc wait <t> and tell each to report to you from now on."
  fi
fi

labels=(--label "herdr.space=$space" --label "herdr.tab=$tab")
[ "$role" = coordinator ] && labels+=(--label herdr.role=coordinator)
# An agent in Chat mode (parked behind a chat pane) restarts parked behind the same chat.
chat=${HERDR_RESTART_CHAT:-$(get '.labels["herdr.chat"]')}
if [ -n "$chat" ]; then
  origin=$(get '.labels["herdr.chat.origin"]'); origin=${origin:-$old}
  labels=(--keep --label "herdr.chat=$chat" --label "herdr.chat.origin=$origin")
  # What a coordinator chat finds its agent by (mods/chat), and where the coordinator lives.
  for k in herdr.chat.slot herdr.coordinator.space herdr.coordinator.tab; do
    v=$(get ".labels[\"$k\"]"); [ -n "$v" ] && labels+=(--label "$k=$v")
  done
  [ "$role" = coordinator ] && labels+=(--label herdr.role=coordinator)
fi
# The new agent never inherits a parent Claude Code session's markers the holder may carry (SHEP-86):
# the same line as core/clean-env.js CLEAN_ENV (test_repo keeps them equal).
clean='for v in $(env | sed -nE '"'"'s/^(CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_[A-Za-z0-9_]+)=.*/\1/p'"'"' | grep -vE '"'"'^CLAUDE_CODE_(USE|SKIP|DISABLE|ENABLE|MAX|OAUTH|CLIENT|API)_'"'"'); do unset "$v"; done;'
tpl=$tdir/assistant.md
# A coordinator restarted without an argv: the assistant template's own command and words.
own=""
[ -z "$argv" ] && [ "$role" = coordinator ] && own=$(awk '/^---[[:space:]]*$/ {f++; next} f == 1 && sub(/^command:[ \t]*/, "") {print; exit}' "$tpl" 2>/dev/null)
if [ "$route" = azure-foundry ]; then
  # Azure Foundry: the owner plans the agent's command (its recorded binding when it continues the conversation) and
  # runs it from its own one-off template in this one's place, with this one's words; nothing here composes it.
  one=herdr-handoff-$$
  file=$tdir/$one.md
  msg=""
  if [ -n "$argv" ]; then
    mapfile -t cmd < <(jq -r '.[]' <<<"$argv")
    [ ${#cmd[@]} -gt 0 ] || exit 1
    key=$(basename "${cmd[0]}")
    if [ -z "${HERDR_RESTART_RESUME:-}" ]; then
      [ "$key" = codex ] && [[ " ${cmd[*]} " != *" --no-daemon "* ]] && cmd+=(--no-daemon)
      msg=$handoff
    fi
    words=(--argv "$(printf '%s\0' "${cmd[@]}" | jq -Rsc 'split("\u0000") | .[:-1]')")
    command=${cmd[0]}
  else
    own=$(awk '/^---[[:space:]]*$/ {f++; next} f == 1 && sub(/^command:[ \t]*/, "") {print; exit}' "$tpl" 2>/dev/null)
    own=${own#exec }
    [ -n "$own" ] || { echo "The assistant template has no command to plan for Azure Foundry. Nothing was started." >&2; exit 1; }
    key=$(basename "${own%% *}") msg=$handoff command=$own
    words=()
  fi
  if [ -n "$msg" ] && [ "$role" = coordinator ]; then
    msg="$(awk 'f>=2 {print} /^---[[:space:]]*$/ {f++}' "$tpl")"$'\n\n'"$msg"
  fi
  { printf -- '---\nname: %s\ndescription: A one-off Herdr restart, removed after use.\ncommand: %s\n---\n' "$one" "$command"
    printf '%s' "$msg"; } >"$file"
  out=$("$owner" launch run "${admit[@]}" --new-start "$one" --source "$one" ${words[@]+"${words[@]}"} --json -- \
    --bg --json --no-parent --cwd "$cwd" "${labels[@]}" --label "herdr.agent=$key" "$one")
  code=$?
  rm -f "$file"
  [ "$code" -eq 0 ] || { jq -r '.error // empty' <<<"$out" >&2; exit 1; }
  new=$(jq -r '.address // empty' <<<"$out")
  if [ -n "$new" ] && [ -n "$msg" ] && [ "$(jq -r '.first_message.sent' <<<"$out")" = false ]; then
    hc wait "$new" --timeout 90 >/dev/null 2>&1
    hc send "$new" "$msg" >/dev/null 2>&1
  fi
elif [ -n "${HERDR_RESTART_RESUME:-}" ] && [ -n "$argv" ]; then
  mapfile -t cmd < <(jq -r '.[]' <<<"$argv")
  [ ${#cmd[@]} -gt 0 ] || exit 1
  agent=$(basename "${cmd[0]}")
  [ -n "$carry" ] && cmd=(env "CLAUDE_CONFIG_DIR=$carry" "${cmd[@]}")
  new=$(start --bg --json --no-parent --cwd "$cwd" "${labels[@]}" --label "herdr.agent=$agent" -- sh -c "$clean"' exec "$@"' herdr-clean "${cmd[@]}" | jq -r '.address // empty')
elif [ -z "$argv" ] && [ "$role" = coordinator ] && [ -z "$own" ]; then
  new=$(start --bg --json --no-parent --cwd "$cwd" "${labels[@]}" assistant "$handoff" | jq -r '.address // empty')
else
  if [ -n "$own" ]; then
    own=${own#exec }
    line=$own key=$(basename "${own%% *}")
  else
    mapfile -t cmd < <(jq -r '.[]' <<<"$argv")
    [ ${#cmd[@]} -gt 0 ] || exit 1
    key=$(basename "${cmd[0]}")
    # Codex runs its commands outside hc without --no-daemon.
    [ "$key" = codex ] && [[ " ${cmd[*]} " != *" --no-daemon "* ]] && cmd+=(--no-daemon)
    line=$(printf '%q ' "${cmd[@]}")
  fi
  [ -n "$carry" ] && line="env CLAUDE_CONFIG_DIR=$(printf '%q' "$carry") $line"
  msg=$handoff
  if [ "$role" = coordinator ]; then
    body=$(awk 'f>=2 {print} /^---[[:space:]]*$/ {f++}' "$tpl")
    msg="$body"$'\n\n'"$handoff"
  fi
  # hc delivers a template's first message once the agent is ready, so the
  # handoff goes in a one-off template, removed once it has started.
  one=herdr-handoff-$$
  file=$tdir/$one.md
  { printf -- '---\nname: %s\ndescription: A one-off Herdr handoff, removed after use.\ncommand: %s\n---\n' "$one" "$clean exec $line"
    printf '%s\n' "$msg"; } >"$file"
  out=$(start --bg --json --no-parent --cwd "$cwd" "${labels[@]}" --label "herdr.agent=$key" "$one")
  rm -f "$file"
  new=$(jq -r '.address // empty' <<<"$out")
  # Some agents (Codex's animated start) never settle for hc: send once it reports a status.
  if [ -n "$new" ] && [ "$(jq -r '.first_message.sent' <<<"$out")" = false ]; then
    hc wait "$new" --timeout 90 >/dev/null 2>&1
    hc send "$new" "$msg" >/dev/null 2>&1
  fi
fi
[ -n "$new" ] || exit 1
hc kill "$old" >/dev/null 2>&1
hc rm "$old" >/dev/null 2>&1
echo "$new"
exit 0
