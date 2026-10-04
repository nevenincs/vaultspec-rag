#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["psutil==7.2.2", "filelock==4.0.6"]
# ///
"""The dev-server harness every web app on this workstation shares.

Canonical source: the private `devservers` repository, `dev/devserver.py`.
Every enrolled repo carries a byte-identical copy at the same path, and the
`dev` recipe, the CI workflow and the React/Vite versions are rendered from
the constants below. A fix made in a copy is a fork: make it in devservers and
run `just sync` there. `just dev check` fails in any repo whose copy of the
recipe or workflow has drifted from this file.

`up` converges on one state: every declared port served by a healthy process
this checkout started. In order it

1. sanitizes: forgets records of dead processes, stops this checkout's Vite
   servers left running on undeclared fixed ports, and refuses dependencies
   older than the lockfile;
2. reattaches to a service this checkout started when it still answers its
   health check and was started under the current configuration;
3. stops anything else holding a declared port - another worktree's server, a
   crashed start, a server that stopped answering, one started under an older
   configuration - and starts the service again;
4. registers the app's name with the portless proxy, prints its URLs and, on a
   terminal, follows the log until Ctrl+C, which detaches and leaves it running.

The port numbers, the portless name and the services come from ONE place: the
`portless` and `devserver` keys of the frontend's package.json. Vite configs,
Playwright configs and scripts read the same keys; nothing else writes a port.

Exit codes: 0 ok, 1 fail, 2 usage or bad declaration, 127 missing tool or
dependencies.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_NO_TOOL = 127

WINDOWS = sys.platform == "win32"
ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve()

#: The versions every enrolled frontend declares and resolves. Bumping one is a
#: change here, synced to every repo, not a dependabot merge in one of them.
STANDARD = {
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "vite": "8.3.1",
    "@vitejs/plugin-react": "6.1.1",
}

BLOCK_SIZE = 20
EPHEMERAL_FLOOR = 32768  # below this a listener's port was chosen by someone
READY_SECONDS = 90.0
RELEASE_SECONDS = 15.0
PROBE_SECONDS = 3.0  # while waiting for a fresh start: poll fast
VERDICT_SECONDS = 10.0  # before calling a running server degraded: wait out a busy event loop
VERDICT_TRIES = 3
TAIL_LINES = 40

#: Ports a declared service must not take: other tools' defaults, which is how
#: two dev servers ended up answering on the same number in the first place.
AVOID = {
    3000: "Node/React defaults",
    4173: "Vite preview default",
    4200: "Angular default",
    5000: "Flask default, macOS AirPlay",
    5173: "Vite dev default",
    5432: "Postgres",
    5500: "VS Code Live Server",
    8000: "Python http.server default",
    8080: "common proxy default",
}

#: portless subcommands; an app cannot be named after one.
RESERVED_NAMES = {"run", "get", "alias", "hosts", "list", "doctor", "trust", "clean", "prune", "proxy", "service"}
NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

RECIPE = """\
[doc('Dev server: start or attach, sanitize, health-check, evict occupiers (up|restart|stop|status|logs|check|ci)')]
[group('dev')]
dev target="up" *args="":
    @uv run --script dev/devserver.py {{ target }} {{ args }}
"""

WORKFLOW_PATH = ".github/workflows/devserver.yml"
WORKFLOW = """\
# Rendered from dev/devserver.py by the devservers repository (`just sync`) and
# identical in every enrolled repo; `just dev check` fails when it drifts.
name: Dev server
on:
  push:
    branches: [main]
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review, labeled]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  devserver:
    name: 'Check: Dev server'
    if: >-
      github.event_name != 'pull_request' ||
      (github.event.pull_request.head.repo.full_name == github.repository &&
      ((github.event.action == 'labeled' && github.event.label.name == 'ci:full' &&
      github.event.sender.type == 'User') ||
      (github.event.pull_request.draft == false &&
      (github.event.pull_request.author_association == 'OWNER' ||
      github.event.pull_request.author_association == 'COLLABORATOR'))))
    runs-on: [self-hosted, Linux, X64]
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
        with:
          persist-credentials: false
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7
        with:
          package-manager-cache: false
          node-version-file: .nvmrc
      - name: Set up just
        uses: taiki-e/install-action@6012bba2f8e3e666a2b212f8823c06831704ce92 # just
        with:
          tool: just@1.38.0
      - name: Set up uv
        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1
        with:
          enable-cache: false
          prune-cache: false
      - run: just dev ci
