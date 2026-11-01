# Verification record — 1 November 2026

- SQLite uploaded by user opened read-only and passed integrity_check = ok.
- 20 SQLite race records and 162 runner records before merge.
- Imported repaired 2022 CSV: 3 races, 36 runners.
- Imported older 2026 CSV: 5 additional races, 44 runner records not previously present in SQLite.
- Final 28 races, 242 runners; two dates only. The 2026 older export supplied five races and 23 runners at those five races, plus 21 records in the original 20 races (principally non-finishers/non-runners); no cross-source horse-name duplicates were identified in the final merge.
- No direct live website collection or 2022–2026 full archive gathering has been performed.
- All standards_input_allowed flags in recovery audit are false; needs further independent QA and exact course layout resolution.
- 7 local recovery tests passed. Original v2.5 offline tests passed.
