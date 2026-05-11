# PT0X Sentinel Investigation — Session State

## Problem

BB5 PLYRDSEQ has 56 PT0X mismatches (224 diff lines). We output `-32768` for every
entry; the reference has a mix of `-32768`, `-16384`, and `0`. BB6 PLYRDSQ2 has 2
similar mismatches. All failing images come from **NBA_DNK2.IMG**.

## Root Cause of Wrong ite_pttbl

`NBA_DNK2.IMG` has `seqcnt=2, scrcnt=1, version=0x634 < 0x654, palcnt=4, n_special=5`.
The `ite_pttbl` heuristic runs because `n_seqscr=3 > 0`. It finds `std_bad=3,
it_bad=0 → ite_pttbl=1`. This causes PT0X to always return `-32768`.

But LOADW does NOT set `ite_pttbl=1` for this file — the reference has a mix of
PT0X values, not all `-32768`.

## Why `-32768`, `-16384`, `0` Don't Come from Any PTTBL cbox

Full-file scans at every byte offset found **no PTTBL base** where:
- pttbls[16].cbox.y = 0x80 (for M1SPDU1 PT0X=-32768)
- pttbls[22].cbox.y = 0xC0 (for M1SPDU3 PT0X=-16384)
- pttbls[18].cbox = 0 (for M2DKDU1 PT0X=0)

...simultaneously. These values do not co-exist at any consistent PTTBL base.

## Things Already Tried (All Failed)

| Attempt | Result |
|---------|--------|
| Standard pttbl_ofs (pal_ofs + palcnt*26 + 6 + n_seqscr*98) | cbox = (0x1c,0x00)=28 etc. |
| IT.EXE pttbl position | cbox = (0x00,0x00)=0 for all |
| std without seqscr skip (pal_ofs + palcnt*26 + 6) | cbox = 0 for all |
| std + n_special shift (std_ofs - n_special*40) | W3PLDDU15 matches; rest don't |
| IT + n_special shift (it_ofs - n_special*40) | M2DKDU1, W3PLDDU14 match; rest don't |
| pttblnum+n_special indexing at IT pos | no match |
| 16-bit offset wrapping | std/it offsets are 0xACF8/0xAE54 — no wrap |
| Changing heuristic threshold to n_palettes > 4 | Correctly prevents ite_pttbl=1 for DNK2, but standard pttbl gives wrong PT2X/PT3X too → more total diffs |

## Key Observation: Pattern in Reference Values

Reference PT0X for NBA_DNK2 images:
- `0`: M2DKDU* (pttblnum=17-33), M3TUKDU* (28-44), W3SPRDU13-14
- `-32768`: M1SPDU* 1,2,9-20, S1TUKDU1-2,7-8, M3SPRDU*, W3FLDU1-11 etc.
- `-16384`: M1SPDU3-8, S1TUKDU3-6,9-11, W3FLDU12-13, W3SPNDU4-9

There are exactly **3 groups** by pttblnum range. Within M1SPDU: pn=16 (ref=-32768),
pn=17 (ref=-32768), pn=22 (ref=-16384). The breakpoint between -32768 and -16384
doesn't align cleanly with any pttblnum threshold or n_special boundary.

## Promising Untried Hypotheses

1. **Different n_special detection**: LOADW may count n_special differently (e.g.
   checking for `flags & some_bit` rather than `name[0]=='!'`). If n_special=0 for
   NBA_DNK2 per LOADW's logic, the pttbl pointer is not shifted, giving different
   lookups.

2. **Different seqscr skip size**: The seqscr entry size might not be exactly 98
   bytes in LOADW's computation. If LOADW uses a different stride, `it_pttbl_ofs`
   lands at a different location that has the right cbox data.

3. **IT.EXE heuristic simply never fires**: Maybe the condition `n_palettes > 3` is
   actually `n_palettes > 5` or some other value not yet tested, meaning ite_pttbl=0
   always for NBA_DNK2, AND the standard PTTBL position DOES have the right cbox
   data — but at a base we compute wrongly because the `6` in `pal_ofs + n_pal*26 + 6`
   is wrong (could be 4, 8, etc.) or n_seqscr skipping uses a different header size.

4. **ite_pttbl=1 IS correct but PT0X code differs**: In IT.EXE mode, LOADW may not
   return -32768 unconditionally — it might compute PT0X from a different field.
   Our `if (g.ite_pttbl) return -32768;` may be wrong. The 3-way split (-32768,
   -16384, 0) could come from reading cbox.y at the IT.EXE pttbl position where
   cbox.y is 0x80, 0xC0, or 0x00 for different pttblnums. But we already checked
   IT.EXE cbox for those pttblnums — all zero. Unless a DIFFERENT PTTBL stride is used.

## Next Investigation Steps

1. **Check BB5_OUT.TXT more carefully**: the out file doesn't have verbose PTTBL data
   but might have clues about which files triggered "IT.EXE" mode.

2. **Find the PTTBL setup in LOADW_0800.asm**: The heuristic is near the 0xABCD
   checks. Already found `cmp word ptr es:[0FF26h],634h` at lines 7692 and 7776.
   The code around line 4A90 (after the ABCD checks) shows palette/PTTBL allocation.
   Need to trace the actual pttbl_ofs computation for n_seqscr > 0 case.

3. **Vary the seqscr header size**: Try 0x60=96, 0x64=100, 0x68=104 instead of 98.

4. **Check the 6-byte gap**: `pal_ofs + n_pal*26 + 6` — try 0, 2, 4, 8 instead of 6.

5. **Run LOADW under DOSBox with NBA_DNK2 and capture debug state**: add breakpoints
   at the PTTBL computation to read the actual pointer value.

## Assembly Entry Points

`LOADW_0800.asm` contains the relevant function starting around line 4A90 (fn0800_4A90).
The 0xABCD check at line 7863 is in the PTTBL allocation path. Lines 7880-7890 show
the n_seqscr (bp-6h) loop counting, and line 7892 shows `push 62h` (98-byte alloc).
The PTTBL setup should be after line 7863.

## Fixed

- **PT0X: read x1 in IT.EXE mode**: PT0X should use `ie->pttbl->x1` (own entry), not `ie->pttbl_pt0x->cbox` (`pttbls[pn-3]`). The ref -32768/-16384/0 match x1 at IT position.
- **Per-image `ite_pttbl`**: saved from `img->ite_pttbl` to `ImageEntry->ite_pttbl` so the IT/standard selection persists across IMG file loads. Global `g.ite_pttbl` was being overwritten by subsequent IMG loads.
- **`img->ite_pttbl` set**: Now saved during `img_load` when heuristic fires. Was never set before.
- **BB5 PLYRDSP** fixed: 5/7 → 6/7.

## Remaining: PLYRDSEQ / PLYRDSQ2

- BB5 PLYRDSEQ and BB6 PLYRDSQ2 still fail (PT0X=0 vs -32768/-16384).
- Images come from `NBA_DNK*.IMG` files with `n_seqscr=0`, so the heuristic never runs.
- The standard PTTBL position gives cbox=0 → PT0X=0 (wrong). The IT position gives x1=-32768 (correct).
- Extending heuristic to n_seqscr=0 works for NBA_DNK but breaks BB4 (NBA_MSC1 has same `std_bad=1, it_bad=0` pattern but needs standard position).
- No reliable discriminator found between files needing IT vs standard for n_seqscr=0 case.