"""

#: Tracked files where a port number may never be written: they read it from the
#: declaration. Prose is not scanned; the devservers registry replaces it.
LITERAL_SURFACES = re.compile(r"(^|/)(justfile|[^/]+\.just|(vite|vitest|playwright)[^/]*\.config\.[cm]?[jt]s)$")


class DeclarationError(Exception):
    """package.json does not declare a valid dev server."""


# --------------------------------------------------------------------------
# The declaration


@dataclass(frozen=True)
class Health:
    path: str = "/"
    expect: str | None = "/@vite/client"


@dataclass(frozen=True)
class Service:
    key: str
    port: int
    run: tuple[str, ...] | None  # None: port reserved, started by another process
    cwd: Path
    health: Health | None
    replace: bool
    route: str
    ready: float = READY_SECONDS  # a server that builds before it listens needs longer


@dataclass(frozen=True)
class App:
    name: str
    package: Path
    block: tuple[int, int]
    host: str
    services: dict[str, Service]
    requires: tuple[str, ...]
    env_cmd: tuple[str, ...] | None
    ci_env: dict[str, str]
    config: str | None
    deps: dict[str, str] = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return self.package.parent

    @property
    def dev(self) -> Service:
        return self.services["dev"]


def find_package(root: Path = ROOT) -> Path:
    """The one package.json under `root` (itself or one level down) that declares `devserver`."""
    found = []
    for candidate in [root / "package.json", *sorted(root.glob("*/package.json"))]:
        if "node_modules" in candidate.parts or not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and "devserver" in data:
            found.append(candidate)
    if len(found) != 1:
        where = ", ".join(str(p.relative_to(root)) for p in found) or "none"
        raise DeclarationError(
            f"expected exactly one package.json with a `devserver` key at the root or one level down; found {where}"
        )
    return found[0]


def _int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise DeclarationError(f"{what} must be a TCP port in 1-65535, got {value!r}")
    return value


def _seconds(value: object, what: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 1 <= value <= 1800:
        raise DeclarationError(f"{what} must be a number of seconds in 1-1800, got {value!r}")
    return float(value)


def _argv(value: object, what: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise DeclarationError(f"{what} must be a non-empty list of strings")
    return tuple(value)


def _health(value: object, default: Health | None, what: str) -> Health | None:
    if value is None:
        return default
    if value is False:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("path", "/"), str):
        raise DeclarationError(f"{what} must be false or {{path, expect}}")
    expect = value.get("expect")
    if expect is not None and not isinstance(expect, str):
        raise DeclarationError(f"{what}.expect must be a string")
    return Health(value.get("path", "/"), expect)


def load(package: Path) -> App:
    """Parse and validate the declaration in `package`."""
    data = json.loads(package.read_text(encoding="utf-8"))
    portless, spec = data.get("portless"), data.get("devserver")
    if not isinstance(portless, dict) or not isinstance(spec, dict):
        raise DeclarationError(f"{package}: `portless` and `devserver` must both be objects")
    name = portless.get("name")
    if not isinstance(name, str) or not NAME.match(name) or name in RESERVED_NAMES:
        raise DeclarationError(f"portless.name must be a DNS label that is not a portless subcommand, got {name!r}")
    dev_port = _int(portless.get("appPort"), "portless.appPort")

    block = spec.get("block")
    if not (isinstance(block, list) and len(block) == 2):
        raise DeclarationError("devserver.block must be [first, last]")
    lo, hi = _int(block[0], "devserver.block[0]"), _int(block[1], "devserver.block[1]")
    if hi - lo + 1 != BLOCK_SIZE:
        raise DeclarationError(f"devserver.block must span exactly {BLOCK_SIZE} ports, got {lo}-{hi}")

    host = spec.get("host", "0.0.0.0")
    if not isinstance(host, str):
        raise DeclarationError("devserver.host must be a string")
    dev_spec = spec.get("dev", {})
    if not isinstance(dev_spec, dict):
        raise DeclarationError("devserver.dev must be an object")
    config = dev_spec.get("config")
    if config is not None and not isinstance(config, str):
        raise DeclarationError("devserver.dev.config must be a path")

    services = {
        "dev": Service(
            key="dev",
            port=dev_port,
            run=None,
            cwd=package.parent,
            health=_health(dev_spec.get("health"), Health(), "devserver.dev.health"),
            replace=True,
            route=name,
            ready=_seconds(dev_spec.get("ready", READY_SECONDS), "devserver.dev.ready"),
        )
    }
    raw_services = spec.get("services", {})
    if not isinstance(raw_services, dict):
        raise DeclarationError("devserver.services must be an object")
    for key, raw in raw_services.items():
        what = f"devserver.services.{key}"
        if key == "dev" or not NAME.match(key) or not isinstance(raw, dict):
            raise DeclarationError(f"{what}: a service is a lowercase label other than `dev`, declared as an object")
        run = _argv(raw.get("run"), f"{what}.run")
        cwd = raw.get("cwd", ".")
        if not isinstance(cwd, str):
            raise DeclarationError(f"{what}.cwd must be a path relative to the package")
        services[key] = Service(
            key=key,
            port=_int(raw.get("port"), f"{what}.port"),
            run=run,
            cwd=(package.parent / cwd).resolve(),
            health=_health(raw.get("health"), Health(expect=None) if run else None, f"{what}.health"),
            # A port only reserved here belongs to a process started elsewhere - a
            # Playwright run, say - so it is left alone unless declared replaceable.
            replace=bool(raw.get("replace", run is not None)),
            route=f"{key}.{name}",
            ready=_seconds(raw.get("ready", READY_SECONDS), f"{what}.ready"),
        )

    ports = [s.port for s in services.values()]
    if len(set(ports)) != len(ports):
        raise DeclarationError(f"two services declare the same port: {sorted(ports)}")
    for svc in services.values():
        if not lo <= svc.port <= hi:
            raise DeclarationError(f"{svc.key} port {svc.port} is outside the block {lo}-{hi}")

    requires = tuple(dev_spec.get("requires", ()))
    unknown = [r for r in requires if r not in services or r == "dev"]
    if unknown:
        raise DeclarationError(f"devserver.dev.requires names undeclared services: {unknown}")
    ci_env = spec.get("ci", {}).get("env", {}) if isinstance(spec.get("ci", {}), dict) else None
    if not isinstance(ci_env, dict) or not all(isinstance(v, str) for v in ci_env.values()):
        raise DeclarationError("devserver.ci.env must map names to strings")

    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return App(
        name=name,
        package=package,
        block=(lo, hi),
        host=host,
        services=services,
        requires=requires,
        env_cmd=_argv(spec.get("env"), "devserver.env"),
        ci_env=dict(ci_env),
        config=config,
        deps=deps,
    )


# --------------------------------------------------------------------------
# Processes and ports


def listening() -> dict[int, set[int]]:
    """Every listening TCP port on this machine, mapped to the PIDs that hold it."""
    held: dict[int, set[int]] = {}
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.pid:
            held.setdefault(conn.laddr.port, set()).add(conn.pid)
    return held


def excluded_ranges() -> list[tuple[int, int]]:
    """Windows' reserved TCP port ranges (Hyper-V, WinNAT); a process cannot bind inside them."""
    if not WINDOWS:
        return []
    try:
        out = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [(int(a), int(b)) for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", out, re.MULTILINE)]


def _norm(path: str | Path) -> str:
    text = str(path).replace("\\", "/").rstrip("/")
    return text.lower() if WINDOWS else text


def _proc(pid: int) -> psutil.Process | None:
    try:
        return psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _describe(pid: int) -> str:
    proc = _proc(pid)
    if proc is None:
        return f"pid {pid}"
    try:
        return f"pid {pid} ({proc.name()})"
    except psutil.Error:
        return f"pid {pid}"


def vite_home(pid: int) -> str | None:
    """The directory whose node_modules holds the Vite that `pid` runs, or None when it runs no Vite."""
    proc = _proc(pid)
    if proc is None:
        return None
    try:
        args, cwd = proc.cmdline(), proc.cwd()
    except psutil.Error:
        return None
    for arg in args:
        if _norm(arg).endswith("vite/bin/vite.js"):
            path = Path(arg) if Path(arg).is_absolute() else Path(cwd) / arg
            # Lexical, not resolve(): `.bin/..` must collapse, links must not be followed.
            text = _norm(os.path.normpath(path))
            cut = text.rfind("/node_modules/")
            return text[:cut] if cut >= 0 else None
    return None


def kill_tree(pids: Iterable[int]) -> list[str]:
    """Stop each PID with its descendants; return the ones that could not be stopped."""
    procs: dict[int, psutil.Process] = {}
    refused = []
    for pid in pids:
        if pid in (0, 4) or pid == os.getpid():
            refused.append(f"{pid} (system)")
            continue
        proc = _proc(pid)
        if proc is None:
            continue
        try:
            for child in proc.children(recursive=True):
                procs[child.pid] = child
        except psutil.Error:
            pass
        procs[pid] = proc
    for proc in procs.values():
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            refused.append(_describe(proc.pid))
    _, alive = psutil.wait_procs(list(procs.values()), timeout=5)
    for proc in alive:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    return refused


def wait_for(predicate: Callable[[], bool], seconds: float, step: float = 0.3) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def probe(port: int, health: Health | None, timeout: float = PROBE_SECONDS) -> bool:
    """Whether `port` answers the service's health check; a service without one only has to listen."""
    if health is None:
        return True
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{health.path}", timeout=timeout) as res:
            body = res.read(400_000)
            status = res.status
    except urllib.error.HTTPError:
        return False
    except (OSError, ValueError):
        return False
    return status == 200 and (health.expect is None or health.expect.encode() in body)


def settled(port: int, health: Health | None) -> bool:
    """A patient probe for a server that is already running.

    A Vite server compiling a large stylesheet can stall its event loop for
    seconds; one slow answer must not get it restarted. Only a server that
    fails every try is degraded.
    """
    return any(probe(port, health, VERDICT_SECONDS) for _ in range(VERDICT_TRIES))


# --------------------------------------------------------------------------
# State: one record per service, kept outside every checkout


def state_root() -> Path:
    if WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "devservers"


@dataclass(frozen=True)
class Record:
    pid: int
    created: float
    port: int
    checkout: str
    fingerprint: str
    started_at: float
    argv: list[str]


class State:
    def __init__(self, app: App, root: Path | None = None) -> None:
        self.dir = (root or state_root()) / app.name
        self.dir.mkdir(parents=True, exist_ok=True)

    def lock(self) -> FileLock:
        return FileLock(str(self.dir / "lock"), timeout=120)

    def log(self, key: str) -> Path:
        return self.dir / f"{key}.log"

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def read(self, key: str) -> Record | None:
        try:
            raw = json.loads(self._path(key).read_text(encoding="utf-8"))
            return Record(**raw)
        except (OSError, ValueError, TypeError):
            return None

    def write(self, key: str, record: Record) -> None:
        self._path(key).write_text(json.dumps(record.__dict__, indent=2), encoding="utf-8")

    def forget(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def alive(record: Record | None) -> bool:
    """The recorded process still runs - the same process, not a reused PID."""
    if record is None:
        return False
    proc = _proc(record.pid)
    try:
        return proc is not None and abs(proc.create_time() - record.created) < 2.0
    except psutil.Error:
        return False


def owned(pid: int, record: Record | None, checkout: str) -> bool:
    """Whether listener `pid` is the recorded process, or runs under it, for this checkout."""
    if record is None or record.checkout != checkout or not alive(record):
        return False
    proc = _proc(pid)
    if proc is None:
        return False
    try:
        chain = [proc, *proc.parents()]
    except psutil.Error:
        chain = [proc]
    return any(p.pid == record.pid for p in chain)


def decide(holders: set[int], mine: bool, healthy: bool, current: bool) -> str:
    """What `up` does about one service's port: `start`, `reuse`, or `replace:<reason>`."""
    if not holders:
        return "start"
    if not mine:
        return "replace:foreign"
    if not healthy:
        return "replace:degraded"
    if not current:
        return "replace:stale"
    return "reuse"


# --------------------------------------------------------------------------
# Running services


def checkout_id(root: Path = ROOT) -> str:
    return _norm(root.resolve())


def vite_bin(app: App) -> Path | None:
    for base in [app.dir, *app.dir.parents]:
        candidate = base / "node_modules" / "vite" / "bin" / "vite.js"
        if candidate.is_file():
            return candidate
        if base == ROOT:
            break
    return None


def fill(argv: Iterable[str], app: App, svc: Service) -> list[str]:
    values = {
        "port": str(svc.port),
        "host": app.host,
        "root": str(ROOT),
        "app": str(app.dir),
        "name": app.name,
    }
    out = [re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), a) for a in argv]
    found = shutil.which(out[0])
    return [found or out[0], *out[1:]]


