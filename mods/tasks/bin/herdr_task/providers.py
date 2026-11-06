"""Provider bindings and launch plans: Personal (the default: the CLI's own configuration and
sign-in, untouched) or Azure Foundry, from nonsecret settings alone.

This module never reads a credential. A plan names the variable the CLI itself reads on the
execution host (ANTHROPIC_FOUNDRY_API_KEY, ANTHROPIC_FOUNDRY_AUTH_TOKEN, AZURE_OPENAI_API_KEY);
its value stays in that host's environment and never enters argv, settings, labels or records.
A binding's fingerprint covers its CLI, endpoint or resource, deployment and authentication
method: it does not attest an account, and rotating a credential doesn't change it.

The supported combinations are the four in docs/azure-launch-plans.md, each from the official
contract for the inspected CLI version; anything else is refused. In this source checkpoint a
valid Azure plan is still not dispatched: launch admission and bound resume are later migration
phases (docs/migration/upstream-v3.1.3.md, A2 and L1), so admit_launch() refuses it before any
effect, and `herdr-task provider plan` only shows it."""

import hashlib
import json
import re
import types

from .base import Fail
from .settings import agent_argv, agent_key, bare, read_settings, settings_layers


PERSONAL, AZURE = "personal", "azure-foundry"
KINDS = ("claude", "codex")
# Settings' "provider" section (Everywhere, this machine, the folder's space: the most specific
# wins, field by field). Only these names, each text: a field it doesn't know is refused, so a key
# or token put there by mistake is never read as configuration. That rule holds on every route,
# Personal too (settings are copied between machines, so a secret there is said, not started
# past); with no "provider" section at all nothing is checked. azure_subscription is discovery's only.
FIELDS = ("route", "azure_subscription", "claude_resource", "claude_deployment", "claude_auth",
          "codex_endpoint", "codex_deployment", "codex_auth")
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
HELD = ("Azure Foundry is set for {}, and its launch plan is valid, but this version only plans it: starting or resuming an "
        "agent on Azure waits for launch admission and bound resume (still pending). Nothing was started or changed. "
        "`herdr-task provider plan --agent {}` shows the plan; set Provider to Personal to start on the CLI's own sign-in.")


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
    elif field in ("claude_deployment", "codex_deployment"):
        if not DEPLOYMENT.fullmatch(v):
            raise Fail(NO_DEPLOYMENT.format("Claude Code" if field.startswith("claude") else "Codex"))
    elif field == "claude_auth":
        if v not in CLAUDE_AUTH:
            raise Fail(NO_CLAUDE_AUTH)
    elif field == "codex_auth":
        if v not in CODEX_AUTH:
            raise Fail(NO_CODEX_AUTH)
    else:
        raise Fail(NO_FIELD)
    return v


def binding_for(s, space=None):
    """The nonsecret provider binding for this folder's launches: Everywhere's, then this
    machine's, then the space's own "provider" fields; a field a layer leaves out (or null) follows
    the layer above, and "" there is its own empty value. With no route anywhere: Personal.
    "local" is False for a copy the settings window or the service pushed to this machine
    ("pushed_from"). It is not a full local-only guard: a Serve-from host's file is its own, so launch admission (L1) must
    bind the execution machine before any Azure dispatch."""
    out = {f: "" for f in FIELDS}
    for layer in settings_layers(s, space):
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
    out["local"] = not read_settings().get("pushed_from")
    return out


