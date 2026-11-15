-- One row per install id per day: what TELEMETRY.md says a ping holds, and the day it arrived. No IP address.
create table if not exists pings(
  day text not null,            -- YYYY-MM-DD (UTC), the day it arrived
  id text not null,             -- the install's random id for that month
  cli text, engine text, macos text, arch text, cohort text,
  apps text not null,           -- JSON list, names from the fixed list only
  backend text,
  sessions text, saves text, recalls text, forgets text, memories text,   -- ranges: 0, 1-9, 10-99, ...
  primary key(day, id));
create index if not exists pings_cohort on pings(cohort, day);
