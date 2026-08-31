"""Connection helper shared by the CLI and the probe.

Credentials come from the environment (or a .env file next to the project):

    ROUTER_HOST   default 192.168.50.1
    ROUTER_USER   default admin
    ROUTER_PASS   required
    ROUTER_SSL    default false
    ROUTER_PORT   optional
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

from asusrouter import AsusData, AsusRouter


class ConfigError(RuntimeError):
    """Raised when the router credentials are missing or unusable."""


@dataclasses.dataclass(frozen=True)
class RouterConfig:
    """Everything needed to reach the router."""

    host: str
    username: str
    password: str
    use_ssl: bool
    port: int | None

    @property
    def url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        suffix = f":{self.port}" if self.port else ""
        return f"{scheme}://{self.host}{suffix}"


def config_paths() -> list[Path]:
    """Candidate .env locations, most specific first.

    The CLI is normally installed globally (`uv tool install .`) and then run
    from whatever directory the user or agent happens to be in, so a bare
    load_dotenv() on the working directory is not enough.
    """
    paths = []
    if override := os.getenv("ASUS_ENV_FILE"):
        paths.append(Path(override).expanduser())
    paths.append(Path.cwd() / ".env")
    paths.append(Path.home() / ".config" / "asus-skill" / ".env")
    # Legacy location from before the project was renamed to asus-skill.
    paths.append(Path.home() / ".config" / "asus-router" / ".env")
    return paths


def load_config() -> RouterConfig:
    """Read the router configuration from the environment."""
    for path in config_paths():
        if path.is_file():
            load_dotenv(path)
            break

    password = os.getenv("ROUTER_PASS")
    if not password:
        searched = "\n  ".join(str(p) for p in config_paths())
        raise ConfigError(
            "ROUTER_PASS is not set. Create a config file at one of:\n  "
            + searched
            + "\n\nStart from env.example in the repository."
        )

    port = os.getenv("ROUTER_PORT")
    return RouterConfig(
        host=os.getenv("ROUTER_HOST", "192.168.50.1"),
        username=os.getenv("ROUTER_USER", "admin"),
        password=password,
        use_ssl=os.getenv("ROUTER_SSL", "false").lower() in {"1", "true", "yes"},
        port=int(port) if port else None,
    )


@asynccontextmanager
async def connect(config: RouterConfig | None = None) -> AsyncIterator[AsusRouter]:
    """Open an authenticated session and always close it again."""
    config = config or load_config()

    async with aiohttp.ClientSession() as session:
        router = AsusRouter(
            hostname=config.host,
            username=config.username,
            password=config.password,
            port=config.port,
            use_ssl=config.use_ssl,
            session=session,
        )
        if not await router.async_connect():
            raise ConfigError(f"Login refused by {config.url}. Check ROUTER_USER/ROUTER_PASS.")
        try:
            yield router
        finally:
            await router.async_disconnect()


async def read_nvram(router: AsusRouter, names: list[str]) -> dict[str, Any]:
    """Read raw nvram variables over the HTTP API.

    This is the same mechanism the library uses to collect device identity
    (see asusrouter/modules/identity.py::collect_identity), exposed here as
    an escape hatch for settings that have no dedicated data type.
    """
    from asusrouter.tools import writers  # local import: internal helper

    request = writers.nvram(names)
    if not request:
        return {}
    return await router.async_api_hook(request)


async def port_forwarding_rules(router: AsusRouter) -> list[Any]:
    """Return the current port forwarding rules.

    The library omits the "rules" key entirely when vts_rulelist is empty
    (asusrouter/modules/endpoint/hook.py::process_port_forwarding), so a
    plain ["rules"] lookup raises KeyError on a router with no rules.
    """
    data = await router.async_get_data(AsusData.PORT_FORWARDING) or {}
    return list(data.get("rules") or [])


def jsonable(value: Any) -> Any:
    """Convert library objects into something json.dumps can handle."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def enum_name(value: Any) -> str:
    """Render an IntEnum as its name rather than a bare number."""
    return value.name if isinstance(value, Enum) else str(value)


async def apply_nvram(
    router: AsusRouter,
    values: dict[str, str],
    service: str,
) -> dict[str, Any]:
    """Write nvram variables, restart a service, and report what actually stuck.

    This is the same write path the library uses for port forwarding
    (async_apply_port_forwarding_rules -> async_run_service): the arguments
    dict becomes nvram assignments, `apply` adds action_mode=apply, and the
    named service is restarted afterwards.

    Some variables are read-only on stock firmware even though the write is
    accepted — country code is the known case — so the values are read back
    and returned as before/after rather than trusting the success flag.
    """
    names = list(values)
    before = await read_nvram(router, names)
    ok = await router.async_run_service(service=service, arguments=dict(values), apply=True)
    after = await read_nvram(router, names)

    return {
        "ok": ok,
        "before": before,
        "after": after,
        "unchanged": [n for n in names if str(after.get(n)) != str(values[n])],
    }
