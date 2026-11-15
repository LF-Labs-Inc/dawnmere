"""Anonymous usage counts (TELEMETRY.md): once a day at most, a few counts, never anything a memory, prompt or file
says.

On by default for a new install, asked at setup. An install made before this existed is asked once (setup run again,
or a terminal update) and sends nothing until it answers. Off: the `telemetry off` command, LFLABS_MEMORY_TELEMETRY=0
or DO_NOT_TRACK=1. `telemetry show` prints exactly what would be sent.

What goes out is payload() and nothing else: the fields in FIELDS, the counts as buckets ("10-99"), a random id that
changes every month, and how long ago this Mac was set up, in coarse ranges (so retention can be counted without
following anyone). The endpoint keeps single pings for 7 days, then only daily totals. No memory text, prompt, name,
path, project or IP address.

The environment switches are read from the login shell too: the daily agent runs under launchd, which never sees a
DO_NOT_TRACK set in ~/.zshrc. A command run with one set turns usage counts off for good (honor_env).
"""
import json
import os
import platform
import sqlite3
import sys
import time
import urllib.request
import uuid
from importlib import metadata
from pathlib import Path
from xml.sax.saxutils import escape

from . import install_record
from .brand import COMMAND, PRODUCT, TELEMETRY_URL
from .layout import CLI_DIST, ENGINE_DIST, data_dir, home, logs_dir
from .run import run

ENDPOINT = TELEMETRY_URL
OFF_ENV = "LFLABS_MEMORY_TELEMETRY"   # 0 / off / false: never send (a company's machines, CI)
URL_ENV = "LFLABS_MEMORY_TELEMETRY_URL"  # tests only
LABEL = "com.lflabs.memory.telemetry"
SCHEMA = 1
FIELDS = ("schema", "id", "cli", "engine", "macos", "arch", "age", "apps", "backend", "week", "memories")
AGES = ("0", "1", "2", "3-5", "6-11", "12+")  # months since setup
APPS = ("claude-code", "codex", "cursor", "windsurf", "gemini", "copilot", "qwen-code", "kimi-code", "qoder", "iflow",
        "cline")
QUESTION = (f"Share anonymous usage counts with LF Labs to help improve {PRODUCT}? Never your memories, prompts or "
            f"file names; see them any time with `{COMMAND} telemetry show`")
DAY = 86400


def path():
    return data_dir() / "telemetry.json"


