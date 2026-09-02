# Roadmap

Things deliberately left out, and what would have to be true to add them.

## Streamable HTTP transport for the MCP server

The server speaks stdio only. That is the right default here: the router is a
LAN device, and the credential the server holds is the router's **admin
password**. stdio means the server runs as a child of the agent that uses it,
on the same machine, reachable by nothing else.

HTTP would let a hosted agent reach the router — a real use, and the only
reason to want it. It would also raise three questions stdio never asks:

- **Who may connect.** An HTTP endpoint is reachable by everything on the
  network segment it binds to, not just the agent you meant.
- **What authenticates.** MCP's own auth story would have to sit in front of
  admin-password-equivalent access, and a bearer token stored somewhere is a
  second credential to lose.
- **Which interface to bind.** Loopback is safe and pointless for a remote
  agent; anything wider needs the first two answered first.

None of that is hard, and all of it is wasted work without a concrete use
case. When there is one — a specific host that cannot spawn a subprocess —
answer the three questions against *that* host and implement it.

## Writes enabled by default

Today the MCP server registers its 12 read tools always, its 8 write tools
only under `ASUSWRT_MCP_ALLOW_WRITES=1`, and `reboot_router` /
`upgrade_firmware` only when `ASUSWRT_MCP_ALLOW_DANGEROUS=1` is also set. The
default install can look at the router and cannot change it.

Shipping writes on by default would need all of:

- **A host-side approval step that can be relied on.** The MCP spec says tool
  annotations are *hints*; a host may auto-approve `destructive_hint=true`. The
  server's `confirm: bool` two-step exists precisely because the host's dialog
  cannot be assumed. Enabling writes by default means trusting something the
  spec does not promise.
- **A recorded reason to.** The gate costs one environment variable, set once.
  Nobody has yet been slowed down by it.
- **Evidence the preview text is good enough to act on.** The preview is the
  only thing standing between an agent and a config change. It has not been
  exercised against real misuse.

Until then the default stays read-only, which is the setting that cannot go
wrong unattended.