def fingerprint(kind, target, deployment, auth):
    """The binding's nonsecret identity: what a conversation started on it is bound to."""
    return hashlib.sha256(json.dumps([kind, target, deployment, AUTH_WORDS[auth]], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def launch_plan(kind, binding):
    """How one CLI is routed, from the binding alone: {route, agent, fingerprint, deployment, auth,
    credential (a variable's name, or None), settings_env (Claude Code's --settings env),
    args (Codex's -c overrides), env (nonsecret process variables)}. Personal changes nothing.
    An unsupported or incomplete combination is refused, with what to set."""
    if binding["route"] == PERSONAL:
        return {"route": PERSONAL, "agent": kind, "fingerprint": PERSONAL, "deployment": None, "auth": None, "credential": None,
                "settings_env": {}, "args": [], "env": {}}
    if kind not in KINDS:
        raise Fail(NO_KIND.format(kind))
    if not binding.get("local", True):
        raise Fail(NOT_LOCAL)
    name = "Claude Code" if kind == "claude" else "Codex"
    deployment = clean(f"{kind}_deployment", binding[f"{kind}_deployment"])
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
        plan.update(fingerprint=fingerprint(kind, resource, deployment, auth), auth=auth, credential=credential, settings_env=env)
        return plan
    endpoint = clean("codex_endpoint", binding["codex_endpoint"])
    if not endpoint:
        raise Fail(NO_ENDPOINT)
    auth = clean("codex_auth", binding["codex_auth"]) or "api-key"
    credential = CODEX_AUTH[auth]
    mark = fingerprint(kind, endpoint, deployment, auth)
    ident = CODEX_PROVIDER + mark
    table = {"name": "Azure Foundry", "base_url": endpoint, "env_key": credential, "wire_api": "responses", "requires_openai_auth": False}
    plan.update(fingerprint=mark, auth=auth, credential=credential,
                args=["-c", f"model_provider={json.dumps(ident)}",
                      "-c", f"model_providers.{ident}={{{','.join(f'{k}={json.dumps(v)}' for k, v in table.items())}}}"],
                env={"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""})
    return plan


# Where an argv's options end: at its first bare "--" (the words from it on are the CLI's
# operands, never options), else at its end.
def options_end(argv):
    return argv.index("--", 1) if "--" in argv[1:] else len(argv)


def with_model(argv, flags, flag, model):
    """argv selecting `model` and no other: its first model selection keeps its place with the
    model as its value, every later one is dropped, and with none the flag is added. A selection
    is a flag and the word after it, `--flag=value`, or a one-letter flag with its value attached
    (`-mvalue`, `-m=value`: kept as the flag and the model, two words). A flag with no value of
    its own (it is the last option, or the next word is another option) takes the model and the
    next word stays. Words from a bare "--" on are the CLI's operands, not options: left as they
    are."""
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
        # A bare "--" may be another option's value, and then a --settings or --model after it
        # is a real option that could reroute the launch or carry a credential; read as one when
        # it is an operand, it would stand in for the plan's own. Neither reading is safe: refused,
        # and no word of the argv is repeated.
        if any(a in ("--settings", "--model") or a.startswith(("--settings=", "--model=")) for a in out[end:]):
            raise Fail(NO_OPTION_AFTER_DASHES)
        # Only the options below: any other word from the "--" on is left as an operand, and the
        # plan's own --settings goes in front.
        if any(a.startswith("--settings=") for a in out[1:end]):
            raise Fail("On Azure Foundry, give Claude Code's --settings as a separate JSON word. Nothing was started.")
        if out[1:end].count("--settings") > 1:
            raise Fail("On Azure Foundry, give Claude Code one --settings word. Nothing was started.")
        if "--settings" in out[1:min(end, len(out) - 1)]:
            i = out.index("--settings", 1)
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


def admit_launch(s, argv, space=None):
    """Before any launch effect (a worktree, a task's state, a terminal): Personal passes, as it
    always did. An Azure binding is checked whole, so an unsupported one says what is wrong, and
    a valid one is held: this version plans Azure launches and doesn't dispatch them."""
    binding = binding_for(s, space)
    if binding["route"] == PERSONAL:
        return
    kind = agent_key(argv)
    compose(launch_plan(kind, binding), argv)
    raise Fail(HELD.format("Claude Code" if kind == "claude" else "Codex", kind))


def cmd_provider(args):
    """`provider plan`: the launch plan for one CLI under this folder's settings, read-only. It
    starts nothing, signs in nowhere, reads no credential and doesn't say one is there."""
    from .store import locate
    s = types.SimpleNamespace(loc=locate(args.folder))
    binding = binding_for(s, bare(args.space) if args.space else None)
    if not args.agent and not args.argv:
        raise Fail("Which CLI? Pass --agent claude or --agent codex.")
    try:
        base = agent_argv(args.agent, args.argv)
    except ValueError:
        raise Fail("--argv must be a JSON list")
    kind = agent_key(base)
    if args.agent and kind != args.agent:
        raise Fail(f"--argv starts {kind}, not {args.agent}.")
    plan = launch_plan(kind, binding)
    argv, env = compose(plan, base)
    azure = plan["route"] == AZURE
    out = {**plan, "argv": argv, "env": env, "dispatch": "held" if azure else "pass-through",
           "pending": ["launch admission", "bound resume", "settings and selectors", "native qualification"] if azure else []}
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
        "Dispatch is held in this version: launch admission, bound resume, settings and selectors, and native qualification are pending.",
        "This is a plan, not a check: no sign-in, credential or model request was tried. --json shows its argv and env."]))