def load():
    """{"enabled": bool, "asked": time, "id": str, "month": "YYYY-MM", "last_day": "YYYY-MM-DD"}, or {} when this
    install has never answered."""
    try:
        got = json.loads(path().read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(p.name + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, p)


def asked():
    return "enabled" in load()


def env_off(env=None):
    """Whether the environment turns it off, whatever was answered."""
    env = os.environ if env is None else env
    return str(env.get(OFF_ENV, "")).strip().lower() in ("0", "off", "false", "no") or \
        str(env.get("DO_NOT_TRACK", "")).strip().lower() in ("1", "true", "yes")


def enabled():
    return bool(load().get("enabled")) and not env_off()


SHELL_MARK = "__lflabs_memory_env__"


def shell_env():
    """DO_NOT_TRACK and the off switch as a new Terminal window has them (login, interactive zsh), or None when the
    shell could not be asked."""
    r = run(["zsh", "-lic", f'printf "\\n{SHELL_MARK}%s\\t%s\\n" "$DO_NOT_TRACK" "${OFF_ENV}"'], timeout=20)
    for line in reversed((r.out or "").splitlines()) if r.ok else []:
        if line.startswith(SHELL_MARK):
            dnt, off = (line[len(SHELL_MARK):].split("\t") + [""])[:2]
            return {"DO_NOT_TRACK": dnt, OFF_ENV: off}
    return None


def honor_env():
    """An off switch seen in the environment is kept: usage counts are turned off and the agent removed, so it holds
    whether or not the agent's own environment has it. Returns True when it did."""
    if env_off() and load().get("enabled"):
        choose(False)
        return True
    return False


def choose(on, now=None):
    """Record the answer and put the daily agent in place (or take it away). Returns the agent's note."""
    state = load()
    state.update(enabled=bool(on), asked=now or time.time())
    _save(state)
    return install_agent() if on else remove_agent()


def ask_once(prompt_fn, default=True):
    """The question for an install that has never answered, asked once where someone can answer (a terminal). Not
    asked (and nothing sent) when there is no one to ask, or the environment turns it off. Returns the answer, or
    None when it was not asked."""
    if asked() or env_off() or not sys.stdin.isatty():
        return None
    on = prompt_fn(QUESTION, default)
    choose(on)
    return on


# ---------- what is sent

def bucket(n):
    if n is None:
        return None
    n = int(n)
    if n <= 0:
        return "0"
    for top in (10, 100, 1000, 10000):
        if n < top:
            return f"{top // 10 if top > 10 else 1}-{top - 1}"
    return "10000+"


def _version(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def _month(now):
    return time.strftime("%Y-%m", time.gmtime(now))


def install_id(state, now):
    """This month's random id: a new one each calendar month (UTC), never derived from anything on the Mac."""
    if state.get("month") != _month(now) or not state.get("id"):
        state.update(id=str(uuid.uuid4()), month=_month(now))
    return state["id"]


def _age(now):
    """Months since setup, as one of AGES (coarse on purpose: with the rest of a ping, an exact week could single out
    a Mac and link its monthly ids)."""
    rec = install_record.load() or {}
    created = rec.get("created")
    if not isinstance(created, (int, float)):
        return None
    months = max(0, int((now - created) // (30.44 * DAY)))
    return "0" if months < 1 else "1" if months < 2 else "2" if months < 3 else "3-5" if months < 6 else \
        "6-11" if months < 12 else "12+"


def _apps():
    rec = install_record.load() or {}
    got = {f.get("app") for f in rec.get("files", []) if isinstance(f, dict)}
    got |= {"claude-code" for c in rec.get("commands", []) if isinstance(c, dict) and c.get("ok")
            and "plugin" in (c.get("argv") or [])}
    return sorted(a for a in got if a in APPS)  # only names from the fixed list: never anything else an entry holds


def _counts(now):
    p = data_dir() / "memory.db"
    out = {"sessions": None, "saves": None, "recalls": None, "forgets": None}
    if not p.exists():
        return out, None
    week = now - 7 * DAY
    try:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error:
        return out, None
    try:
        def count(sql, *args):
            try:
                return db.execute(sql, args).fetchone()[0] or 0
            except sqlite3.Error:
                return None
        out = {"sessions": count("select count(*) from sessions where activity >= ?", week),
               "saves": count("select count(*) from saves where at >= ?", week),
               "recalls": count("select count(*) from injections where at >= ?", week),
               "forgets": count("select count(*) from memories where status = 'retired' and updated >= ?", week)}
        total = count("select count(*) from memories where status = 'active'")
    finally:
        db.close()
    return {k: bucket(v) for k, v in out.items()}, bucket(total)


def _backend():
    from . import settings
    b = settings.load()["llm"].get("backend")
    return b if b in ("claude-cli", "anthropic-api", "none") else None


def payload(state=None, now=None):
    """Exactly what one ping sends."""
    now = time.time() if now is None else now
    state = load() if state is None else state
    week, total = _counts(now)
    mac = platform.mac_ver()[0]
    mac = mac if "." in mac or not mac else mac + ".0"  # always major.minor (the endpoint takes no other shape)
    return {"schema": SCHEMA, "id": install_id(state, now), "cli": _version(CLI_DIST), "engine": _version(ENGINE_DIST),
            "macos": ".".join(mac.split(".")[:2]) or None, "arch": platform.machine() or None, "age": _age(now),
            "apps": _apps(), "backend": _backend(), "week": week, "memories": total}


def ping(now=None, post=None, shell_check=True):
    """Send today's ping if it is on and today's has not gone. Returns what happened, in a few words. Never raises:
    a ping that fails is simply not sent; nothing is retried or queued."""
    now = time.time() if now is None else now
    if honor_env() or not enabled():
        return "off"
    login = shell_env() if shell_check else {}
    if login is None:  # could not tell whether the user's shell says off: not today
        return "not sent (the login shell did not answer)"
    if env_off(login):
        choose(False)
        return "off (the login shell turns it off)"
    state = load()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if state.get("last_day") == day:
        return "already sent today"
    body = payload(state, now)
    _save({**state, "last_day": day})  # one try a day, sent or not
    try:
        (post or _post)(json.dumps(body).encode())
        return "sent"
    except Exception as e:  # offline, a DNS block, the endpoint down: fine
        return f"not sent ({type(e).__name__})"


def _post(data):
    req = urllib.request.Request(os.environ.get(URL_ENV) or ENDPOINT, data=data, method="POST",
                                 headers={"content-type": "application/json",
                                          "user-agent": f"{COMMAND}/{_version(CLI_DIST) or '?'}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler())
    with opener.open(req, timeout=5) as r:
        r.read(1024)


# ---------- the daily agent

def plist_path():
    return home() / f"Library/LaunchAgents/{LABEL}.plist"


def _command():
    """This program's own command, absolute (what the agent runs)."""
    import shutil
    found = shutil.which(COMMAND)
    if found:
        return str(Path(found).absolute())
    sibling = Path(sys.executable).parent / COMMAND
    return str(sibling) if sibling.exists() else None


def render(cmd, data=None):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{escape(cmd)}</string><string>telemetry</string><string>ping</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>LFLABS_MEMORY_HOME</key><string>{escape(str(data or data_dir()))}</string></dict>
  <key>StartInterval</key><integer>21600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardErrorPath</key><string>{escape(str(logs_dir() / "telemetry.log"))}</string>
</dict></plist>
"""


def install_agent():
    """Write the agent (every 6 hours, it sends at most one ping a day) and load it. A note when it could not be."""
    cmd = _command()
    if not cmd:
        return f"the {COMMAND} command was not found, so no daily ping is scheduled"
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    p.write_text(render(cmd))
    os.chmod(p, 0o644)
    dom = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", f"{dom}/{LABEL}"], timeout=30)
    r = run(["launchctl", "bootstrap", dom, str(p)], timeout=30)
    return "" if r.ok else "the daily ping could not be scheduled (launchctl)"


def remove_agent():
    run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], timeout=30)
    plist_path().unlink(missing_ok=True)
    return ""


# ---------- the command

def status_text():
    state = load()
    if env_off():
        head = f"Usage counts: off ({OFF_ENV} or DO_NOT_TRACK is set)."
    elif "enabled" not in state:
        head = f"Usage counts: off, not asked yet. `{COMMAND} telemetry on` to share them."
    elif state["enabled"]:
        head = f"Usage counts: on, at most once a day. `{COMMAND} telemetry off` to stop."
    else:
        head = f"Usage counts: off. `{COMMAND} telemetry on` to share them."
    return head + f"\nWhat is sent, and what never is: TELEMETRY.md in the {PRODUCT} repo."


def main(action=None, out=print):
    if action != "ping":
        honor_env()
    if action in (None, "status"):
        out(status_text())
        return 0
    if action == "show":
        state = load()
        body = payload(state)
        _save(state)  # this month's id, kept: the next ping sends the same one
        out(json.dumps(body, indent=2))
        out(f"\nSent to {ENDPOINT}, at most once a day, only when telemetry is on. Nothing else is sent.")
        return 0
    if action in ("on", "off"):
        note = choose(action == "on")
        out(status_text() + (f"\n{note}" if note else ""))
        return 0
    if action == "ping":  # the daily agent's own call
        out(ping())
        return 0
    out(f"{COMMAND} telemetry [status|show|on|off]")
    return 2
