# Ranking donors by measured fit

**Date:** 2026-08-31
**Question:** of the 128 KOTOR 2 models a head can be taken from, which are
worth building?
**Answer:** 80 are as close to Carth as the median head the game ships, and the
six worst are all creatures rather than faces - which the measure worked out on
its own.

## What is measured, and why that one

`transplant.transfer_strain` already answers the question that decides how a
build looks. Weight transfer gives every new vertex the influences of the
nearest point on the *host's* surface, so wherever the two shapes disagree, a
vertex inherits from whatever happened to be closest and then swings with a
bone that has nothing to do with it. That is the "animates, but is smashed
about" failure, seen in game. The fraction of donor vertices sitting far from
the host's surface is a direct count of how much of the donor will be driven by
the wrong thing.

**Measured after fitting, deliberately.** Raw strain would rank donors by size:
a head twice as large disagrees everywhere even when it is the same shape.
Since the tool applies `--fit` anyway, so does the ranking, and what survives is
disagreement of *shape* - the part no scaling rescues.

## The grades are vanilla's numbers, not invented thresholds

Fitting all 60 vanilla K1 heads onto Carth:

| | far fraction |
|---|---|
| median | 0.0% |
| 75th percentile | 0.3% |
| 90th percentile | 4.1% |
| worst (`n_yoda`) | 11.5% |

So the scale is: **clean** ≤ 1.2%, **good** ≤ 4.8%, **rough** ≤ 11.5%, and
**hard** past anything the game ships. A donor graded `rough` is no worse than a
head that ships and works; only `hard` is doing something vanilla never asks of
the engine. Grading against shipped content keeps the bar empirical - the
alternative is a score that looks authoritative and means nothing.

Vanilla K1 against itself comes out 41 clean, 8 good, 5 rough, 6 blocked, and
nothing `hard`, which is the sanity check: the scale must not describe the game
as broken.

## Three checks that the number means something

* **The identity case is exactly zero.** Carth's head in Carth's head node
  measures 0.0% far, 0.0% mean. If that were not so, nothing else would be
  worth reading.
* **It reproduces the earlier calibration.** `n_rodian` at 10.9% and `n_yoda` at
  11.5% match the figures recorded when the strain thresholds were first set,
  from a completely separate run.
* **It predicts the one build we have in-game experience of.** `n_quarren`
  grades `rough` at 9.1%, flags 2.6x oversize (so `--fit`), reports that its own
  weights come across, and names all four mouth tentacles as parts to fold in.
  That is exactly what happened when it was built: it needed fitting, it
  animated correctly because its weights carried over, and two of the four
  tentacles hung wrong.

## KOTOR 2, 128 donors, ranked against Carth

| grade | count |
|---|---|
| clean | 80 |
| good | 22 |
| rough | 11 |
| hard | 6 |
| blocked | 9 |

Three practical findings fall out:

* **No K2 head needs decimating.** Not one of the 119 usable donors exceeds
  KOTOR's vertex budget. Decimation is for imported third-party meshes, not for
  cross-game work.
* **89 of 119 keep their own weights**, because K2 inherited K1's bone naming.
  This is why cross-game head swaps animate as well as they do - the donor's own
  facial rig comes across by name rather than being approximated.
* **24 need `--fit`** at more than 1.5x, and **76 bring extra parts** that have
  to be folded in.

### The six `hard` donors are all creatures

```
c_drdwar        12.0% far   1.8x     war droid
c_zakkeg        22.9% far   3.0x     zakkeg
c_tach          30.2% far   4.1x     tach
c_drdmkfour     30.5% far   3.7x     MK-IV droid
c_bosdrexl      37.2% far   1.9x     drexl
c_drdspyder     47.7% far   1.9x     spyder droid
```

Not one is a humanoid head. The measure was never told what a face is - it only
compares shapes - and it still put every non-face at the bottom. Meanwhile the
recognisably humanoid aliens land where intuition says they should:
`n_duros` clean, `c_ithorian` and `n_wookiem` good, `n_quarren` and `n_rodian`
rough.

### Nine blocked, for one honest reason

`c_condrdl, c_rakghoul, c_selkath, n_komadh, n_rakata, n_selkath, n_selkathcr,
n_xorh, n_zharh` - every one because its `Head` mesh carries a **tangent**
column the writer cannot author. That is a real limit of the tool, not a
property of the donor, and the list says so rather than dropping them silently.
Tangent support would unlock nine more donors, including all the Selkath.

## Where it shows up

* `kmdlfun rank --install <K1> --host p_carthh --donor-install <K2> --notes`
* In the app, **Rank for this host** re-sorts the donor list best-first and
  labels each entry with its grade, whether its own weights survive, and whether
  it brings extra parts. It runs on a worker, because reading 128 models takes
  about twelve seconds.

The extra facts - own weights, oversize, extra parts, over budget - are reported
*beside* the number, never folded into it. They are different kinds of thing,
and a single blended score would hide exactly the detail that decides whether a
donor is worth trying.
