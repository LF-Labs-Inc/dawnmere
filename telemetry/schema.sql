-- Single pings, kept 7 days (enough to count weekly actives), then only the daily totals below. No IP address.
create table if not exists pings(
  day text not null,            -- YYYY-MM-DD (UTC), the day it arrived
  id text not null,             -- the install's random id for that month
  cli text, engine text, macos text, arch text, age text,
  apps text not null,           -- JSON list, names from the fixed list only
  backend text,
  sessions text, saves text, recalls text, forgets text, memories text,   -- ranges: 0, 1-9, 10-99, ...
  primary key(day, id));
-- Daily totals, kept 13 months: how many installs sent a ping that day with each value of each field ("active" and
-- "weekly_active" for the counts of all of them). No id, so no row can be tied to an install.
create table if not exists daily(
  day text not null, field text not null, value text not null, n integer not null,
  primary key(day, field, value));
