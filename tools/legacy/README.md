# Legacy harnesses

These exist only to reproduce the Milestone 0 evaluation of PyKotor, which
concluded that its MDL writer is a lossy semantic reconstruction rather than a
serializer: 0 of 2,832 vanilla K1 models round-trip byte-exact.

They inform nothing in the current tool, which uses its own byte-surgical
reader. They are kept because deleting the evidence behind a load-bearing
decision makes that decision harder to re-check later.

- `roundtrip_eval.py` — read and re-emit every model through PyKotor, byte-diff.
- `diff_anatomy.py` — characterise where one model's PyKotor round trip diverges.

See `reports/MILESTONE_0_FINDINGS.md`.
