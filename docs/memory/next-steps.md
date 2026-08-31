# Next steps

Updated at the end of every step. Newest plan replaces the old one.

## Right now
1. **Owner action:** run `sql/001_init.sql` in the Supabase SQL editor, then fill
   the five variables in `.env` (copy from `.env.example`).
2. **Owner action:** give this machine push rights (see the blocked-push entry in
   `decisions.md`), then `git push -u origin main`.
3. Step 7 — `fetchers/prices_daily.py`: daily XAU/DXY/real yield/Fed funds, a
   `--backfill-years 10` mode, and `events.regime` from the 90-day Fed funds
   direction.
