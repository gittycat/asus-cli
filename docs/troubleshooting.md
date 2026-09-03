# Troubleshooting

## `No route to host` when the router is up

**Status: unresolved.** Recorded here so the next occurrence can be diagnosed
rather than re-guessed.

### What was seen (2026-09-03, macOS Darwin 27.0.0, RT-AX59U at 192.168.50.1)

`asuswrt clients` failed with:

```
Cannot connect to host 192.168.50.1:80 ssl:False [No route to host]
```

while, from the same shell and seconds apart:

| Probe | Result |
|---|---|
| `ping -c 2 192.168.50.1` | 0% packet loss |
| `nc -z 192.168.50.1 80` | succeeded |
| `curl http://192.168.50.1/` | HTTP 200 |
| `python -c "socket.connect(('192.168.50.1', 80))"` | `OSError [Errno 65] No route to host` |

The failing interpreter was
`~/.local/share/uv/python/cpython-3.13.0-macos-aarch64-none/bin/python3.13`.

It later started working with **no configuration change and no permission
granted**. `uv tool install --reinstall` was run in between, but it reused the
same CPython at the same path, so no new binary was introduced.

### Two candidate causes, neither confirmed

1. **macOS Local Network privacy.** macOS gates local network access, and a
   denied program gets EHOSTUNREACH — the same errno as an absent router.
   *Fits:* curl (approved) working while Python failed at the same moment.
   *Does not fit:* the same binary at the same path later succeeded without
   anyone approving anything.

2. **Stale ARP / neighbour entry.** For a host on your own subnet, failed
   resolution makes the kernel install a reject route, which returns
   EHOSTUNREACH instantly. `ping` and `nc` were run before the first success
   and would have forced resolution.
   *Fits:* the instant failure, the recovery, and `arp -n 192.168.50.1`
   showing no entry with `!` (RTF_REJECT) on the subnet routes afterwards.
   *Does not fit:* curl succeeding while Python failed in the same instant.

### What to capture next time, before running anything else

The diagnosis failed last time because the state was destroyed by the probes.
Run this **first**, while it is still broken:

```bash
arp -an | grep "$(route -n get default | awk '/gateway/{print $2}')"
netstat -rn -f inet | head -12          # look for ! (RTF_REJECT) on the subnet
log show --last 5m --predicate 'subsystem == "com.apple.network"' --style compact
```

Then, in this order, testing after each step:

1. Retry the same command unchanged — if it now works, cause 2 is likely.
2. `curl -sS -o /dev/null -w '%{http_code}\n' http://<gateway>/` — a 200 while
   Python still fails points at cause 1.
3. Check System Settings > Privacy & Security > Local Network for an entry
   naming the interpreter or the terminal, and note whether it was already on.

`explain_router_error()` in `src/asuswrt/router.py` prints both causes and the
curl comparison. Do not narrow that message to one cause without evidence from
the checks above.
