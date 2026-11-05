# Private custom domains

This is an opt-in HTTPS listener for a domain you control. It authenticates the
actual TCP peer with the local Tailscale daemon. Existing Tailscale Serve and
local token access retain their defaults. No Cloudflare Tunnel, Funnel, public
listener, header rewriting or shared bearer token is involved.

The listener uses the service's existing request and WebSocket handlers. It
admits only devices owned by the same Tailscale login as the serving machine.
Tagged devices have no human-owner grant and are refused. This is device-owner
authentication, as with native Tailscale Serve; it does not identify the person
or local OS account using an admitted device.

## Configuration

Set `SHEPHERDR_PRIVATE_DOMAIN` in the service's execution environment to a local
JSON file. An unset variable creates no listener and performs no extra lookups.
Keep this file outside synchronized application settings:

```json
{
  "origin": "https://board.example.com",
  "bind": "100.64.0.10",
  "certificate": "/private/tls/fullchain.pem",
  "key": "/private/tls/key.pem"
}
```

Use your own domain and the serving machine's exact Tailscale address. A port
in the origin, such as `https://board.example.com:8443`, selects that TLS port.
`tailscale` optionally names an execution-host CLI path; its default is the
installed `tailscale` command. Other fields are rejected.

Before listening, the module requires a running, online, untagged local node
owned by the service's Tailscale login and containing the configured bind
address. Wildcard and loopback configuration is refused. The certificate must
be current, match the DNS name and match the key. Key permissions must exclude
group and other access. Certificate/private-key contents are never settings or
command arguments. Errors omit CLI output and certificate contents.

Use an external ACME owner for a publicly trusted certificate. DNS-01 can issue
one while the application remains private. Do not put Cloudflare credentials
in this configuration or in Shepherdr settings. Certificate issuance, renewal
and loading renewed files are operational prerequisites, not implemented by
this module. Restarting an admitted instance loads its renewed files.

## Authentication and request scope

Each admission checks local Tailscale status and `tailscale whois --json` for
the actual socket address. Evidence must identify that exact address, have no
node tags and name the current machine owner's login. Lookups time out after
three seconds. Only concurrent lookups coalesce; completed grants are not cached.
A changed owner during lookup is refused. Browser-supplied identity, forwarded
address and authorization headers do not grant private-listener access.

The request Host must equal the configured HTTPS authority. Writes require
that exact Origin and `x-shepherdr: 1`; WebSocket upgrades require the same
Origin. Cross-site and preflight requests retain the native refusal. Opening
the URL directly from the address bar is supported; a cross-site redirect can
be refused. The Web add-on switch and Serve-from ownership still apply.

An unavailable private listener reports a sanitized startup error and leaves
the ordinary loopback service running. No successful startup is claimed for
the custom URL. A configuration syntax error stops startup before app state
initialization. Native Settings > Web and notification links continue to show
the original Tailscale route; `/api/me` on the custom listener reports its own
link.

## DNS and port ownership

Private clients must resolve the custom hostname to the configured Tailscale
address. A Cloudflare DNS-only record can provide that answer; its orange-cloud
proxy cannot reach a tailnet-only origin or supply a caller's Tailscale identity.
Preserve any existing hostname owner until a separately approved cutover.

Reserve the port first. Tailscale Serve may already own port 443. Use an
unoccupied port for proof. Moving an existing Serve mapping, changing DNS,
installing certificates or trust, and replacing a runtime are separate effects.
This module does not perform them. A trusted certificate does not prove DNS,
private reachability or ownership admission.

## Qualification and reversal

CI exercises the production TLS listener and gate with an isolated loopback
socket, an ephemeral test CA, a fixture Tailscale executable and real WebSocket
upgrades. It checks owner/other/tagged/unresolved callers, spoofed headers,
Host/Origin/CSRF failures, stopped Tailscale, changed ownership and key/bind
preflight. The fixture does not establish live Tailscale or browser readiness.

`scripts/private-domain-proof.ts` starts only this listener with a read-only
proof handler and the real execution-host Tailscale CLI. It imports no app
initialization, scheduler, settings, task store or core. Run an admitted proof:

```sh
caffeinate -dimsu bun scripts/private-domain-proof.ts /private/proof/config.json
```

Use the real custom hostname and an unused port with `curl --resolve` against
the actual Tailscale address. Use a certificate chain the client trusts; a
test CA supplied explicitly to curl proves TLS mechanics, not public browser
trust. Check owner reads, writes, a WebSocket upgrade, refused Host/Origin,
and a real tagged-node refusal. Stop only the proof PID, verify its listener
closed and recheck the original route. Keep raw proof outside source.

The full fork remains subject to its migration qualification and deployment
holds. A passing transport proof is not a deployed custom-domain application.
To reverse an activated custom listener, remove its opt-in configuration and
restart only the separately admitted instance. Restore the exact prior DNS and
Serve mappings through their owners. No task or conversation conversion is needed.

## Sources

- [Tailscale Serve identity and DNS limits](https://tailscale.com/docs/features/tailscale-serve)
- [Official whois implementation](https://github.com/tailscale/tailscale/blob/main/cmd/tailscale/cli/whois.go)
- [Bun TLS](https://bun.com/docs/runtime/http/tls)
