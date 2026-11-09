"""Provider bindings and launch plans: Personal (the default: the CLI's own configuration and
sign-in, untouched) or Azure Foundry, from nonsecret settings alone.

This module never reads a credential. A plan names the variable the CLI itself reads on the
execution host (ANTHROPIC_FOUNDRY_API_KEY, ANTHROPIC_FOUNDRY_AUTH_TOKEN, AZURE_OPENAI_API_KEY);
its value stays in that host's environment and never enters argv, settings, labels or records.
A binding's fingerprint covers its CLI, endpoint or resource, deployment and authentication
method: it does not attest an account, and rotating a credential doesn't change it.

The supported combinations are the four in docs/azure-launch-plans.md, each from the official
contract for the inspected CLI version; anything else is refused. Since A2 a valid Azure plan is
dispatched where its start records it (docs/migration/upstream-v3.1.3.md, A2): a task's agent
(start, the tick's queue, an automation's run, resume, switch, a backup) and an Assistant's new
start from its three new-start sites (`herdr-task launch run --new-start`). Each start records its
nonsecret binding (recorded()); resuming a recorded conversation plans from that record, never
from today's defaults, and refuses when its routing (route, resource or endpoint, sign-in method)
changed since (admit_launch(bound=...)). Since L2 the same rule holds where an agent comes back: a
restart (restart.sh, the window's and the web's Restart and Switch agent) or a revival continuing
its conversation plans from its recorded binding, and one starting a new conversation from today's
settings (admit_assistant; revive.py)."""

import hashlib
import json
import os
import re
import types

from .base import Fail, HOME
from . import settings as settings_file
from .settings import agent_argv, agent_key, bare, settings_layers


PERSONAL, AZURE = "personal", "azure-foundry"
KINDS = ("claude", "codex")
# Settings' "provider" section (Everywhere, this machine, the folder's space: the most specific
# wins, field by field). Only these names, each text: a field it doesn't know is refused, so a key
# or token put there by mistake is never read as configuration. That rule holds on every route,
# Personal too (settings are copied between machines, so a secret there is said, not started
# past); with no "provider" section at all nothing is checked. azure_subscription is discovery's only.
FIELDS = ("route", "azure_subscription", "claude_resource", "claude_deployment", "claude_auth",
          "codex_endpoint", "codex_deployment", "codex_auth", "worker_claude_deployment", "worker_codex_deployment",
          "coordinator_claude_deployment", "coordinator_codex_deployment")
