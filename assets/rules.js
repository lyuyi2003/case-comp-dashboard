/* Date rules for the page. These repeat scripts/rules.py in JavaScript, so a
   status like "closing soon" stays correct on days when no update has run.
   If you change a rule in one file, change it in the other too.

   Dates stay as text like "2027-01-11". That format sorts correctly as plain
   text, so comparing two dates needs no conversion. */

const Rules = (() => {
  const MAIN_PHASE_FIELDS = ["case_release", "submission_deadline", "finals"];
  const DATE_FIELDS = ["registration_opens", "registration_deadline", ...MAIN_PHASE_FIELDS];
  const SINGAPORE = "Asia/Singapore";
  const SINGAPORE_OFFSET_HOURS = 8;
  const MS_PER_DAY = 86400000;

  // Turn "2027-01-11" into a plain count of days, so we can subtract dates.
  function dayNumber(iso) {
    const [year, month, day] = iso.split("-").map(Number);
    return Date.UTC(year, month - 1, day) / MS_PER_DAY;
  }

  function daysUntil(iso, today) {
    return dayNumber(iso) - dayNumber(today);
  }

  function addDays(iso, days) {
    return new Date((dayNumber(iso) + days) * MS_PER_DAY).toISOString().slice(0, 10);
  }

  // Today's date in Singapore, wherever the page is opened.
  function todayInSingapore(now = new Date()) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: SINGAPORE }).format(now);
  }

  function academicYearOf(iso) {
    const [year, month] = iso.split("-").map(Number);
    return month >= 8 ? year : year - 1;
  }

  function isLeapYear(year) {
    return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  }

  // Move a date forward by whole years. 29 Feb becomes 28 Feb if needed.
  function shiftYears(iso, years) {
    const [year, month, day] = iso.split("-");
    const newYear = Number(year) + years;
    const newDay = month === "02" && day === "29" && !isLeapYear(newYear) ? "28" : day;
    return `${newYear}-${month}-${newDay}`;
  }

  // Dates to plan with. Expected dates are moved forward to this academic year.
  // The stored record is never changed: see effective_dates in rules.py.
  function effectiveDates(record, settings) {
    const dates = {};
    DATE_FIELDS.forEach((field) => { dates[field] = record[field] || null; });

    const known = Object.values(dates).filter(Boolean);
    if (record.date_status !== "expected" || known.length === 0) return dates;

    const shift = settings.academic_year_start - academicYearOf(known.sort()[0]);
    if (shift <= 0) return dates;

    DATE_FIELDS.forEach((field) => {
      if (dates[field]) dates[field] = shiftYears(dates[field], shift);
    });
    return dates;
  }

  // Only confirmed dates can give a precise status.
  function computeStatus(record, today, settings) {
    if (record.date_status !== "confirmed") {
      return record.organiser_says_open ? "open" : "unconfirmed";
    }

    const opens = record.registration_opens;
    const deadline = record.registration_deadline;
    const main = MAIN_PHASE_FIELDS.map((field) => record[field]).filter(Boolean).sort();
    const first = main[0];
    const last = main[main.length - 1];

    if (last && today > last) return "ended";
    if (opens && today < opens) return "not-yet-open";
    if (deadline && today <= deadline) {
      return daysUntil(deadline, today) <= settings.closing_soon_days ? "closing-soon" : "open";
    }
    if (first && first <= today) return "ongoing";
    if (deadline) return "closed";
    return opens ? "open" : "unconfirmed";
  }

  // The next scheduled run, as a Date. Singapore has no daylight saving, so
  // adding 8 hours gives Singapore clock time.
  function nextScheduledRun(schedule, now = new Date()) {
    const offset = SINGAPORE_OFFSET_HOURS * 3600000;
    const local = new Date(now.getTime() + offset);
    for (let ahead = 0; ahead <= 7; ahead += 1) {
      const candidate = new Date(Date.UTC(
        local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() + ahead,
        schedule.hour_sgt
      ));
      if (schedule.weekdays.includes(candidate.getUTCDay()) && candidate > local) {
        return new Date(candidate.getTime() - offset);
      }
    }
    return null;
  }

  return {
    DATE_FIELDS,
    MAIN_PHASE_FIELDS,
    addDays,
    computeStatus,
    dayNumber,
    daysUntil,
    effectiveDates,
    nextScheduledRun,
    shiftYears,
    todayInSingapore,
  };
})();
