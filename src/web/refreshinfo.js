/* Refresh info module: the last / next refresh times shown at the top right of the landing page.
     RefreshInfo.load()      reads refresh.json (written by every refresh) -> {record, nowMs} (nowMs from the server's clock)
     RefreshInfo.describe(record, schedule, nowMs)   the pure part: {last, kind, lastScheduled, next, delayed} as text
   "Next" is the next slot of the fixed schedule (every_minutes counted from `anchor`, both in settings.json), so an adhoc refresh
   never moves it. A slot more than grace_minutes late with no scheduled refresh since is "due (delayed)".  */
const RefreshInfo = (() => {
  const when = (ms) => new Date(ms).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  function slotAtOrBefore(schedule, nowMs) {
    const every = schedule.every_minutes * 60000, anchor = Date.parse(schedule.anchor);
    return anchor + Math.floor((nowMs - anchor) / every) * every;
  }
  function describe(record, schedule, nowMs) {
    const out = { last: "", kind: "", lastScheduled: "", next: "", delayed: false };
    if (record && !isNaN(Date.parse(record.refreshed_at))) {
      out.last = when(Date.parse(record.refreshed_at));
      if (record.kind === "scheduled") out.kind = "scheduled";
      else if (record.kind === "adhoc") out.kind = `adhoc, last ${record.range_hours} h / ${record.max_articles} stories`;
      if (record.kind === "adhoc" && record.last_scheduled_at) out.lastScheduled = when(Date.parse(record.last_scheduled_at));
    }
    if (schedule) {
      const slot = slotAtOrBefore(schedule, nowMs);
      const done = record ? Date.parse(record.last_scheduled_at || (record.kind === "scheduled" ? record.refreshed_at : "")) : NaN;
      out.delayed = nowMs - slot > schedule.grace_minutes * 60000 && !(done >= slot);
      out.next = out.delayed ? "due (delayed)" : when(slot + schedule.every_minutes * 60000);
    }
    return out;
  }
  async function load() {
    let record = null, nowMs = Date.now();
    try {
      const r = await fetch("refresh.json?t=" + Date.now(), { cache: "no-store" });
      if (r.ok) { record = await r.json(); nowMs = Date.parse(r.headers.get("date") || "") || nowMs; }
    } catch (e) {}
    return { record, nowMs };
  }
  return { load, describe, format: when };
})();
