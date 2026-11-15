# Usage counts

Dawnmere can send LF Labs a few anonymous counts, at most once a day, so we can tell how many Macs use it, which apps
people connect, and whether they keep using it. It never sends your memories, prompts, file names, project names or
anything they say.

- **New installs:** on by default. Setup asks, and you can say no there.
- **Installs from before 0.2.0:** off until you answer. You are asked once, the next time you run `dawnmere setup` or
  `dawnmere update` in a terminal. Until then nothing is sent.

## What is sent

One ping, exactly this shape. `dawnmere telemetry show` prints yours.

```json
{
  "schema": 1,
  "id": "3f0c6a52-6a0e-4c43-9a51-0a8b3c2d9e71",
  "cli": "0.2.0",
  "engine": "0.1.12",
  "macos": "15.2",
  "arch": "arm64",
  "age": "1",
  "apps": ["claude-code", "codex", "cursor"],
  "backend": "claude-cli",
  "week": {"sessions": "10-99", "saves": "1-9", "recalls": "100-999", "forgets": "0"},
  "memories": "100-999"
}
```

| Field | What it is |
| --- | --- |
| `id` | a random id, made on your Mac and replaced every calendar month; it is only used to count each Mac once a day and a week |
| `cli`, `engine` | the versions you run |
| `macos`, `arch` | macOS major and minor version, and the chip (`arm64`) |
| `age` | how long ago this Mac was set up, in months: 0, 1, 2, 3-5, 6-11 or 12+, so we can see whether people keep using it |
| `apps` | which AI apps setup connected, from a fixed list of names |
| `backend` | what does the background reading: your Claude plan, an API key, or none |
| `week` | counts for the last 7 days, as ranges (0, 1-9, 10-99, 100-999, ...): AI sessions, saves, memories put into prompts, forgets |
| `memories` | how many memories you have, as a range |

## What is never sent

The text of any memory, prompt or conversation; project, file, folder or app names outside the fixed list; your name,
email or account; anything about other apps on your Mac. The endpoint does not store IP addresses.

## Turning it off

- `dawnmere telemetry off` (and `dawnmere telemetry on` to turn it back on)
- `LFLABS_MEMORY_TELEMETRY=0` or `DO_NOT_TRACK=1` in the environment: nothing is sent, whatever was answered (for
  a company's Macs, or CI). The daily ping also reads them from your login shell (`~/.zprofile`, `~/.zshrc`), and once
  any `dawnmere` command sees one, usage counts stay off until you turn them on again.
- `dawnmere telemetry` says whether it is on

## How it works

- `cli/src/lflabs_memory_cli/telemetry.py` builds the ping. Nothing else in Dawnmere sends anything to LF Labs.
- A LaunchAgent (`~/Library/LaunchAgents/com.lflabs.memory.telemetry.plist`) runs `dawnmere telemetry ping` every 6
  hours. It sends at most one ping a day, tries once, and never queues or retries. It is only there while usage counts
  are on, and `dawnmere uninstall` removes it.
- The ping goes to `https://telemetry.dawnmere.app/v1/ping`. The endpoint's code is in `telemetry/`: it checks each
  ping against this schema and drops anything else. It keeps single pings for 7 days (to count weekly users), then
  only daily totals with no id in them, for 13 months. So there is no long record of any one Mac.