# A role's own deployment for each CLI (Settings › Agents: the Assistant's and the workers'), for new starts only.
# Unset or "" follows the CLI's deployment above. A task's reviewer and backup are workers.
ROLES = ("worker", "coordinator")
# Each authentication method and the variable the CLI reads for it (None: no variable, the
# Azure SDK's default credential chain on the execution host).
CLAUDE_AUTH = {"entra-id": None, "api-key": "ANTHROPIC_FOUNDRY_API_KEY", "bearer-token": "ANTHROPIC_FOUNDRY_AUTH_TOKEN"}
CODEX_AUTH = {"api-key": "AZURE_OPENAI_API_KEY"}
# The fingerprint's words for a method: the ones the 2.x planner hashed, so the same nonsecret
# configuration keeps the same fingerprint and Codex provider id here.
AUTH_WORDS = {"entra-id": "Entra ID", "api-key": "API key", "bearer-token": "Bearer token"}
# What Claude Code reads to pick a provider, an endpoint, a credential or a model alias. A plan
# sets every one: the Foundry route's own values, and "" for the rest, so a competing route or an
# inactive credential in the inherited environment can't win. Claude Code's documentation says an
# empty settings env value reads as unset for provider selection (the CLAUDE_CODE_USE_* names);
# that the endpoint, credential and model names read the same way is the 2.x planner's working
# assumption, not a documented contract: native qualification (Q) owns proving it. The active
# credential's variable is left out: inherited.
CLAUDE_ROUTING = ("CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_MANTLE",
                  "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
                  "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "ANTHROPIC_FOUNDRY_RESOURCE",
                  "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                  "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL")
# Codex merges provider tables by name: a reserved, configuration-specific name never reuses or
# changes a provider the person defined (their own "azure"), and stays the same for resume.
CODEX_PROVIDER = "shepherdr_azure_"

DEPLOYMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RESOURCE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?")
SUBSCRIPTION = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
# Azure public cloud's v1 Responses route only, as written: no userinfo, port, query, fragment,
# other path, custom domain or other cloud.
ENDPOINT = re.compile(r"(https://[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.openai\.azure\.com/openai/v1)/?")

NO_ROUTE = "Provider is Personal or Azure Foundry (\"personal\" or \"azure-foundry\"). Nothing was started."
NO_DEPLOYMENT = "Set an explicit Azure deployment name for {} (letters, digits, dots, dashes and underscores)."
NO_RESOURCE = "Set the Claude Azure resource name, not a URL."
NO_ENDPOINT = "Set the Codex Azure endpoint as https://RESOURCE.openai.azure.com/openai/v1, without credentials or query parameters."
NO_SUBSCRIPTION = "The discovery subscription is an Azure subscription ID (a UUID), or empty for the host's Azure CLI subscription."
NO_CLAUDE_AUTH = "Claude Code on Azure Foundry signs in with Entra ID, an API key or a bearer token (\"entra-id\", \"api-key\" or \"bearer-token\")."
NO_CODEX_AUTH = ("Codex on Azure signs in with an API key only (\"api-key\", from AZURE_OPENAI_API_KEY on the execution host): "
                 "Microsoft's Codex guide says Entra ID isn't available for Codex.")
NO_KIND = "Azure Foundry is set up for Claude Code and Codex only, not {}. Set Provider to Personal to start it."
# A Serve-from client (service/sync.ts) keeps its settings file in step with the machine serving the
# web app and writes it as its own, without pushed_from. Its herdr-core node record (core/host.js
# NODE_DOC, written by this machine's service) says it doesn't serve, so the file is that machine's.
NOT_SERVED_HERE = ("Azure Foundry starts agents only on the machine whose settings set it, and this machine's settings are "
                   "kept in step with the machine that serves the web app (Serve from): they are its. Nothing was started. "
                   "Set Provider to Personal for this machine or space.")
NOT_KNOWN_HERE = ("Azure Foundry starts agents only on the machine whose settings set it, and whether this machine's settings "
                  "are its own or a Serve-from copy can't be read now (herdr-core's documents). Nothing was started.")
NODE_DOC = "shepherdr.node"
NOT_LOCAL = ("Azure Foundry starts agents only on the machine whose window holds these settings: this machine's are a copy. "
             "Set Provider to Personal for this machine or space.")
# Never names the field it found: a key pasted in as a field's name would be repeated, and this
# reason is kept on a task or an automation (a tick's or a run's "Couldn't start").
NO_FIELD = ("Shepherdr settings' provider section has a field it doesn't know. Its fields are " + ", ".join(FIELDS) + ". "
            "Keys and tokens never go in settings: remove any other field. Nothing was started.")
NO_INLINE_CREDENTIAL = ("On Azure Foundry, {} comes from the execution host's environment, never from the argv's --settings: "
                        "remove it there. Nothing was started.")
NO_OPTION_AFTER_DASHES = ("On Azure Foundry, Claude Code's argv can't carry --settings or --model after a bare \"--\": there it "
                          "can't be told from an option. Remove it, or give it before the \"--\". Nothing was started.")
NO_SETTINGS_VALUE = "On Azure Foundry, Claude Code's --settings needs its inline JSON value right after it. Nothing was started."
# A settings file that is there but can't be read is never taken for "no settings" (Personal): its
# provider section could say otherwise (P17-7). Never repeats the file's words.
UNREADABLE = ("Shepherdr settings ({}) are there but can't be read as a settings file, so this start can't tell which "
              "provider they set. Nothing was started; fix or move the file.")
NOT_EXECUTION_HOST = ("Provider is Azure Foundry here, and Azure Foundry starts agents only on the machine whose settings set "
                      "it; this start would run on {}. Nothing was started. Set Provider to Personal to start it.")
# A start on Azure Foundry is planned from the agent's own command line; one that gives none (a template whose command
# the owner can't read as one plain agent command) can't be, so it never starts on the CLI's own sign-in instead.
RESTART_HELD = ("Provider is Azure Foundry here, and this start gives no agent command line to plan, so it would run on the "
                "CLI's own sign-in. Nothing was started or changed. Start a new Assistant chat, or set Provider to Personal "
                "for this space.")
# A recorded binding an agent's terminal says it started on, but no owner holds (L2: revival and restart): never read
# as Personal.
NO_BINDING = ("{who} started on Azure Foundry, and its recorded provider binding can't be found (not on its task, its "
              "terminal or its start's journal record), so it can't be continued on it. Nothing was started; it is never "
              "moved to Personal. Start a new conversation with a handoff (a task: resume or switch with --fresh; an "
              "Assistant: a new chat).")
# A restart that continues a recorded Azure conversation keeps its deployment (A2): a model the menu names instead is
# refused rather than silently replaced.
RESTART_MODEL = ("{who}'s conversation is recorded on Azure Foundry deployment {deployment}, and continuing it keeps that "
                 "deployment, so the model picked for this restart wouldn't be used. Nothing was started or changed. Pick "
                 "{deployment} to restart it, or start a new conversation with a handoff (switch with --fresh).")
# A restart starting a new conversation (a handoff, another CLI, a lost session's fresh start) takes today's settings,
# but not onto another route than the agent it replaces started on: that would move its work to another provider unasked.
RESTART_ROUTE = ("{who} started on {was}, and these settings now route new starts to {now}. Restarting it with a new "
                 "conversation here would move its work to another provider, so nothing was started or changed. Start a new "
                 "conversation on today's settings yourself (a new Assistant chat, or herdr-task resume or switch with "
                 "--fresh), or set the settings back.")
# A recorded conversation keeps the routing it started on: today's defaults never reroute it (A2).
CHANGED_ROUTING = ("{who}'s conversation started on {was}, and this folder's settings now route {cli} to {now}. Resuming it "
                   "would move it to another provider, resource or sign-in, so nothing was started or changed. Set the "
                   "settings back, or start a new conversation with a handoff (resume or switch with --fresh).")
UNKNOWN_RECORD = ("{who}'s recorded provider binding can't be read as one this version planned, so it can't be resumed on "
                  "it. Nothing was started; start a new conversation with a handoff (resume or switch with --fresh).")
TAB_PERSONAL = ("Provider is Azure Foundry here, and a tab agent starts Personal only: its start can't carry a launch plan "
                "(only a task's agent and an Assistant's new start can). Nothing was started. Start it as a task, or set "
                "Provider to Personal for this space.")
# A task's save-only choice for its first start (herdr-task select) under another routing than it was saved under: the
# contract's next step is saving it again or clearing it, never running it elsewhere or falling back to Personal.
STALE_TASK_CHOICE = ("{who}'s choice for its first start was saved under other provider settings (route, resource or "
                     "endpoint, or sign-in), so it isn't started on today's. Nothing was started. Save its choice again "
                     "(Model for its start, or herdr-task select), or use the configured defaults (Use configured defaults, "
                     "or herdr-task select --default).")
STALE_SELECTION = ("The provider settings or the choice changed since this start was chosen (revision {}), so it isn't what "
                   "was picked. Nothing was started; choose again.")


def clean(field, value):
    """One nonsecret field's value as it is kept ("" stays "": not set yet); a value that can't be
    one is refused with what it should be. Never echoes the value: it may be a pasted secret."""
    v = value.strip()
    if not v:
        return v
    if field == "route":
        if v not in (PERSONAL, AZURE):
            raise Fail(NO_ROUTE)
    elif field == "azure_subscription":
        if not SUBSCRIPTION.fullmatch(v):
            raise Fail(NO_SUBSCRIPTION)
    elif field == "claude_resource":
        if not RESOURCE.fullmatch(v):
            raise Fail(NO_RESOURCE)
    elif field == "codex_endpoint":
        m = ENDPOINT.fullmatch(v)
        if not m:
            raise Fail(NO_ENDPOINT)
        v = m.group(1)
    elif field.endswith(("claude_deployment", "codex_deployment")) and field in FIELDS:
        if not DEPLOYMENT.fullmatch(v):
            raise Fail(NO_DEPLOYMENT.format("Claude Code" if "claude" in field else "Codex"))
    elif field == "claude_auth":
        if v not in CLAUDE_AUTH:
            raise Fail(NO_CLAUDE_AUTH)
    elif field == "codex_auth":
        if v not in CODEX_AUTH:
            raise Fail(NO_CODEX_AUTH)
    else:
        raise Fail(NO_FIELD)
    return v


def read_strict(path=None):
    """The settings file, read once for a launch: {} when there is none (Personal stays the
    default), refused when it is there but unreadable, not JSON or not an object (P17-7)."""
    path = path or settings_file.SETTINGS
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError):
        raise Fail(UNREADABLE.format(path))
    try:
        d = json.loads(text)
    except ValueError:
        raise Fail(UNREADABLE.format(path))
    if not isinstance(d, dict):
        raise Fail(UNREADABLE.format(path))
    return d


