# Next steps

Updated at the end of every step. Newest plan replaces the old one.

## Right now
1. **Owner action:** run `sql/001_init.sql` in the Supabase SQL editor, then put
   the five variables from `.env.example` into `.env`.
2. **Owner action:** give this machine push rights (see the blocked-push entry in
   `decisions.md`), then `git push -u origin main`.
3. Step 3 — `fetchers/calendar_skeleton.py`: 12 months of release dates from the
   FRED `releases/dates` API plus the FOMC calendar.
