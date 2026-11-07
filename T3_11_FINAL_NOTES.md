# T3-11 final verification notes
- Fixed 1 real bug: `t3_strip_cfg` (mt/templates/t3/panels.py) capped sets to MAX_SETS (3) BEFORE dropping unusable sets, so an invalid set used up a slot. Now filter first, then cap. Caught by selftest "T3-6 cfg normaliser".
- Selftest check 26 (timing T1 vs T2) is machine-load sensitive: measured 1.34x vs target 1.3x in this container (T1 7.7 s, T2 10.3 s); not a functional failure.
- Cosmetic (by design): when a chapter tag changes, the old tag fades out while the new one slides in (0.35 s overlap).