def binding_for(s, space=None, d=None):
    """The nonsecret provider binding for this folder's launches: Everywhere's, then this
    machine's, then the space's own "provider" fields; a field a layer leaves out (or null) follows
    the layer above, and "" there is its own empty value. With no route anywhere: Personal.
    "local" is False for a copy the settings window or the service pushed to this machine
    ("pushed_from"); "source" says whose the file is for a route other than Personal (settings_source(): a
    Serve-from client's copy is the serving machine's). Launch admission (L1) also refuses Azure for a start on
    another machine. d: the settings as read_strict() read
    them (read here when not given): a file that is there but unreadable refuses, never reads as Personal."""
    d = read_strict() if d is None else d
    out = {f: "" for f in FIELDS}
    for layer in settings_layers(s, space, d):
        section = layer.get("provider") if isinstance(layer, dict) else None
        if section is None:
            continue
        if not isinstance(section, dict):
            raise Fail("Shepherdr settings' provider section isn't readable. Nothing was started; fix it in Settings.")
        for field, value in section.items():
            if field not in FIELDS:
                raise Fail(NO_FIELD)
            if value is None:
                continue
            if not isinstance(value, str):
                raise Fail(f"Shepherdr settings' provider {field} isn't text. Nothing was started; fix it in Settings.")
            out[field] = value
    # Only the route decides Personal: the Azure fields' values are checked when a plan needs
    # them, so a half-filled Azure setup never gets in Personal's way (the section's shape, above,
    # is checked on every route).
    out["route"] = clean("route", out["route"]) or PERSONAL
    out["local"] = not d.get("pushed_from")
    # Whose file it is decides Azure only; Personal never reads herdr-core's documents.
    out["source"] = ("pushed" if not out["local"] else settings_source()) if out["route"] != PERSONAL else None
    return out


def core_docs():
    """herdr-core's documents file on this machine (as backups.py reads it), for the default session."""
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
    return os.path.join(state, "herdr-core", "default", "docs.json")