def command(app: App, svc: Service) -> list[str] | None:
    """The argv that starts `svc`, or None when a tool it needs is missing."""
    if svc.key == "dev":
        node, vite = shutil.which("node"), vite_bin(app)
        if node is None or vite is None:
            return None
        # node directly, never `npm run dev`: the PID recorded is the one that listens.
        argv = [node, str(vite)]
        if app.config:
            argv += ["--config", app.config]
        return argv + ["--port", str(svc.port), "--strictPort", "--host", app.host]
    assert svc.run is not None
    argv = fill(svc.run, app, svc)
    return argv if shutil.which(argv[0]) or Path(argv[0]).is_file() else None


def lockfile(app: App) -> Path:
    return app.dir / "package-lock.json"


def stale_dependencies(app: App) -> list[str]:
    """Direct dependencies whose installed version differs from the lockfile's."""
    try:
        lock = json.loads(lockfile(app).read_text(encoding="utf-8")).get("packages", {})
    except (OSError, ValueError):
        return ["package-lock.json is missing or unreadable"]
    stale = []
    for name in sorted(app.deps):
        want = lock.get(f"node_modules/{name}", {}).get("version")
        if want is None:
            continue
        installed = None
        for base in [app.dir, *app.dir.parents]:
            manifest = base / "node_modules" / name / "package.json"
            if manifest.is_file():
                with contextlib.suppress(ValueError):
                    installed = json.loads(manifest.read_text(encoding="utf-8")).get("version")
                break
            if base == ROOT:
                break
        if installed != want:
            stale.append(f"{name} {installed or 'missing'} != {want}")
    return stale


