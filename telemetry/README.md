# The usage-count endpoint

What `dawnmere telemetry ping` sends to, as described in [TELEMETRY.md](../TELEMETRY.md): a Cloudflare Worker that
accepts a ping only in the documented shape (`valid()` in `worker.js`), stores it in D1 with the day it arrived, never
reads the sender's IP address, has request logs off, and deletes pings older than 13 months.

Deploy (LF Labs' Cloudflare account): see the comment at the top of `wrangler.toml`.

Questions it answers, for example:

```sql
-- active installs per day
select day, count(*) from pings group by day order by day;
-- installs from each setup week still sending, by week since
select cohort, strftime('%Y-W%W', day) as week, count(distinct id) from pings group by cohort, week;
-- which apps people connect
select value as app, count(*) from pings, json_each(pings.apps) where day = date('now') group by app;
```