def settings_source():
    """Whose this machine's settings file is, for a route that must run where it was set: "own" (no
    Shepherdr service here, so nothing syncs it, or this machine serves the web app), "serve-from" (its
    node record says another machine serves, so service/sync.ts keeps the file in step with that one),
    or "unknown" (the documents are there but can't be read, or the node record says neither)."""
    path = core_docs()
    try:
        with open(path) as f:
            docs = json.load(f)
    except FileNotFoundError:
        return "own"
    except (OSError, ValueError, UnicodeDecodeError):
        return "unknown"
    if not isinstance(docs, dict):
        return "unknown"
    # No node record: no Shepherdr service here, so nothing syncs the file. One that is there but
    # malformed (not a document, no value, no serving flag) can't say whose the file is.
    if NODE_DOC not in docs:
        return "own"
    entry = docs[NODE_DOC]
    node = entry.get("value") if isinstance(entry, dict) else None
    if not isinstance(node, dict) or not isinstance(node.get("serving"), bool):
        return "unknown"
    # This machine's own service decides serving (a host record it rejected doesn't count), so its flag is the answer.
    return "own" if node["serving"] else "serve-from"


def fingerprint(kind, target, deployment, auth):
    """The binding's nonsecret identity: what a conversation started on it is bound to."""
    return hashlib.sha256(json.dumps([kind, target, deployment, AUTH_WORDS[auth]], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def host_checks(binding):
    """Azure runs only where its settings were set: refused on a Serve-from client's copy, when that can't be read, or
    on a copy pushed here."""
    if binding.get("source") == "serve-from":
        raise Fail(NOT_SERVED_HERE)
    if binding.get("source") == "unknown":
        raise Fail(NOT_KNOWN_HERE)
    if not binding.get("local", True):
        raise Fail(NOT_LOCAL)


def role_deployment(binding, kind, role=None):
    """The deployment a new start of `role` uses for kind: the role's own when it sets one, else the CLI's."""
    own = binding.get(f"{role}_{kind}_deployment") if role in ROLES else ""
    return own or binding.get(f"{kind}_deployment") or ""


def launch_plan(kind, binding, role=None, deployment=None):
    """How one CLI is routed, from the binding alone: {route, agent, fingerprint, deployment, auth, target,
    credential (a variable's name, or None), settings_env (Claude Code's --settings env), args (Codex's -c
    overrides), env (nonsecret process variables)}. Personal changes nothing. role: whose deployment a new start
    takes (role_deployment); deployment: one chosen for this start itself (a task's or a chat's save-only
    selection), which wins. An unsupported or incomplete combination is refused, with what to set."""
    if binding["route"] == PERSONAL:
        return {"route": PERSONAL, "agent": kind, "fingerprint": PERSONAL, "deployment": None, "auth": None, "target": None,
                "credential": None, "settings_env": {}, "args": [], "env": {}}
    if kind not in KINDS:
        raise Fail(NO_KIND.format(kind))
    host_checks(binding)
    name = "Claude Code" if kind == "claude" else "Codex"
    deployment = clean(f"{kind}_deployment", deployment or role_deployment(binding, kind, role))
    if not deployment:
        raise Fail(NO_DEPLOYMENT.format(name))
    plan = {"route": AZURE, "agent": kind, "deployment": deployment, "settings_env": {}, "args": [], "env": {}}
    if kind == "claude":
        resource = clean("claude_resource", binding["claude_resource"])
        if not resource:
            raise Fail(NO_RESOURCE)
        auth = clean("claude_auth", binding["claude_auth"]) or "entra-id"
        credential = CLAUDE_AUTH[auth]
        env = {v: "" for v in CLAUDE_ROUTING if v != credential}
        env.update(CLAUDE_CODE_USE_FOUNDRY="1", ANTHROPIC_FOUNDRY_RESOURCE=resource, ANTHROPIC_DEFAULT_OPUS_MODEL=deployment,
                   ANTHROPIC_DEFAULT_SONNET_MODEL=deployment, ANTHROPIC_DEFAULT_HAIKU_MODEL=deployment)
        plan.update(fingerprint=fingerprint(kind, resource, deployment, auth), auth=auth, target=resource, credential=credential,
                    settings_env=env)
        return plan
    endpoint = clean("codex_endpoint", binding["codex_endpoint"])
    if not endpoint:
        raise Fail(NO_ENDPOINT)
    auth = clean("codex_auth", binding["codex_auth"]) or "api-key"
    credential = CODEX_AUTH[auth]
    mark = fingerprint(kind, endpoint, deployment, auth)
    ident = CODEX_PROVIDER + mark
    table = {"name": "Azure Foundry", "base_url": endpoint, "env_key": credential, "wire_api": "responses", "requires_openai_auth": False}
    plan.update(fingerprint=mark, auth=auth, target=endpoint, credential=credential,
                args=["-c", f"model_provider={json.dumps(ident)}",
                      "-c", f"model_providers.{ident}={{{','.join(f'{k}={json.dumps(v)}' for k, v in table.items())}}}"],
                env={"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""})
    return plan


# ---- recorded bindings: what a conversation started on (A2) ----------------------------------

PERSONAL_RECORD = {"route": PERSONAL}


def recorded(plan):
    """The nonsecret binding a start records with its agent: Personal's route alone, or an Azure plan's CLI, resource
    or endpoint (target), deployment, sign-in method and fingerprint. No variable's value, no account."""
    if plan["route"] == PERSONAL:
        return dict(PERSONAL_RECORD)
    return {k: plan[k] for k in ("route", "agent", "target", "deployment", "auth", "fingerprint")}


def routing_words(rec):
    """A recorded binding or plan's routing, in words for a refusal (never a value: none is kept)."""
    if (rec or {}).get("route") != AZURE:
        return "Personal (the CLI's own sign-in)"
    return f"Azure Foundry {rec.get('target')} with {AUTH_WORDS.get(rec.get('auth'), rec.get('auth'))}"


def same_routing(rec, plan):
    """Whether resuming the conversation recorded as rec on plan keeps its routing: the route, and on Azure the
    resource or endpoint and the sign-in method. The deployment is not compared: a resume keeps the recorded one."""
    if rec.get("route") != plan["route"]:
        return False
    return rec.get("route") == PERSONAL or (rec.get("target") == plan["target"] and rec.get("auth") == plan["auth"])


def binding_words(binding, kind):
    """Today's routing for kind, in words: only checked values are said (an unchecked one could be a pasted secret)."""
    if binding["route"] != AZURE:
        return routing_words(PERSONAL_RECORD)
    field = "claude_resource" if kind == "claude" else "codex_endpoint"
    try:
        target = clean(field, binding.get(field) or "")
        auth = clean(f"{kind}_auth", binding.get(f"{kind}_auth") or "") or ("entra-id" if kind == "claude" else "api-key")
    except Fail:
        return "Azure Foundry"
    return routing_words({"route": AZURE, "target": target or "(no resource set)", "auth": auth})


def plan_of_record(rec, binding, kind, who):
    """The plan a recorded conversation resumes on: its own recorded deployment and routing, rebuilt by the same
    planner (so the Claude Code environment and the Codex provider table are what its first start had), checked
    against today's settings: their routing for kind must still be the recorded one (a change refuses before any
    effect), and a record this version didn't write refuses. A deployment default changed since doesn't matter: the
    recorded one is kept."""
    rec = rec or PERSONAL_RECORD
    route = rec.get("route")
    if route not in (PERSONAL, AZURE) or (route == AZURE and rec.get("agent") != kind):
        raise Fail(UNKNOWN_RECORD.format(who=who))
    changed = Fail(CHANGED_ROUTING.format(who=who, was=routing_words(rec), cli="Claude Code" if kind == "claude" else "Codex",
                                          now=binding_words(binding, kind)))
    if route == PERSONAL:
        if binding["route"] != PERSONAL:
            raise changed
        return launch_plan(kind, binding)
    if binding["route"] != AZURE:
        raise changed
    now = launch_plan(kind, {**binding, f"{kind}_deployment": rec.get("deployment") or ""})
    if not same_routing(rec, now):
        raise changed
    if now["fingerprint"] != rec.get("fingerprint"):
        raise Fail(UNKNOWN_RECORD.format(who=who))
    return now


def selection_revision(binding, kind):
    """What a save-only new-start choice is bound to (a task's selector, an Assistant chat's pick): the routing its
    deployment would run on (route, resource or endpoint, sign-in method), as a short digest. Changed, a choice made
    under the old one is stale and refuses rather than run elsewhere (and never falls back to Personal)."""
    parts = {"route": binding["route"], "kind": kind}
    if binding["route"] == AZURE:
        target = binding.get("claude_resource" if kind == "claude" else "codex_endpoint") or ""
        parts.update(target=target.strip(), auth=(binding.get(f"{kind}_auth") or "").strip())
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


# Where an argv's options are taken to end: at its first bare "--", else at its end. For Codex
# the words from it on are operands; for Claude Code that isn't certain (compose guards it).
def options_end(argv):
    return argv.index("--", 1) if "--" in argv[1:] else len(argv)


def with_model(argv, flags, flag, model):
    """argv selecting `model` and no other: its first model selection keeps its place with the
    model as its value, every later one is dropped, and with none the flag is added. A selection
    is a flag and the word after it, `--flag=value`, or a one-letter flag with its value attached
    (`-mvalue`, `-m=value`: kept as the flag and the model, two words). A flag with no value of
    its own (it is the last option, or the next word is another option) takes the model and the
    next word stays. Words from a bare "--" on are left as they are: Codex's operands, and for
    Claude Code what compose() guards."""
    words = list(argv)
    end = options_end(words)
    out, i, found = words[:1], 1, False
    while i < end:
        a, i = words[i], i + 1
        if a in flags:
            if i < end and not words[i].startswith("-"):
                i += 1
            mine = [a, model]
        elif any(a.startswith(f + "=") for f in flags if f.startswith("--")):
            mine = [f"{a.split('=', 1)[0]}={model}"]
        elif any(a.startswith(f) and a != f for f in flags if not f.startswith("--")):
            mine = [a[:2], model]
        else:
            out.append(a)
            continue
        if not found:
            out += mine
        found = True
    out += words[end:]
    return out if found else out[:1] + [flag, model] + out[1:]


def model_of(argv):
    """The model argv selects (its first --model, or Codex's -m), or None: options only, as with_model reads them."""
    words = list(argv or [])
    flags = ("--model",) if agent_key(words or [""]) == "claude" else ("-m", "--model")
    end = options_end(words or [""])
    for i in range(1, end):
        a = words[i]
        if a in flags:
            return words[i + 1] if i + 1 < end and not words[i + 1].startswith("-") else None
        for f in flags:
            if a.startswith(f + "=") and f.startswith("--"):
                return a.split("=", 1)[1]
            if not f.startswith("--") and a.startswith(f) and a != f:
                return a[3:] if a.startswith(f + "=") else a[2:]
    return None


def codex_override_keys(argv):
    """The key of each -c/--config override in a Codex argv, as Codex reads it: the words before
    the first "=", trimmed (`-c key=value`, `-ckey=value`, `-c=key=value`, `--config key=value`,
    `--config=key=value`). Only its options are read: not the operands from a bare "--" on."""
    keys, words = [], argv[1:options_end(argv)]
    for i, a in enumerate(words):
        if a in ("-c", "--config"):
            value = words[i + 1] if i + 1 < len(words) else ""
        elif a.startswith("--config="):
            value = a[len("--config="):]
        elif a.startswith("-c") and not a.startswith("--"):
            value = a[3:] if a.startswith("-c=") else a[2:]
        else:
            continue
        keys.append(value.split("=", 1)[0].strip())
    return keys


def compose(plan, argv):
    """(argv, env) for a launch on this plan: the agent's own argv with the plan's routing, its
    effort, Fast and permission words kept; Personal: the argv as it is and no env. Refuses an
    argv that routes itself (its own provider, or a --settings file whose words can't be seen)
    or that carries the plan's credential variable in its own --settings."""
    if plan["route"] == PERSONAL:
        return list(argv), {}
    if agent_key(argv) != plan["agent"]:
        raise Fail(f"This plan is for {plan['agent']}, not {agent_key(argv)}.")
    if plan["agent"] == "claude":
        out = with_model(argv, ("--model",), "--model", plan["deployment"])
        end = options_end(out)
        # A bare "--" may end the options or be another option's value: which, for Claude Code,
        # isn't known. As a value, a --settings or --model after it is a real option that could
        # reroute the launch or carry a credential; as the end, reading that word as an option
        # would stand in for the plan's own. Neither is safe: refused, no argv word repeated.
        if any(a in ("--settings", "--model") or a.startswith(("--settings=", "--model=")) for a in out[end:]):
            raise Fail(NO_OPTION_AFTER_DASHES)
        # Any other word from the "--" on is left as it is, unexamined as an option before the
        # "--" is, and the plan's own --settings goes in front.
        if any(a.startswith("--settings=") for a in out[1:end]):
            raise Fail("On Azure Foundry, give Claude Code's --settings as a separate JSON word. Nothing was started.")
        if out[1:end].count("--settings") > 1:
            raise Fail("On Azure Foundry, give Claude Code one --settings word. Nothing was started.")
        if "--settings" in out[1:end]:
            i = out.index("--settings", 1)
            # The last option, with nothing after it before the "--" or the end, or followed by another
            # option (`--settings --effort high`): no value to read.
            if i + 1 >= end or out[i + 1].startswith("-"):
                raise Fail(NO_SETTINGS_VALUE)
            try:
                cur = json.loads(out[i + 1])
            except ValueError:
                cur = None
            # A settings file is never opened here: it could hold a key, and its words would end in argv.
            if not isinstance(cur, dict) or not isinstance(cur.get("env") or {}, dict):
                raise Fail("On Azure Foundry, Claude Code's --settings must be inline JSON, not a file. Nothing was started.")
            # The plan leaves the active credential's variable out, so one written inline would
            # stay in argv and in every record of it: refused by name, its value never repeated.
            if plan["credential"] and plan["credential"] in (cur.get("env") or {}):
                raise Fail(NO_INLINE_CREDENTIAL.format(plan["credential"]))
            out[i + 1] = json.dumps({**cur, "env": {**(cur.get("env") or {}), **plan["settings_env"]}})
            return out, dict(plan["env"])
        return out[:1] + ["--settings", json.dumps({"env": plan["settings_env"]})] + out[1:], dict(plan["env"])
    own = any(k in ("model_provider", "model_providers") or k.startswith("model_providers.") for k in codex_override_keys(argv))
    if own or any(a in ("--oss", "--local-provider") or a.startswith("--local-provider=") for a in argv[1:options_end(argv)]):
        raise Fail("On Azure, Codex's provider comes from Settings: remove the argv's own provider (model_provider, --oss). Nothing was started.")
    out = with_model(argv, ("-m", "--model"), "-m", plan["deployment"])
    return out[:1] + plan["args"] + out[1:], dict(plan["env"])


def admit_launch(s, argv, space=None, d=None, role=None, deployment=None, bound=None, who=None):
    """Before any launch effect (a worktree, a task's state, a terminal): the plan this start runs on. A new
    conversation (bound None) plans from today's settings: Personal passes as it always did; an Azure binding is
    checked whole, so an unsupported one says what is wrong, and a valid one is planned for role (its deployment,
    or `deployment` chosen for this start). A recorded conversation's resume (bound: its recorded binding,
    PERSONAL_RECORD for one recorded before A2) plans from that record (plan_of_record). d: the settings as launch
    admission read them (read_strict)."""
    binding = binding_for(s, space, d)
    kind = agent_key(argv)
    if bound is not None:
        plan = plan_of_record(bound, binding, kind, who or "This task")
    else:
        plan = launch_plan(kind, binding, role, deployment)
    compose(plan, argv)
    return plan


def restart_route(was, bound, binding, kind, who):
    """A restart starting a new conversation plans from today's settings, but never on another route than the agent it
    replaces started on (was: its recorded route): that would move its work to another provider unasked (L2)."""
    was = was or PERSONAL
    if binding["route"] != was:
        said = routing_words(bound) if bound else routing_words({"route": was}) if was == PERSONAL else "Azure Foundry"
        raise Fail(RESTART_ROUTE.format(who=who, was=said, now=binding_words(binding, kind)))


def resumes(argv):
    """Whether argv continues a conversation rather than starting one: Claude Code's --resume, -r, --continue or -c, or
    Codex's resume subcommand (core/agents.js freshArgv reads the same words). Only its options are read."""
    words = list(argv or [])[1:options_end(argv or [""])]
    if agent_key(argv) == "claude":
        return any(a in ("--resume", "-r", "--continue", "-c") or a.startswith("--resume=") for a in words)
    return agent_key(argv) == "codex" and "resume" in words


def admit_assistant(s, space=None, d=None, machine=None, argv=None, deployment=None, restart=None, tab=False):
    """An Assistant's (or a tab agent's) start, before any effect: its plan. A new start (argv: the agent's own argv,
    `launch run --new-start`) plans an Azure binding for the Assistant's role (its deployment, or the chat's chosen one).
    A restart (restart: {"bound": the replaced agent's recorded binding, or None when it can't be found; "who"}, L2)
    that continues the same conversation (resumes(argv)) plans from that record, as a task's resume does
    (plan_of_record: changed routing refuses, the recorded deployment is kept); one starting a new conversation (a
    handoff, another CLI, a lost session's fresh start) plans from today's settings as a new start does. A start with
    no argv to plan (a template the owner can't read words from) admits Personal only. tab: a tab agent's start, which
    never starts on Azure (only a task's agent and an Assistant can). machine: where it would run when that isn't here
    (`hc run --on`)."""
    binding = binding_for(s, space, d)
    if restart is not None and not (argv and resumes(argv)):
        restart_route(restart.get("route"), restart.get("bound"), binding, agent_key(argv) if argv else "claude",
                      restart.get("who") or "This agent")
    if restart is not None and argv and resumes(argv):
        if restart.get("bound") is None:
            raise Fail(NO_BINDING.format(who=restart.get("who") or "This agent"))
        plan = plan_of_record(restart["bound"], binding, agent_key(argv), restart.get("who") or "This agent")
        if plan["route"] != PERSONAL and machine:
            raise Fail(NOT_EXECUTION_HOST.format(machine))
        compose(plan, argv)
        return plan
    if binding["route"] == PERSONAL:
        return launch_plan(agent_key(argv) if argv else "claude", binding)
    if tab:
        raise Fail(TAB_PERSONAL)
    if machine:
        raise Fail(NOT_EXECUTION_HOST.format(machine))
    if argv is None:
        raise Fail(RESTART_HELD)
    plan = launch_plan(agent_key(argv), binding, "coordinator", deployment)
    compose(plan, argv)
    return plan


# What can outrank a plan on the execution host, so a plan shown here is never said to be what
# will run. Each layer's evidence stays apart: official documentation, installed or pinned version
# evidence, parser or source inference, and what is unknown. None is read here: only whether
# Claude's managed settings file is at a documented path.
MANAGED_SETTINGS = ("/Library/Application Support/ClaudeCode/managed-settings.json", "/etc/claude-code/managed-settings.json")
PRECEDENCE = {
    "claude": [
        {"layer": "Claude apps gateway sign-in",
         "effect": "a signed-in gateway session authenticates with the gateway's token even when CLAUDE_CODE_USE_FOUNDRY is set",
         "evidence": "official docs as reviewed for A1 (PR 17), Claude Code 2.1.318 installed then; not re-read here",
         "observed": "unknown: whether the execution host has such a session is not checked"},
        {"layer": "Claude managed settings",
         "effect": "outrank --settings, its env included; allowedProviders can refuse a provider, and --model picks only from allowed models",
         "evidence": "official docs as reviewed for A1 (PR 17), Claude Code 2.1.318 installed then; not re-read here",
         "observed": None},
    ],
    "codex": [
        {"layer": "Codex required_model_provider()",
         "effect": "resolves ahead of the other provider sources, the plan's -c model_provider included",
         "evidence": "source inference: the Codex 0.166.0 tag read through summarised fetches; Microsoft's guide validated only 0.152.1, 0.153.0 and 0.155.1",
         "observed": "unknown: not checked"},
    ],
}


def precedence(kind):
    """The layers that can outrank kind's plan, each with its evidence and what is seen of it here."""
    rows = [dict(r) for r in PRECEDENCE.get(kind, [])]
    for r in rows:
        if r["observed"] is None:
            there = [p for p in MANAGED_SETTINGS if os.path.exists(p)]
            r["observed"] = (f"a managed settings file is there ({there[0]}): it may change or refuse this plan" if there
                             else "no file at the documented paths; MDM and other managed sources are not checked")
    return rows


def selection_view(binding, role):
    """What a new-start selector shows for role (`provider show`): the route, and per CLI its routing in words, the
    deployment a new start takes now (checked; "" when unset or not one) and the revision a choice made now is bound
    to. Never refuses an incomplete Azure setup: the selector says what is missing instead."""
    out = {"route": binding["route"], "role": role, "clis": {}}
    for kind in KINDS:
        try:
            dep = clean(f"{kind}_deployment", role_deployment(binding, kind, role) or "")
        except Fail:
            dep = ""
        try:
            launch_plan(kind, binding, role)
            problem = None
        except Fail as e:
            problem = str(e)
        out["clis"][kind] = {"routing": binding_words(binding, kind), "deployment": dep if binding["route"] == AZURE else None,
                             "revision": selection_revision(binding, kind), "problem": problem}
    return out


def cmd_provider(args):
    """`provider plan`: the launch plan for one CLI under this folder's settings; `provider show`: what a new-start
    selector shows. Both read-only: they start nothing, sign in nowhere, read no credential and don't say one is
    there."""
    from .store import locate
    space = bare(args.space) if args.space else None
    d = read_strict()
    # A space the settings file holds is read by its own entry's folder, as launch admission reads it (space_scope),
    # so a shell or folder below its top can't answer for another layer.
    entry = d.get("spaces", {}).get(space) if space and isinstance(d.get("spaces"), dict) else None
    folder = entry.get("folder") if isinstance(entry, dict) and isinstance(entry.get("folder"), str) and entry.get("folder") else None
    s = types.SimpleNamespace(loc={"folder": folder} if folder else locate(args.folder))
    binding = binding_for(s, space, d)
    role = getattr(args, "role", None) or "worker"
    if role not in ROLES:
        raise Fail("--role is worker or coordinator.")
    if args.provider == "show":
        out = selection_view(binding, role)
        if getattr(args, "json", False):
            print(json.dumps(out))
            return
        print("\n".join([f"{role}: {'Azure Foundry' if out['route'] == AZURE else 'Personal'}."] +
                        [f"{k}: {c['routing']}" + (f", deployment {c['deployment'] or '(not set)'}" if c["deployment"] is not None else "")
                         + (f". {c['problem']}" if c["problem"] else "") for k, c in out["clis"].items()]))
        return
    if not args.agent and not args.argv:
        raise Fail("Which CLI? Pass --agent claude or --agent codex.")
    try:
        base = agent_argv(args.agent, args.argv)
    except ValueError:
        raise Fail("--argv must be a JSON list")
    kind = agent_key(base)
    if args.agent and kind != args.agent:
        raise Fail(f"--argv starts {kind}, not {args.agent}.")
    plan = launch_plan(kind, binding, role, getattr(args, "deployment", None))
    argv, env = compose(plan, base)
    azure = plan["route"] == AZURE
    out = {**plan, "argv": argv, "env": env, "dispatch": "planned" if azure else "pass-through",
           "revision": selection_revision(binding, kind),
           "pending": ["fork (a window tab can't carry a plan)", "native qualification"] if azure else [],
           **({"outranked_by": precedence(kind)} if azure else {})}
    if getattr(args, "json", False):
        print(json.dumps(out))
        return
    if not azure:
        print(f"{kind}: Personal. Its own configuration and sign-in, unchanged; nothing is added to its launch.")
        return
    how = f"the {plan['credential']} variable on the execution host (its value is never read here)" if plan["credential"] else \
        "the Azure SDK's default credential chain on the execution host (an az login, say)"
    print("\n".join([
        f"{kind}: Azure Foundry, deployment {plan['deployment']}, {AUTH_WORDS[plan['auth']]}.",
        f"Signs in with {how}.",
        f"Binding {plan['fingerprint'][:12]} (CLI, endpoint or resource, deployment and method; not an account).",
        "A task's start and an Assistant's new start use this plan and record its binding; a resume keeps the recorded "
        "one, and so do a restart and a revival that continue it (L2). A fork stays Personal only, and native "
        "qualification is pending.",
        *[f"Can be outranked by {r['layer']}: {r['effect']} ({r['observed']})." for r in precedence(kind)],
        "This is a plan, not a check: no sign-in, credential or model request was tried. --json shows its argv and env."]))
