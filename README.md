# Case Comp Tracker

A website that tracks business and consulting case competitions for NUS AY2026/27 Semester 2, and keeps itself up to date.

**Live site:** https://lyuyi2003.github.io/case-comp-dashboard/

It shows sign-up deadlines, key dates, eligibility and official links, plus a timeline from October to May. That timeline helps you spot competitions whose sign-ups close long before the semester starts.

Always confirm dates and rules on the official page before you sign up.

## How the update works

Every Monday and Thursday at about 8:00 AM Singapore time, a scheduled task runs on Anthropic's computers, so your laptop can be off.

1. **Fetch.** `scripts/fetch_pages.py` visits about 67 pages and works out which ones really changed.
2. **Research.** Claude follows [UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md). It reads the changed pages, runs 10 web searches and writes what it found as a proposal.
3. **Check and save.** `scripts/apply_update.py` checks the proposal against the accuracy rules, and saves it only if everything passes.
4. **Publish.** The task sends the new data to GitHub, and the site rebuilds within a minute or two.

Claude can't edit the data directly, and there is no way for it to delete a competition. If a page can't be read, the old data stays and the competition is marked "Could not refresh".

## How much it costs

**Nothing extra.** GitHub and GitHub Pages are free, and the updates use your Claude Pro plan instead of a paid API key.

Each update uses some of your Pro allowance, shared with your normal Claude use. The tested update took about 82 seconds with 10 searches. Check [your usage page](https://claude.ai/settings/usage) after a few runs to see what that means for you.

- If you hit your limit, that update is skipped until your usage resets, and the next run catches up.
- You won't be charged as long as usage credits stay turned off.
- Updates stop if your subscription is paused.

## Run an update by hand

Open the [task page](https://claude.ai/code/routines/trig_01Rc2riagAP2cBsVZgU7mnJf) and click **Run now**. To change the schedule or pause it, use the menu next to the task's name and choose **Edit**.

## Correct a competition or add one by hand

Your own changes go in `data/manual-overrides.json`. Updates never overwrite it, and your values always win.

1. Open [the file on GitHub](https://github.com/lyuyi2003/case-comp-dashboard/blob/main/data/manual-overrides.json) and click the pencil icon.
2. Make your change, then click **Commit changes**.
3. Your change appears after the next update. To see it sooner, click **Run now**.

Be careful with commas and quotation marks. One typing mistake stops updates until it's fixed, and "What changed" will show the failed update.

### Correct a competition

Find the competition's `id` in [data/competitions.json](data/competitions.json), then list the fields to change. This example records a confirmed Accenture deadline you found on the NUS CFG site, and clears the dates that haven't been announced yet:

```json
{
  "corrections": {
    "accenture-uic": {
      "edition": "2027",
      "date_status": "confirmed",
      "registration_deadline": "2026-12-04",
      "case_release": null,
      "finals": null,
      "notes": "Deadline confirmed by hand from the NUS CFG page."
    }
  },
  "additions": []
}
```

Dates are written as `YYYY-MM-DD`, and `null` means empty.

- When `date_status` is `confirmed`, every date must be from this academic year, so clear any old ones as shown above.
- You can only set a date for a stage that already has a source, such as a deadline on a record that already has one.
- To change who is eligible, change `restrictions`. The yes, check or no result is worked out from it.
- A correction stays until you remove it, so delete it once the automatic data has caught up.

### Add a competition

Add a record to `additions`:

```json
{
  "corrections": {},
  "additions": [
    {
      "id": "example-case-challenge",
      "name": "Example Case Challenge",
      "organiser": "Example Organisation",
      "category": "consulting/strategy",
      "description": "One or two sentences in your own words about what the competition involves.",
      "format": "in-person",
      "team_size": "3-4",
      "team_rules": "Cross-university teams allowed",
      "eligibility_text": "Open to all undergraduates in Singapore",
      "prizes": "S$1,000 for the winning team",
      "edition": "2027",
      "date_status": "confirmed",
      "registration_deadline": "2027-02-01",
      "finals": "2027-03-01",
      "official_url": "https://example.com/case-challenge",
      "source_urls": [
        {
          "url": "https://example.com/case-challenge",
          "used_for": "Dates and eligibility",
          "fields": ["registration_deadline", "finals", "eligibility_text"],
          "source_type": "organiser",
          "method": "page-read",
          "last_verified": "2026-11-02"
        }
      ]
    }
  ]
}
```

- `category` is one of: `consulting/strategy`, `sustainability`, `finance`, `marketing`, `policy/economics`, `insurance/risk`, `supply-chain`, `social-impact`, `other`.
- `date_status` is `confirmed`, `expected` or `unknown`.
- `source_type` is `organiser`, `university`, `firm` or `news`.

## Run it on your laptop

Open a terminal in the project folder.

To see the site:

```
.venv\Scripts\python -m http.server 8000
```

Then open http://localhost:8000. Press `Ctrl+C` in the terminal to stop.

To run the checks:

```
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts\validate.py
```

If you've changed anything, get the latest version first with `git pull`, because the scheduled task updates the same files.

## If something looks wrong

| What you see | What to do |
|---|---|
| A warning that the data is old | Open the [task page](https://claude.ai/code/routines/trig_01Rc2riagAP2cBsVZgU7mnJf) and look at the latest run, then click **Run now** |
| Runs fail with a GitHub access error | Reconnect GitHub at [claude.ai/connect-github](https://claude.ai/connect-github), and check that the [Claude GitHub App](https://github.com/apps/claude/installations/select_target) can access this repository |
| "What changed" says an update failed | The likely cause is a typing mistake in `data/manual-overrides.json`. Fix it, then click **Run now** |
| A competition says "Could not refresh" | Its pages couldn't be read for a while. Check the official page yourself |
| A competition is missing | NUS CFG blocks automated visits, so new listings there can be missed. Add it by hand |

## What's in the project

| Path | What it is |
|---|---|
| `index.html`, `assets/` | The website |
| `data/competitions.json` | All the competition data |
| `data/manual-overrides.json` | Your corrections and additions |
| `data/update-log.json` | A record of each update |
| `config/settings.json` | Semester dates, your eligibility profile and the update schedule |
| `config/sources.json` | Pages to check and searches to run |
| `scripts/rules.py` | The Sem 2, status and eligibility rules |
| `assets/rules.js` | The same date rules for the website. Change both files together |
| `UPDATE_INSTRUCTIONS.md` | What Claude follows on each update |
| `tests/` | Automatic checks |

## Next academic year

Update the dates in `config/settings.json` from the [NUS academic calendar](https://www.nus.edu.sg/registrar/calendar), along with `academic_year`, `academic_year_start`, `registration_window_start`, `timeline` and your year of study. Update the search phrases in `config/sources.json` too.
