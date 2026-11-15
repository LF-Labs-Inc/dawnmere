"""Usage counts (telemetry.py, TELEMETRY.md): what one ping holds, when it goes, and who is asked."""
import json
import sqlite3
import sys
import time

import pytest
from test_setup import box, run_setup  # noqa: F401  (the fixture, for the setup tests below)

from lflabs_memory_cli import install_record, layout, main as cli, setup, telemetry

SECRET = "my bank PIN is 4471 and the project is Bluebird"


@pytest.fixture
def home(mac, monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("LFLABS_MEMORY_HOME", str(data))
    monkeypatch.delenv(telemetry.OFF_ENV, raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    ran = []
    monkeypatch.setattr(telemetry, "run", lambda argv, timeout=None: ran.append(argv) or
                        type("R", (), {"ok": True, "out": "", "err": "", "code": 0})())
    data.mkdir(parents=True)
    mac.ran = ran
    return data


def store(data, now):
    db = sqlite3.connect(data / "memory.db")
    db.executescript("""
        create table memories(id integer primary key, content text, project text, status text, updated real);
        create table saves(id integer primary key, memory_id integer, at real, via text);
        create table injections(session_id text, memory_id integer, at real);
        create table sessions(session_id text primary key, transcript text, cwd text, activity real);""")
    for i in range(12):
        db.execute("insert into memories(content, project, status, updated) values(?, ?, 'active', ?)",
                   (SECRET, "Bluebird", now))
    db.execute("insert into memories(content, project, status, updated) values(?, 'Bluebird', 'retired', ?)",
               (SECRET, now - 86400))
    for i in range(3):
        db.execute("insert into saves(memory_id, at, via) values(1, ?, 'claude-code')", (now - 3600,))
    db.execute("insert into saves(memory_id, at, via) values(1, ?, 'claude-code')", (now - 30 * 86400,))  # old
    for i in range(140):
        db.execute("insert into injections values(?, 1, ?)", (f"s{i}", now - 60))
    db.execute("insert into sessions values('s1', '/Users/sam/.claude/projects/Bluebird/x.jsonl', "
               "'/Users/sam/code/Bluebird', ?)", (now,))
    db.commit()
    db.close()


def test_a_ping_holds_counts_and_nothing_a_memory_says(home):
    now = time.time()
    store(home, now)
    rec = install_record.empty()
    rec["files"] = [{"app": "codex", "path": "/Users/sam/.codex/config.toml"}, {"app": "Bluebird"}]
    install_record.save(rec)
    body = telemetry.payload({}, now)
    assert tuple(body) == telemetry.FIELDS
    assert body["week"] == {"sessions": "1-9", "saves": "1-9", "recalls": "100-999", "forgets": "1-9"}
    assert body["memories"] == "10-99"
    assert body["apps"] == ["codex"]  # names from the fixed list only
    text = json.dumps(body)
    for leak in ("Bluebird", "4471", "/Users", "sam", str(home)):
        assert leak not in text


def test_buckets():
    assert [telemetry.bucket(n) for n in (None, 0, 1, 9, 10, 99, 100, 999, 1000, 9999, 10000)] == \
        [None, "0", "1-9", "1-9", "10-99", "10-99", "100-999", "100-999", "1000-9999", "1000-9999", "10000+"]


def test_the_id_is_random_and_new_each_month(home):
    nov, dec = time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1)), time.mktime((2026, 12, 3, 12, 0, 0, 0, 0, -1))
    state = {}
    a = telemetry.install_id(state, nov)
    assert telemetry.install_id(state, nov + 86400) == a
    b = telemetry.install_id(state, dec)
    assert b != a and len(b) == 36


def test_nothing_goes_until_someone_says_yes(home):
    sent = []
    assert not telemetry.asked()
    assert telemetry.ping(post=sent.append) == "off" and sent == []


def test_once_a_day_and_a_failure_is_not_retried(home):
    telemetry.choose(True)
    sent = []
    day = time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1))
    assert telemetry.ping(day, post=sent.append) == "sent" and len(sent) == 1
    assert telemetry.ping(day + 3600, post=sent.append) == "already sent today" and len(sent) == 1
    assert json.loads(sent[0])["schema"] == telemetry.SCHEMA

    def down(_):
        raise OSError("offline")
    assert telemetry.ping(day + 86400, post=down).startswith("not sent")
    assert telemetry.ping(day + 86400 + 60, post=sent.append) == "already sent today"


@pytest.mark.parametrize("env", [{telemetry.OFF_ENV: "0"}, {telemetry.OFF_ENV: "off"}, {"DO_NOT_TRACK": "1"}])
def test_the_environment_turns_it_off_whatever_was_answered(home, monkeypatch, env):
    telemetry.choose(True)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sent = []
    assert telemetry.ping(post=sent.append) == "off" and sent == []
    assert "off" in telemetry.status_text()


def test_off_takes_the_agent_away_and_on_puts_it_back(home, mac):
    telemetry.choose(True)
    plist = telemetry.plist_path()
    assert plist.exists() and "<string>telemetry</string><string>ping</string>" in plist.read_text()
    telemetry.choose(False)
    assert not plist.exists() and not telemetry.enabled()


def test_an_install_from_before_is_asked_once_and_only_at_a_terminal(home, monkeypatch):
    asked = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert telemetry.ask_once(lambda q, d: asked.append(q) or True) is None and asked == [] and not telemetry.asked()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert telemetry.ask_once(lambda q, d: asked.append(d) or False) is False and asked == [True]
    assert telemetry.ask_once(lambda q, d: asked.append(d) or True) is None and asked == [True]  # once
    assert telemetry.asked() and not telemetry.enabled()


def test_show_prints_the_ping_and_the_next_ping_sends_the_same_id(home, capsys):
    telemetry.choose(True)
    assert cli.main(["telemetry", "show"]) == 0
    shown = json.loads(capsys.readouterr().out.split("\n\n")[0])
    sent = []
    telemetry.ping(post=sent.append)
    assert json.loads(sent[0])["id"] == shown["id"]


# ---------- setup and update

def test_a_new_install_is_on_by_default_and_says_so(box, monkeypatch):
    monkeypatch.delenv(telemetry.OFF_ENV)
    monkeypatch.setattr(telemetry, "run", lambda argv, timeout=None: type("R", (), {"ok": True, "err": ""})())
    code, out = run_setup()
    assert code == 0
    assert telemetry.enabled() and telemetry.plist_path().exists()
    assert "Usage counts: on" in out


def test_an_install_from_before_is_not_turned_on_by_yes(box, monkeypatch):
    monkeypatch.delenv(telemetry.OFF_ENV)
    (layout.data_dir()).mkdir(parents=True, exist_ok=True)
    (layout.data_dir() / "config.toml").write_text('owner_name = "Sam"\n')  # set up before usage counts existed
    args = cli.parser().parse_args(["setup", "--yes", "--plain"])
    assert setup.ask(args, lambda s: None).telemetry is None


def test_a_rerun_does_not_ask_again(box, monkeypatch):
    monkeypatch.delenv(telemetry.OFF_ENV)
    telemetry.choose(False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    from lflabs_memory_cli import prompt
    asked = []
    real = prompt.yes_no
    monkeypatch.setattr(prompt, "yes_no", lambda q, d, assume=None: asked.append(q) or real(q, d, assume=d))
    monkeypatch.setattr(prompt, "text", lambda q, default="": default)
    args = cli.parser().parse_args(["setup", "--plain", "--dry-run"])
    assert setup.ask(args, lambda s: None).telemetry is None
    assert telemetry.QUESTION not in asked