def env_overlay(app: App, ci: bool) -> dict[str, str]:
    """Environment the app's own hook adds - e.g. an upstream or a CA path - plus the CI overrides."""
    extra = dict(app.ci_env) if ci else {}
    if app.env_cmd:
        argv = fill(app.env_cmd, app, app.dev)
        res = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False, env={**os.environ, **extra})
        if res.returncode != 0:
            raise DeclarationError(f"devserver.env hook failed ({res.returncode}): {res.stderr.strip()[-400:]}")
        try:
            hook = json.loads(res.stdout)
        except ValueError as err:
            raise DeclarationError(f"devserver.env hook must print a JSON object: {err}") from err
        if not isinstance(hook, dict) or not all(isinstance(v, str) for v in hook.values()):
            raise DeclarationError("devserver.env hook must print a JSON object of strings")
        extra.update(hook)
    return extra


def fingerprint(app: App, overlay: dict[str, str]) -> str:
    """What a running server was started under; a change means `up` restarts it."""
    digest = hashlib.sha256()
    files = [app.package, lockfile(app), HARNESS]
    if app.config:
        files.append(app.dir / app.config)
    else:
        files += sorted(app.dir.glob("vite.config.*"))
    for path in files:
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    digest.update(json.dumps(overlay, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def spawn(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> psutil.Process:
    """Start `argv` detached from this terminal, output to `log`."""
    if log.exists() and log.stat().st_size > 0:
        log.replace(log.with_suffix(".log.1"))
    out = log.open("ab")
    out.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(argv)}\n".encode())
    out.flush()
    kwargs: dict = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
    try:
        if WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                # Leave the job object `just` runs in, or closing the terminal takes the server with it.
                proc = subprocess.Popen(argv, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError:
                proc = subprocess.Popen(argv, creationflags=flags, **kwargs)
        else:
            proc = subprocess.Popen(argv, start_new_session=True, **kwargs)
    finally:
        out.close()
    return psutil.Process(proc.pid)


def tail(path: Path, lines: int = TAIL_LINES) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


# --------------------------------------------------------------------------
# Reporting


def say(tag: str, text: str, err: bool = False) -> None:
    print(f"{tag:<5}{text}", file=sys.stderr if err else sys.stdout, flush=True)


def interactive() -> bool:
    """A terminal someone is watching. On Windows NUL also claims to be a tty; only a console counts."""
    if not sys.stdout.isatty():
        return False
    if not WINDOWS:
        return True
    import ctypes
    import msvcrt

    mode = ctypes.c_uint32()
    handle = msvcrt.get_osfhandle(sys.stdout.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def tailnet_name() -> str | None:
    exe = shutil.which("tailscale")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5, check=False).stdout
        name = json.loads(out).get("Self", {}).get("DNSName", "")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return name.rstrip(".") or None


def urls(app: App, svc: Service) -> list[str]:
    found = [f"http://localhost:{svc.port}/"]
    if app.host in ("0.0.0.0", "::", "true"):
        name = tailnet_name()
        if name:
            found.append(f"http://{name}:{svc.port}/")
    if shutil.which("portless") and (svc.key == "dev" or svc.run):
        found.append(f"https://{svc.route}.localhost/")
    return found


def route(svc: Service, register: bool) -> None:
    """Point the portless name at the service's port, or remove it; portless is optional."""
    exe = shutil.which("portless")
    if exe is None or os.environ.get("CI"):
        return
    argv = [exe, "alias", svc.route, str(svc.port), "--force"] if register else [exe, "alias", "--remove", svc.route]
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        say("warn", f"{svc.key}: portless alias failed: {err}", err=True)
        return
    if res.returncode != 0 and register:
        say("warn", f"{svc.key}: portless alias failed: {(res.stderr or res.stdout).strip()[-300:]}", err=True)


# --------------------------------------------------------------------------
# The harness


class Harness:
    def __init__(self, app: App, state: State | None = None, ci: bool = False) -> None:
        self.app = app
        self.state = state or State(app)
        self.ci = ci
        self.checkout = checkout_id()
        self._overlay: dict[str, str] | None = None

    @property
    def overlay(self) -> dict[str, str]:
        if self._overlay is None:
            self._overlay = env_overlay(self.app, self.ci)
        return self._overlay

    def selected(self, key: str | None) -> list[Service]:
        if key in (None, "", "dev"):
            return [self.app.services[k] for k in self.app.requires] + [self.app.dev]
        if key == "all":
            return list(self.app.services.values())
        if key not in self.app.services:
            raise DeclarationError(f"unknown service {key!r}; declared: {', '.join(self.app.services)}")
        return [self.app.services[key]]

    # -- sanitize ----------------------------------------------------------

    def sanitize(self, held: dict[int, set[int]]) -> None:
        for key in self.app.services:
            record = self.state.read(key)
            if record is not None and not alive(record):
                self.state.forget(key)
        declared = {s.port for s in self.app.services.values()}
        homes = {_norm(self.app.dir), _norm(ROOT)}
        strays: dict[int, int] = {}
        for port, pids in held.items():
            if port in declared or port >= EPHEMERAL_FLOOR:
                continue
            for pid in pids:
                if vite_home(pid) in homes:
                    strays[pid] = port
        for pid, port in sorted(strays.items(), key=lambda kv: kv[1]):
            say("--", f"sanitize: stopping {_describe(pid)}, this checkout's Vite on undeclared :{port}")
        refused = kill_tree(strays)
        for who in refused:
            say("warn", f"sanitize: could not stop {who}", err=True)

    # -- up ----------------------------------------------------------------

    def up(self, key: str | None) -> int:
        services = self.selected(key)
        missing = [s.key for s in services if s.run is None and s.key != "dev"]
        services = [s for s in services if s.key not in missing]
        stale = stale_dependencies(self.app)
        if stale:
            where = self.app.dir.relative_to(ROOT).as_posix() or "."
            say("127", f"dependencies differ from {where}/package-lock.json: {'; '.join(stale[:5])}", err=True)
            say("", f"run `npm ci` in {where} (or this repo's init recipe)", err=True)
            return EXIT_NO_TOOL
        with self.state.lock():
            held = listening()
            self.sanitize(held)
            self.clear_reserved(held, services)
            worst = EXIT_OK
            for svc in services:
                worst = max(worst, self.converge(svc))
                if worst != EXIT_OK:
                    break
        return worst

    def clear_reserved(self, held: dict[int, set[int]], services: list[Service]) -> None:
        """Before (re)starting dev, free the ports its own children will bind - another worktree's engine, say."""
        if not any(s.key == "dev" for s in services):
            return
        dev_record = self.state.read("dev")
        for svc in self.app.services.values():
            if svc.run is not None or svc.key == "dev" or not svc.replace:
                continue
            holders = held.get(svc.port, set())
            foreign = {pid for pid in holders if not owned(pid, dev_record, self.checkout)}
            if foreign:
                who = ", ".join(map(_describe, foreign))
                say("--", f"{svc.key}: :{svc.port} held by {who} (foreign); stopping")
                kill_tree(foreign)

    def converge(self, svc: Service) -> int:
        record = self.state.read(svc.key)
        holders = listening().get(svc.port, set())
        mine = bool(holders) and all(owned(pid, record, self.checkout) for pid in holders)
        healthy = bool(holders) and (settled(svc.port, svc.health) if mine else probe(svc.port, svc.health))
        current = record is not None and record.fingerprint == fingerprint(self.app, self.overlay)
        action = decide(holders, mine, healthy, current)

        if action == "reuse":
            say("ok", f"{svc.key}: reattached to pid {record.pid} on :{svc.port}")
            route(svc, register=True)
            return EXIT_OK
        if action.startswith("replace:"):
            reason = action.split(":", 1)[1]
            who = ", ".join(map(_describe, holders))
            if not svc.replace and not mine:
                verdict = "answers" if healthy else "does not answer its health check"
                tag = "ok" if healthy else "warn"
                say(tag, f"{svc.key}: :{svc.port} is held by {who}, which {verdict}; left alone")
                if healthy:
                    # Whoever started it, it serves this app's port: the name should reach it.
                    route(svc, register=True)
                return EXIT_OK
            say("--", f"{svc.key}: :{svc.port} held by {who} ({reason}); restarting")
            if not self.free(svc, holders, record):
                return EXIT_FAIL
        return self.start(svc)

    def free(self, svc: Service, holders: set[int], record: Record | None) -> bool:
        pids = set(holders)
        if record is not None and alive(record) and record.checkout == self.checkout:
            pids.add(record.pid)
        refused = kill_tree(pids)
        self.state.forget(svc.key)
        if not wait_for(lambda: svc.port not in listening(), RELEASE_SECONDS):
            left = listening().get(svc.port, set())
            say("FAIL", f"{svc.key}: :{svc.port} is still held by {', '.join(map(_describe, left))}", err=True)
            if refused:
                say("", f"not permitted to stop {', '.join(refused)}; stop it from an elevated shell", err=True)
            return False
        return True

    def start(self, svc: Service) -> int:
        for lo, hi in excluded_ranges():
            if lo <= svc.port <= hi:
                say("FAIL", f"{svc.key}: :{svc.port} is inside Windows' reserved range {lo}-{hi}", err=True)
                return EXIT_FAIL
        argv = command(self.app, svc)
        if argv is None:
            tool = "node and node_modules/vite" if svc.key == "dev" else (svc.run or ["?"])[0]
            say("127", f"{svc.key}: {tool} is not installed; run `npm ci` or this repo's init recipe", err=True)
            return EXIT_NO_TOOL
        env = {
            **os.environ,
            **self.overlay,
            "DEVSERVER_NAME": self.app.name,
            "DEVSERVER_SERVICE": svc.key,
            "DEVSERVER_CHECKOUT": self.checkout,
            "DEVSERVER_INSTANCE": uuid.uuid4().hex,
            "DEVSERVER_FINGERPRINT": fingerprint(self.app, self.overlay),
            "FORCE_COLOR": "1",
        }
        log = self.state.log(svc.key)
        proc = spawn(argv, svc.cwd, env, log)
        self.state.write(
            svc.key,
            Record(
                pid=proc.pid,
                created=proc.create_time(),
                port=svc.port,
                checkout=self.checkout,
                fingerprint=env["DEVSERVER_FINGERPRINT"],
                started_at=time.time(),
                argv=argv,
            ),
        )
        record = self.state.read(svc.key)

        def ready() -> bool:
            holders = listening().get(svc.port, set())
            mine = bool(holders) and all(owned(p, record, self.checkout) for p in holders)
            return mine and probe(svc.port, svc.health)

        def exited() -> bool:
            try:
                return not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
            except psutil.Error:
                return True

        deadline = time.monotonic() + svc.ready
        while time.monotonic() < deadline:
            if ready():
                say("ok", f"{svc.key}: started pid {proc.pid} on :{svc.port}")
                route(svc, register=True)
                return EXIT_OK
            if exited():
                break
            time.sleep(0.4)
        kill_tree([proc.pid])
        self.state.forget(svc.key)
        why = "exited" if exited() else f"did not answer on :{svc.port} within {svc.ready:.0f}s"
        say("FAIL", f"{svc.key}: pid {proc.pid} {why}; last lines of {log}:", err=True)
        print(tail(log), file=sys.stderr)
        return EXIT_FAIL

    # -- stop / status / logs ---------------------------------------------

    def stop(self, key: str | None) -> int:
        services = self.app.services.values() if key in (None, "", "all") else self.selected(key)
        ok = True
        with self.state.lock():
            held = listening()
            for svc in services:
                record = self.state.read(svc.key)
                holders = held.get(svc.port, set())
                if not svc.replace:
                    holders = {p for p in holders if owned(p, record, self.checkout)}
                if not holders and not alive(record):
                    self.state.forget(svc.key)
                    continue
                if self.free(svc, holders, record):
                    say("ok", f"{svc.key}: stopped :{svc.port}")
                    route(svc, register=False)
                else:
                    ok = False
        return EXIT_OK if ok else EXIT_FAIL

    def status(self) -> int:
        """A report, never a gate."""
        held = listening()
        say("", f"{self.app.name}  block {self.app.block[0]}-{self.app.block[1]}  state {self.state.dir}")
        for svc in self.app.services.values():
            # A port-only service is run by the dev server (an engine its Vite plugin spawns): judge it by dev's record.
            record = self.state.read(svc.key if svc.key == "dev" or svc.run else "dev")
            holders = held.get(svc.port, set())
            if not holders:
                word = "down"
            elif all(owned(p, record, self.checkout) for p in holders):
                current = record is not None and record.fingerprint == fingerprint(self.app, self.overlay)
                word = ("up" if current else "stale") if settled(svc.port, svc.health) else "degraded"
            else:
                word = "foreign"
            who = ", ".join(map(_describe, holders)) or "-"
            say("", f"  {svc.key:<12} :{svc.port:<6} {word:<9} {who}")
            if holders:
                say("", f"  {'':<12}  {'  '.join(urls(self.app, svc))}")
        return EXIT_OK

    def logs(self, key: str | None) -> int:
        svc = self.selected(key)[-1]
        log = self.state.log(svc.key)
        if not log.exists():
            say("--", f"{svc.key}: no log yet at {log}")
            return EXIT_OK
        return self.follow(svc, announce=False)

    def follow(self, svc: Service, announce: bool = True) -> int:
        """Print the URLs; on a terminal, follow the log until Ctrl+C, which detaches."""
        if announce:
            say("", "  ".join(urls(self.app, svc)))
        if not interactive() or self.ci:
            return EXIT_OK
        log = self.state.log(svc.key)
        say("", f"following {log} - Ctrl+C detaches, `just dev stop` stops")
        try:
            with log.open("rb") as handle:
                for line in handle.read().splitlines()[-TAIL_LINES:]:
                    print(line.decode(errors="replace"))
                checked = time.monotonic()
                while True:
                    chunk = handle.read()
                    if chunk:
                        sys.stdout.write(chunk.decode(errors="replace"))
                        sys.stdout.flush()
                    elif time.monotonic() - checked > 5:
                        checked = time.monotonic()
                        record = self.state.read(svc.key)
                        holders = listening().get(svc.port, set())
                        if not holders or not all(owned(p, record, self.checkout) for p in holders):
                            say("FAIL", f"{svc.key}: the server on :{svc.port} went away; `just dev` restarts it", True)
                            return EXIT_FAIL
                    time.sleep(0.3)
        except KeyboardInterrupt:
            print()
            say("", "detached; the server keeps running")
            return EXIT_OK
        except OSError:
            # The reader went away (`just dev | head`; Windows reports EINVAL, not EPIPE).
            return EXIT_OK


# --------------------------------------------------------------------------
# check: the static gate CI runs


def tracked(root: Path = ROOT) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False).stdout
    except OSError:
        return []
    return [p for p in out.decode(errors="replace").split("\0") if p]


def literal_ports(app: App, root: Path = ROOT) -> list[str]:
    """Where a declared port is written into a config surface instead of read from the declaration."""
    ports = {str(s.port) for s in app.services.values()}
    pattern = re.compile(r"(?<![\w.])(" + "|".join(sorted(ports)) + r")(?![\w])")
    found = []
    for rel in tracked(root):
        if not LITERAL_SURFACES.search(rel):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                found.append(f"{rel}:{number}: {line.strip()[:120]}")
    return found


def version_findings(app: App) -> list[str]:
    findings = []
    try:
        lock = json.loads(lockfile(app).read_text(encoding="utf-8")).get("packages", {})
    except (OSError, ValueError):
        lock = {}
    for name, want in STANDARD.items():
        declared = app.deps.get(name)
        resolved = lock.get(f"node_modules/{name}", {}).get("version")
        if declared != want:
            findings.append(f"{name}: package.json declares {declared or 'nothing'}, the standard is exactly {want}")
        if resolved != want:
            findings.append(f"{name}: package-lock.json resolves {resolved or 'nothing'}, the standard is {want}")
    return findings


def check(app: App, root: Path = ROOT) -> list[str]:
    """Every way this repo can disagree with the standard; empty means it conforms."""
    findings = []
    for svc in app.services.values():
        if svc.port in AVOID:
            findings.append(f"{svc.key} :{svc.port} is {AVOID[svc.port]}'s port")
        for lo, hi in excluded_ranges():
            if lo <= svc.port <= hi:
                findings.append(f"{svc.key} :{svc.port} is inside Windows' reserved range {lo}-{hi}")
    findings += version_findings(app)
    justfile = root / "justfile"
    if not justfile.is_file() or RECIPE not in justfile.read_text(encoding="utf-8").replace("\r\n", "\n"):
        findings.append("justfile does not carry the canonical `dev` recipe (`devserver.py render recipe` prints it)")
    if (root / ".github").is_dir():
        workflow = root / WORKFLOW_PATH
        if not workflow.is_file() or workflow.read_text(encoding="utf-8").replace("\r\n", "\n") != WORKFLOW:
            findings.append(f"{WORKFLOW_PATH} is missing or differs from the canonical one (`render workflow`)")
        if not (root / ".nvmrc").is_file():
            findings.append(".nvmrc is missing at the repo root; the dev-server workflow reads Node's version from it")
    findings += [f"port literal outside the declaration: {hit}" for hit in literal_ports(app, root)]
    return findings


# --------------------------------------------------------------------------
# Entry point


TARGETS = ("up", "restart", "stop", "status", "logs", "check", "ci", "render")
USAGE = "usage: devserver.py [up|restart|stop|status|logs] [service] | check | ci | render recipe|workflow"


def run_ci(app: App) -> int:
    findings = check(app)
    for finding in findings:
        say("FAIL", finding, err=True)
    if findings:
        return EXIT_FAIL
    say("ok", "check: declaration, versions, recipe and workflow conform")
    if not (app.dir / "node_modules").is_dir() or stale_dependencies(app):
        npm = shutil.which("npm")
        if npm is None:
            say("127", "ci: npm is not installed", err=True)
            return EXIT_NO_TOOL
        say("--", f"ci: npm ci in {app.dir.relative_to(ROOT) or '.'}")
        if subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=app.dir, check=False).returncode != 0:
            return EXIT_FAIL
    harness = Harness(app, ci=True)
    code = harness.up(None)
    if code == EXIT_OK:
        # A second `up` must reattach, not restart: that is the whole point of the harness.
        started = {s.key: harness.state.read(s.key) for s in harness.selected(None)}
        code = harness.up(None)
        again = {s.key: harness.state.read(s.key) for s in harness.selected(None)}
        if code == EXIT_OK and started != again:
            say("FAIL", "ci: a second `up` restarted the server instead of reattaching to it", err=True)
            code = EXIT_FAIL
    harness.stop("all")
    return code


def main(argv: list[str]) -> int:
    # A log line Vite writes (its arrow, a filename) must never crash a report on a narrow code page.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    target = argv[0] if argv else "up"
    rest = argv[1] if len(argv) > 1 else None
    if target not in TARGETS or len(argv) > 2:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    if target == "render":
        if rest == "recipe":
            sys.stdout.write(RECIPE)
            return EXIT_OK
        if rest == "workflow":
            sys.stdout.write(WORKFLOW)
            return EXIT_OK
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        app = load(find_package())
        if target == "check":
            findings = check(app)
            for finding in findings:
                say("FAIL", finding, err=True)
            if not findings:
                say("ok", f"{app.name}: declaration, versions, recipe and workflow conform")
            return EXIT_FAIL if findings else EXIT_OK
        if target == "ci":
            return run_ci(app)
        harness = Harness(app, ci=bool(os.environ.get("CI")))
        if target == "status":
            return harness.status()
        if target == "logs":
            return harness.logs(rest)
        if target == "stop":
            return harness.stop(rest)
        if target == "restart":
            harness.stop(rest if rest else "dev")
        code = harness.up(rest)
        if code != EXIT_OK:
            return code
        shown = harness.selected(rest)
        for svc in shown[:-1]:
            say("", f"{svc.key}: " + "  ".join(urls(app, svc)))
        return harness.follow(shown[-1])
    except DeclarationError as err:
        say("FAIL", str(err), err=True)
        return EXIT_USAGE
    except Timeout:
        say("FAIL", "another `just dev` holds this app's lock; try again when it finishes", err=True)
        return EXIT_FAIL


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
        sys.stdout.flush()
    except OSError:
        # `just dev | head`: the reader left (EPIPE, or EINVAL on Windows); the server is unaffected.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = EXIT_OK
    sys.exit(code)
