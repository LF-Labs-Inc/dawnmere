# The usage-count endpoint

What `dawnmere telemetry ping` sends to, as described in [TELEMETRY.md](../TELEMETRY.md): a Cloudflare Worker that
accepts a ping only in the documented shape (`valid()` in `worker.js`), keeps it in D1 with the day it arrived for 7
days, then only daily totals with no id (13 months). It never reads the sender's IP address, and request logs are off.

Deploy (LF Labs' Cloudflare account): see the comment at the top of `wrangler.toml`.

Questions it answers, for example:

```sql
-- active and weekly-active installs per day
select day, field, n from daily where field in ('active', 'weekly_active') order by day;
-- installs still sending, by months since setup
select day, value as months, n from daily where field = 'age' order by day, value;
-- which apps people connect
select day, value as app, n from daily where field = 'app' order by day, n desc;
```
