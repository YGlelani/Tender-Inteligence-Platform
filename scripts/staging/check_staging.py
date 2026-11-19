#!/usr/bin/env python3
"""Static safety checks for the staging stack (compose.staging.yaml).

Proves, without starting anything, that staging cannot collide with or reach production:
container names, host ports, networks, volumes, image tags, Redis, databases, the
addresses services use to reach each other, and the addresses the browser sites use.
It also checks the staging settings file (required values, placeholders, reuse of
production values) and that every Dockerfile the stack builds exists with its COPY sources.

Usage:
    python scripts/staging/check_staging.py --env-file .env.staging
    python scripts/staging/check_staging.py --env-file .env.staging.example --allow-placeholders   (CI)
    python scripts/staging/check_staging.py --env-file .env.staging --production-env Signup-api/.env alerts-api/.env
        (on the server: fails if any staging secret equals a production value)

Exit code 0 = no errors (warnings are printed but allowed), 1 = errors.
Needs PyYAML (pip install pyyaml). Reads files only; never contacts Docker or a server.
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("check_staging.py needs PyYAML: python -m pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]
STAGING_FILE = "compose.staging.yaml"
STAGING_PROJECT = "tender-staging"
# The production Compose files, deployed today from the individual service repositories.
PRODUCTION_FILES = [
    "tender-scrapping-database/compose.yaml",
    "tender-ai-agent/compose.yaml",
    "Signup-api/compose.yaml",
    "alerts-api/compose.yaml",
    "jwt/compose.yml",
    "tender_apis/compose.yaml",
    "tender-ml/compose.yaml",
    "frontend/compose.yaml",
    "tender-ai-frontend/docker-compose.yml",
]
# Production ports of services that live outside this repository (scripts/config.js),
# plus the port USER_SERVER_PORT is set to for the main site and the old PostgreSQL port.
PRODUCTION_PORTS_OUTSIDE_REPO = {8005: "overview API", 8008: "signup site", 8009: "main site (USER_SERVER_PORT)",
                                 9002: "business profile API", 9006: "application tracker API",
                                 9008: "saved tenders API", 9009: "tender search API", 5433: "PostgreSQL"}
SECRET_VARS = ["STAGING_JWT_SECRET", "STAGING_INTERNAL_API_KEY", "STAGING_ACCOUNT_DELETION_KEY",
               "STAGING_AI_SERVICE_API_KEY", "STAGING_SCRAPER_API_KEY"]
OPTIONAL_SECRET_VARS = ["STAGING_AZURE_AI_API_KEY", "STAGING_AZURE_EMBED_API_KEY", "STAGING_SMTP_PASSWORD",
                        "STAGING_AGENT_ADMIN_KEY"]
PLACEHOLDERS = {"", "change-me", "changeme", "replace-me", "todo", "xxx"}
ALLOWED_IMAGES_WITHOUT_BUILD = {"redis", "ollama/ollama"}
# Public third-party addresses staging may call.
ALLOWED_EXTERNAL_HOSTS = {"www.etenders.gov.za", "etenders.gov.za"}
# Settings that hold an address browsers or e-mails use (must be USER_SERVER_IP + a staging port).
PUBLIC_URL_KEYS = {"EMAIL_CONFIRMATION_URL", "LOGIN_URL", "APP_URL", "PUBLIC_API_URL", "AGENT_URL"}
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")

errors: list[str] = []
warnings: list[str] = []


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def fail(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# --------------------------------------------------------------------------- env files
def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


# --------------------------------------------------------------------------- interpolation
class Interpolator:
    """Compose-style ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?error}, ${VAR?error}, $$."""

    def __init__(self, env: dict[str, str]):
        self.env = env
        self.missing: list[str] = []

    def __call__(self, text: str) -> str:
        out, i = [], 0
        while i < len(text):
            if text.startswith("$$", i):
                out.append("$")
                i += 2
            elif text.startswith("${", i):
                end = self._closing(text, i + 2)
                out.append(self._expand(text[i + 2:end]))
                i = end + 1
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    @staticmethod
    def _closing(text: str, start: int) -> int:
        depth, i = 1, start
        while i < len(text):
            if text.startswith("${", i):
                depth, i = depth + 1, i + 2
                continue
            if text[i] == "}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise ValueError("unclosed ${ in: " + text)

    def _expand(self, expr: str) -> str:
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(:?[-?])?(.*)$", expr, re.S)
        if not m:
            raise ValueError("bad variable reference: ${" + expr + "}")
        name, op, arg = m.group(1), m.group(2), m.group(3)
        value = self.env.get(name)
        unset_or_empty = value is None or (op is not None and op.startswith(":") and value == "")
        if op in (":-", "-"):
            return self(arg) if unset_or_empty else value
        if op in (":?", "?"):
            if unset_or_empty:
                self.missing.append(self(arg) or f"{name} is required")
                return ""
            return value
        return value or ""

    def walk(self, node):
        if isinstance(node, str):
            return self(node)
        if isinstance(node, list):
            return [self.walk(v) for v in node]
        if isinstance(node, dict):
            return {k: self.walk(v) for k, v in node.items()}
        return node


def load_compose(path: Path, env: dict[str, str]) -> tuple[dict, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    interp = Interpolator(env)
    return interp.walk(data), interp.missing


def published_ports(service: dict) -> list[int]:
    ports = []
    for entry in service.get("ports") or []:
        if isinstance(entry, dict):
            if entry.get("published"):
                ports.append(int(str(entry["published"]).split("-")[0]))
            continue
        parts = str(entry).split("/")[0].split(":")
        if len(parts) >= 2 and parts[-2]:
            ports.append(int(parts[-2].split("-")[0]))
    return ports


def env_map(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return {k: "" if v is None else str(v) for k, v in env.items()}


# --------------------------------------------------------------------------- production
def production_inventory() -> tuple[dict[int, str], set[str], set[str], set[str], set[str]]:
    """Ports, container names, network names, volume names and images used by production."""
    # Interpolate with no variables set, i.e. the production defaults.
    ports: dict[int, str] = {}
    names, networks, volumes, images = set(), set(), set(), set()
    for rel in PRODUCTION_FILES:
        path = ROOT / rel
        if not path.exists():
            warn(f"production Compose file not found: {rel}")
            continue
        data, _ = load_compose(path, {})
        project = data.get("name") or path.parent.name.lower()
        for svc_name, svc in (data.get("services") or {}).items():
            for p in published_ports(svc):
                ports.setdefault(p, f"{rel} ({svc_name})")
            names.add(svc.get("container_name") or f"{project}-{svc_name}-1")
            if svc.get("image"):
                images.add(svc["image"])
        for key, net in (data.get("networks") or {}).items():
            net = net or {}
            networks.add(net.get("name") or f"{project}_{key}")
        for key, vol in (data.get("volumes") or {}).items():
            vol = vol or {}
            volumes.add(vol.get("name") or f"{project}_{key}")
    for port, what in PRODUCTION_PORTS_OUTSIDE_REPO.items():
        ports.setdefault(port, what)
    return ports, names, networks, volumes, images


def frontend_service_names() -> set[str]:
    """Service names in frontend/scripts/config.js that are built from SERVER_ORIGIN + a port."""
    text = (ROOT / "frontend" / "scripts" / "config.js").read_text(encoding="utf-8")
    block = re.search(r"services:\s*\{(.*?)\n\s*\}", text, re.S)
    if not block:
        fail("could not find the services list in frontend/scripts/config.js")
        return set()
    return set(re.findall(r"^\s*(\w+):\s*`\$\{SERVER_ORIGIN\}:\d+", block.group(1), re.M))


# --------------------------------------------------------------------------- Dockerfiles
def check_build(svc_name: str, build) -> None:
    if isinstance(build, str):
        build = {"context": build}
    context = (ROOT / build.get("context", ".")).resolve()
    if not context.is_dir():
        fail(f"{svc_name}: build context does not exist: {build.get('context')}")
        return
    dockerfile = context / build.get("dockerfile", "Dockerfile")
    if not dockerfile.is_file():
        fail(f"{svc_name}: Dockerfile not found: {dockerfile.relative_to(ROOT)}")
        return
    ignored = set()
    dockerignore = context / ".dockerignore"
    if dockerignore.exists():
        ignored = {l.strip().rstrip("/") for l in dockerignore.read_text().splitlines() if l.strip() and not l.startswith("#")}
    text = dockerfile.read_text(encoding="utf-8").replace("\\\r\n", " ").replace("\\\n", " ")
    for line in text.splitlines():
        words = line.split()
        if not words or words[0].upper() not in ("COPY", "ADD"):
            continue
        args = [w for w in words[1:] if not w.startswith("--")]
        if any(w.startswith("--from") for w in words) or len(args) < 2 or args[0].startswith("["):
            continue
        for src in args[:-1]:
            if src in (".", "./") or "://" in src:
                continue
            if src.rstrip("/") in ignored:
                fail(f"{svc_name}: {dockerfile.relative_to(ROOT)} copies {src}, which .dockerignore excludes")
            elif not glob.glob(str(context / src)):
                fail(f"{svc_name}: {dockerfile.relative_to(ROOT)} copies {src}, which does not exist in {context.relative_to(ROOT)}")


# --------------------------------------------------------------------------- main checks
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=None, help="staging settings (default: .env.staging, else .env.staging.example)")
    parser.add_argument("--allow-placeholders", action="store_true", help="accept change-me values (CI with the example file)")
    parser.add_argument("--production-env", nargs="*", default=[], help="production .env files: staging must not reuse their values")
    parser.add_argument("--compose-file", default=STAGING_FILE, help=f"staging Compose file (default: {STAGING_FILE})")
    args = parser.parse_args()

    env_path = Path(args.env_file) if args.env_file else (ROOT / ".env.staging" if (ROOT / ".env.staging").exists() else ROOT / ".env.staging.example")
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()
    if not env_path.exists():
        print(f"FAIL settings file not found: {env_path}")
        return 1
    env = read_env_file(env_path)
    print(f"Settings file: {env_path}")

    staging_path = Path(args.compose_file)
    if not staging_path.is_absolute():
        staging_path = (ROOT / staging_path).resolve() if (ROOT / staging_path).exists() else (Path.cwd() / staging_path).resolve()
    raw_text = staging_path.read_text(encoding="utf-8")

    # 1. Only STAGING_* variables and USER_SERVER_IP may be read.
    for name in sorted(set(VAR_REF.findall(raw_text))):
        if not (name.startswith("STAGING_") or name == "USER_SERVER_IP"):
            fail(f"{STAGING_FILE} reads ${{{name}}}; staging may only read STAGING_* and USER_SERVER_IP")
    for key in env:
        if not (key.startswith("STAGING_") or key == "USER_SERVER_IP"):
            warn(f"{env_path.name} sets {key}, which compose.staging.yaml never reads")

    # 2. No hard-coded IPv4 addresses in staging files.
    staging_files = [staging_path, ROOT / ".env.staging.example", *sorted((ROOT / "scripts" / "staging").glob("*")),
                     ROOT / ".github" / "workflows" / "deploy-staging.yml"]
    for path in staging_files:
        if path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for ip in IPV4.findall(line):
                    if ip not in ("127.0.0.1", "0.0.0.0") and not ip.startswith("203.0.113."):  # 203.0.113.0/24 = documentation range
                        fail(f"{rel(path)}:{n} hard-codes the IP address {ip}; use USER_SERVER_IP")

    # 3. Settings file: required values, placeholders, strength, reuse.
    user_ip = env.get("USER_SERVER_IP", "")
    if user_ip.lower() in PLACEHOLDERS:
        (warn if args.allow_placeholders else fail)("USER_SERVER_IP is not set (use the staging server's IP or host name, or localhost)")
    seen: dict[str, str] = {}
    for name in SECRET_VARS + OPTIONAL_SECRET_VARS:
        value = env.get(name, "")
        required = name in SECRET_VARS
        if value.lower() in PLACEHOLDERS:
            if required:
                (warn if args.allow_placeholders else fail)(f"{name} is not set (generate one: openssl rand -hex 32)")
            continue
        if required and len(value) < 32:
            fail(f"{name} is shorter than 32 characters")
        if value in seen:
            warn(f"{name} has the same value as {seen[value]}; use a different value for each purpose")
        seen.setdefault(value, name)
    if not env.get("STAGING_AZURE_AI_ENDPOINT") or not env.get("STAGING_AZURE_AI_API_KEY"):
        warn("STAGING_AZURE_AI_ENDPOINT / STAGING_AZURE_AI_API_KEY are empty: the AI agent's chat will report 'degraded'")
    if not all(env.get(k) for k in ("STAGING_SMTP_HOST", "STAGING_SMTP_USERNAME", "STAGING_SMTP_PASSWORD", "STAGING_EMAIL_FROM")):
        warn("STAGING_SMTP_* / STAGING_EMAIL_FROM are incomplete: sign-up and password e-mails will fail in staging")
    for prod_file in args.production_env:
        prod_values = read_env_file(Path(prod_file))
        for name in SECRET_VARS + OPTIONAL_SECRET_VARS:
            value = env.get(name, "")
            if value and value.lower() not in PLACEHOLDERS:
                for prod_name, prod_value in prod_values.items():
                    if value == prod_value:
                        fail(f"{name} reuses a production value ({prod_name} in {prod_file}); staging needs its own secrets")

    # 4. Parse and interpolate the staging file the way Compose does.
    staging, missing = load_compose(staging_path, env)
    for msg in dict.fromkeys(missing):
        (warn if args.allow_placeholders else fail)(f"Compose would stop: {msg}")
    if staging.get("name") != STAGING_PROJECT:
        fail(f"{STAGING_FILE} must set 'name: {STAGING_PROJECT}' (got {staging.get('name')!r})")
    services = staging.get("services") or {}

    prod_ports, prod_names, prod_networks, prod_volumes, prod_images = production_inventory()
    project = staging.get("name", STAGING_PROJECT)

    # 5. Networks and volumes are staging's own.
    staging_networks = staging.get("networks") or {}
    for key, net in staging_networks.items():
        net = net or {}
        name = net.get("name") or f"{project}_{key}"
        if net.get("external"):
            fail(f"staging network '{key}' is external; staging must create its own network")
        if name in prod_networks:
            fail(f"staging network '{name}' is a production network")
    staging_volumes = staging.get("volumes") or {}
    for key, vol in staging_volumes.items():
        vol = vol or {}
        name = vol.get("name") or f"{project}_{key}"
        if vol.get("external"):
            fail(f"staging volume '{key}' is external; staging must create its own volumes")
        if name in prod_volumes:
            fail(f"staging volume '{name}' is a production volume")

    # 6. Per-service checks.
    service_hosts = set(services)
    for svc in services.values():
        for net in (svc.get("networks") or {}).values() if isinstance(svc.get("networks"), dict) else []:
            service_hosts.update((net or {}).get("aliases") or [])
    staging_ports: dict[int, str] = {}
    for svc_name, svc in services.items():
        if "container_name" in svc:
            fail(f"{svc_name}: container_name is set; staging containers must be named by the project ({project}-{svc_name}-1)")
        if f"{project}-{svc_name}-1" in prod_names:
            fail(f"{svc_name}: container name {project}-{svc_name}-1 is used by production")
        if "env_file" in svc:
            fail(f"{svc_name}: env_file is set; a production .env could leak into staging")
        if svc.get("network_mode"):
            fail(f"{svc_name}: network_mode is set; staging services must stay on the staging network")
        nets = svc.get("networks") or []
        for net in (nets if isinstance(nets, list) else list(nets)):
            if net not in staging_networks:
                fail(f"{svc_name}: uses network '{net}', which is not a staging network")
        image = svc.get("image", "")
        if svc.get("build"):
            check_build(svc_name, svc["build"])
            if not image.startswith(f"{STAGING_PROJECT}/"):
                fail(f"{svc_name}: built image must be tagged {STAGING_PROJECT}/<name>, not {image!r} (a production tag would be overwritten)")
            if image in prod_images:
                fail(f"{svc_name}: image {image!r} is the image a production container runs")
        elif image.split(":")[0] not in ALLOWED_IMAGES_WITHOUT_BUILD:
            fail(f"{svc_name}: uses image {image!r} without building it; staging must build its own images")
        for vol in svc.get("volumes") or []:
            source = vol.split(":")[0] if isinstance(vol, str) else (vol or {}).get("source", "")
            if source and not source.startswith((".", "/")) and source not in staging_volumes:
                fail(f"{svc_name}: mounts volume '{source}', which is not declared by the staging file")
            if source.startswith(("/", "./", "../")):
                fail(f"{svc_name}: bind-mounts {source}; staging data must live in staging volumes")
        for port in published_ports(svc):
            if port in staging_ports:
                fail(f"host port {port} is published twice: {staging_ports[port]} and {svc_name}")
            staging_ports[port] = svc_name
            if port in prod_ports:
                fail(f"{svc_name}: host port {port} is already used by production ({prod_ports[port]})")

        for key, value in env_map(svc).items():
            if key == "REDIS_URL" and urlsplit(value).hostname != "redis":
                fail(f"{svc_name}: REDIS_URL must point at the staging 'redis' service, got {value!r}")
            if key == "DATABASE_URL" and not (urlsplit(value).hostname or "").endswith(".invalid"):
                fail(f"{svc_name}: DATABASE_URL points at a database server ({value!r}); staging services use only SQLite files in staging volumes")
            if key == "DATABASE_PATH":
                mounts = {(v.split(":")[1] if isinstance(v, str) else v.get("target")) for v in svc.get("volumes") or []}
                if not any(value.startswith(m.rstrip("/") + "/") for m in mounts if m):
                    fail(f"{svc_name}: DATABASE_PATH {value} is not inside a staging volume")
            if key == "FRONTEND_SERVICE_PORTS":
                listed = set()
                for pair in re.sub(r"\s", "", value).split(","):
                    if not pair:
                        continue
                    name, _, port = pair.partition("=")
                    listed.add(name)
                    if not port.isdigit():
                        fail(f"{svc_name}: FRONTEND_SERVICE_PORTS entry {pair!r} has no port")
                    elif int(port) in prod_ports:
                        fail(f"{svc_name}: the staging site would call production port {port} for '{name}' ({prod_ports[int(port)]})")
                # A service left out keeps its production port in scripts/config.js.
                for name in sorted(frontend_service_names() - listed):
                    fail(f"{svc_name}: FRONTEND_SERVICE_PORTS has no entry for '{name}', so the staging site would call its production port")
            if "://" not in value or key.startswith("AZURE_"):
                continue
            for url in value.split(","):
                parts = urlsplit(url.strip())
                host = parts.hostname or ""
                if host in service_hosts or host.endswith(".invalid") or host in ALLOWED_EXTERNAL_HOSTS:
                    continue  # a staging container, the guard host, or an allowed public site
                if key in PUBLIC_URL_KEYS or key == "CORS_ORIGINS":
                    if host != user_ip:
                        fail(f"{svc_name}: {key} uses host {host!r}; browser-facing addresses must use USER_SERVER_IP")
                    if parts.port is not None and parts.port in prod_ports:
                        fail(f"{svc_name}: {key} points at production port {parts.port} ({prod_ports[parts.port]})")
                else:
                    fail(f"{svc_name}: {key}={url.strip()!r} does not point at a staging service")

    # 7. Report.
    print(f"Checked {len(services)} staging services against {len(PRODUCTION_FILES)} production Compose files.")
    print(f"Staging host ports: {', '.join(f'{p} ({s})' for p, s in sorted(staging_ports.items()))}")
    for msg in warnings:
        print(f"WARN {msg}")
    for msg in errors:
        print(f"FAIL {msg}")
    if errors:
        print(f"{len(errors)} error(s): staging is NOT safe to start with these settings.")
        return 1
    print("OK: staging is isolated from production (names, ports, networks, volumes, images, Redis, databases, URLs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
