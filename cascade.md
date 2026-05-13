# CMP=1 Encoder Cascade

This document describes the CMP=1 encoder cascade — the primary remaining open
issue in LOADW byte-exact matching. The cascade affects compressed (ZON mode,
CMP=1) images in the NBA Jam/Hangtime dataset (BB5, BB6, BB7) and some WWF
images.

---

## Quick Reference

```bash
# Run an affected test
cd workArt
../build/loadimg BB5.LOD /P /T /V

# Run all suite tests
cd .. && bash test.sh
```

---

## Affected Tests

| Test | Mode | TBLs | Result | Notes |
|------|------|------|--------|-------|
| **BB5** | Mixed | 7/7 | **PASS** | PT0X sentinel fixed: reads `flags` in IT.EXE mode |
| **BB6** | Mixed | 6/6 | **PASS** | PT0X sentinel fixed: reads `flags` in IT.EXE mode |
| **BB7** | Mixed | 15/16 | FAIL | OUTDOOR LEAF8 unused image, ref dedup bug |
| **BAM** | SEQ | 0/1 | FAIL | WWF /SEQ mode not yet implemented |

### BB5 TBL List (refArt)

`PLYRDSP PLYRDSEQ STAND PLYRSEQ2 PLYRSEQ3 PLYRJSHT PLYRMAKE`
- Passing: `PLYRDSP STAND PLYRSEQ2 PLYRSEQ3 PLYRJSHT PLYRMAKE`
- Failing: `PLYRDSEQ` (PT0X sentinel: -16384 vs -32768, cosmetic)

### BB6 TBL List (refArt)

`NAMES2 PLYRDSQ2 NCKNME PRIVLG CHEER PLYRHD6A`
- Passing: `NAMES2 NCKNME PRIVLG CHEER PLYRHD6A`
- Failing: `PLYRDSQ2` (2 cosmetic PT0X sentinel diffs)

### BB7 TBL List (refArt)

`ARROW MUGSHOT HOTSPOT BALLSHAD BALL LOGOS CREDTURB CREDIT HOOP COURTFLR HANGFONT BASTCYC PLYRNUB PRIZES POWERTXT OUTDOOR`
- Passing: all except `OUTDOOR`
- Failing: `OUTDOOR` (pre-existing LOADW false dedup — ref has wrong LEAF pixels)

### BAM TBL List (refwwf)

`BAMIMG`

---

## What the Cascade Is

A SAG cascade occurs when one image's compressed size differs between our
output and the reference. Each subsequent image's SAG offset shifts by the
difference, causing all later TBL entries to mismatch.

The cascade ALWAYS starts at a CMP=1 (ZON-compressed) image. CMP=0 (ZOF)
images are byte-exact. All- ZON tests (MK2MIL, MK4MIL, MK5MIL, MK6MIL) and
all-ZOF tests (MK3MIL, BB, BB2, BB4, BB8) pass 100%.

### Cascade Symptoms

- First mismatching TBL entry has wrong SAG or CTRL
- All subsequent entries also have wrong SAG (offset accumulates)
- CTRL differences indicate LM/TM/bpp selection diverges
- SAG-only differences indicate same LM/TM but different compressed size

---

## Pipeline Architecture

### Two-Pass Encoding

1. **Pass 1** (`scan_bpp` at src/loadimg.c:1997): scans all `--->` image lists
   to determine global bpp (max pixel value), respecting `PPP>` override.

2. **Pass 2** (`process_lod` at src/loadimg.c:2084): for each `--->` image:
   - Determine per-image bpp (PPP override, auto pixel packing, or global bpp)
   - Compute compression window SIZX from PTTBL or `OUT_STRIDE(rec->w)`
   - **`analyze_image()`** → selects LM/TM multipliers via FUN_1000_6f20
     error-minimizing algorithm
   - **`encode_image()`** → encodes all rows to IRW bitstream
   - Write TBL entry (SAG, CTRL, etc.)
   - Handle dedup (`CON>/COF>`) via checksum table

3. **IRW Writing** (`write_irw`): flush 0x44-byte header + bit-packed data.

### The LOD File Controls

```
ZON>   — Enable zero-run compression (CMP=1 allowed)
ZOF>   — Disable zero-run compression (CMP=0 forced)
PPP> N — Force N bits per pixel (1-8), 0 = auto
CON>   — Enable checksum dedup
COF>   — Disable checksum dedup
XON>   — Extra zero pixel column (adds +1 to SIZX/SIZY)
```

BB5/BB6/BB7 LODs toggle these modes mid-file. The cascade starts when the
tool's CMP=1 encoding produces a different compressed size than LOADW for
the first ZON image after a mode switch.

---

## Key Functions

### analyze_image (src/loadimg.c:825-999)

Selects LM/TM multipliers, computes CTRL word, determines CMP flag.

**First pass — per-row lead/trail counting:**

```c
for (int x = 0; x < sizx; x++) {
    uint8_t px = (row && x < stride) ? row[x] : 0;
    if (!lead_done) {
        if (lead == 120)          lead_done = 1;
        else if (px == 0)         lead++;
        else                      lead_done = 1;
    } else if (sizx - 120 < x) {
        if (px == 0)              trail++;
        else                      trail = 0;
    }
}
```

- **Lead capped at 120** (0x78) — matches FUN_1000_6f20 bVar8
- **Trail only after lead finishes** — `else if` ensures trail is never
  counted alongside lead
- **Trail condition** `sizx - 120 < x` — always true for sizx ≤ 120
- **Trail resets to 0** on first non-zero pixel from the right
- **Zero-padded** beyond rec->w

**Error accumulation:**

```c
for (int m = 0; m < 4; m++) {
    int mult = 1 << m;
    int ln = lead / mult; if (ln > 15) ln = 15;
    lead_err[m] += lead - mult * ln;
    int tn = trail / mult; if (tn > 15) tn = 15;
    trail_err[m] += trail - mult * tn;
}
```

**LM/TM selection:**

```c
int best_lm = 0;
for (int m = 1; m < 4; m++)
    if (lead_err[m] < lead_err[best_lm]) best_lm = m;
int best_tm = 0;
for (int m = 1; m < 4; m++)
    if (trail_err[m] < trail_err[best_tm]) best_tm = m;
```

- LM: strict `<` (lower index wins on tie)
- TM: strict `<` (lower index wins on tie)

**Second pass — space check:**

```c
comp_bits = sum over all rows of (8 + stored * bpp)
raw_bits = sizx * rows * bpp
do_cmp = (sizx >= 10 && comp_bits <= raw_bits)
```

Two conditions for CMP=1:
1. `sizx >= 10` — "Need 10 non-zero pixels minimum"
2. `comp_bits <= raw_bits` — compressed must be smaller or equal (`<=`
   means equal → NOT compressed)

### encode_row (src/loadimg.c:1005-1092)

Per-row ZON encoding. Same lead/trail counting as analyze_image, then:

```c
int lead_n = lead / lm_mult; if (lead_n > 15) lead_n = 15;
int lead_c = lead_n * lm_mult; if (lead_c > sizx) lead_c = sizx;
int trail_n = trail / tm_mult; if (trail_n > 15) trail_n = 15;
int trail_c = trail_n * tm_mult;
if (lead_c + trail_c > sizx) trail_c = sizx - lead_c;
int stored = sizx - lead_c - trail_c; if (stored < 0) stored = 0;
```

Minimum stored = 10 adjustment (applied when `stored < 10`):
- Reduces lead_c (from left) to borrow pixels
- Reduces trail_c (from right) to borrow more if needed
- Recomputes lead_n, trail_n from adjusted lead_c, trail_c
- Edge case: if sizx - 10 < 10, the adjustment can consume the entire row

### encode_image (src/loadimg.c:1157-1220)

Creates SIZX-stride internal buffer (`_do_sclpad`), then per-row:

```c
for (int y = 0; y < rows; y++) {
    uint8_t *row = (g.zon && do_cmp) ? scl_buf + y * scl_stride
                                     : pix + y * img_stride;
    if (g.zon && do_cmp)
        encode_row(row, scl_stride, scl_stride, bpp, cp->lm_mult, cp->tm_mult, &running_lead);
    else
        // CMP=0: raw pixel packing at OUT_STRIDE(w) width
}
```

### compute_ctrl (src/loadimg.c:772-775)

```c
static uint16_t compute_ctrl(int bpp, int lm, int tm, int cmp) {
    uint16_t pix = (bpp == 8) ? 0 : (uint16_t)bpp;
    return (pix << 12) | (tm << 10) | (lm << 8) | (cmp ? 0x80 : 0);
}
```

### CTRL Word Layout (from DMA2.DOC)

```
Bit  [15]     DGO — DMA Go (always 0 in TBL)
Bits [14:12]  PIX — pixel size (0=8bpp, 1-7=bpp)
Bits [11:10]  TM  — trailing-zero multiplier (0=x1, 1=x2, 2=x4, 3=x8)
Bits [9:8]    LM  — leading-zero multiplier (0=x1, 1=x2, 2=x4, 3=x8)
Bit  [7]      CMP — compression enable (1=ZON, 0=ZOF)
```

### BPP Determination (src/loadimg.c:1644-1695)

Priority:
1. `PPP> N` forces bpp (with palette overflow check)
2. `/OLD` mode → 8bpp
3. Auto pixel packing: per-image from max pixel over STRIDE-width
   (not rec->w). Scans stride-width pixels per row, matching
   LOADW's `_compute_bpp`.

Note: stride-width bpp scanning was fix #32 in agents.md. Before this fix,
BB6 CHEER got bpp=4 (from rec->w pixels) but reference had bpp=7 (from
stride-width pixels including padding artifact pixel 96). Match went from
3/6 → 5/6 after the fix.

### Dedup Logic (src/loadimg.c:1897-1963)

```c
// Checksum over stride-padded pixel data
uint16_t ck = loadw_checksum(pix_data, pstride, rec->w, rec->h, &max_val);
// Byte-sum for collision disambiguation
uint16_t ck2 = 0;
for (int i = 0; i < pix_bytes; i++)
    ck2 = (uint16_t)(ck2 + pix_data[i]);

// 6-field key: {sum, max_val, sizx, sizy, ctrl, sum2}
for (int di = 0; di < n_dedup; di++) {
    if (dedup_table[di].sum == ck && dedup_table[di].max_val == max_val &&
        dedup_table[di].sizx == cp.sizx && dedup_table[di].sizy == cp.sizy &&
        dedup_table[di].ctrl == cp.ctrl &&
        dedup_table[di].sum2 == ck2) {
        dedup_idx = di; break;
    }
}
```

If dedup hits, image SAG is reused — no IRW data written. This means dedup
can mask encoding differences (if two images dedup against each other but
shouldn't, or fail to dedup when they should).

BB7 OUTDOOR failure is a pre-existing LOADW false dedup bug — the reference
has wrong LEAF pixels because LOADW incorrectly deduplicated an image.

---

## BBB Background Compression (src/loadimg.c:2473-2688)

Backgrounds (from `BBB>` directive) use the same FUN_1000_6f20 algorithm
but with differences:

| Aspect | Sprite | Background |
|--------|--------|------------|
| SIZX | PTTBL BOX[1].W or OUT_STRIDE(w) | `sizx_a = OUT_STRIDE(w)` |
| PTTBL | Used for SIZX, PT pairs | None |
| BPP | Auto from maxpx or PPP> | Auto + unique-color bump |
| Dedup key | {sum, max_val, sizx, sizy, ctrl, sum2} | {sum, max_val, ctrl} |
| CMP=0 condition | sizx < 10 | w < 10 OR h < 10 |

Background dedup matches on `{sum, max_val, ctrl}` only — no sizx/sizy.
This is more permissive than sprites and could cause false dedup matches.

BBB cascade in Trog (`TROGCAVE.TBL` etc.): the 7 BBB backgrounds between
sprite images (TROGLOG, TROGISLE, TROGCAVE, TROGFUT1, TROGFUT2, TROGCRED,
TROGDSRT) have different compressed sizes, shifting all subsequent sprite
SAGs. This manifests as the cascade at IMGTBL.ASM entry [232] (BARL2).

---

## Debugging a Cascade

### Step 1: Find the first mismatching image

```bash
cd workArt
python3 << 'EOF'
import re
def parse_sags(path):
    sags = []
    for l in open(path):
        l = l.strip()
        m = re.search(r'\.long\s+[>0]?([0-9A-Fa-f]+)H', l)
        if m:
            sags.append(int(m.group(1), 16))
    return sags

ref = parse_sags('../refArt/PLYRSEQ2.TBL')
our = parse_sags('PLYRSEQ2.TBL')
for i, (r, o) in enumerate(zip(ref, our)):
    if r != o:
        print(f'First diff at SAG[{i}]: ref=0x{r:X} our=0x{o:X}')
        print(f'Difference: {r - o} bits ({abs(r-o)/8} bytes)')
        break
EOF
```

### Step 2: Check if it's SAG or CTRL

```bash
# If both SAG and CTRL differ: LM/TM/bpp selection diverged
# If only SAG differs (same CTRL): same LM/TM but different compressed size
diff ../refArt/PLYRSEQ2.TBL PLYRSEQ2.TBL | head -40
```

### Step 3: Find the preceding image in the LOD

```bash
# Find which image comes before the cascade start in the LOD
grep -n '--->' workArt/BB5.LOD | head -30
```

### Step 4: Extract verbose debug output for the diverging image

Add temporary debug prints in `analyze_image()` for the specific image:

```c
if (strcmp(name, "cascade_image_name") == 0) {
    fprintf(stderr, "lead_err: %d %d %d %d\n",
            lead_err[0], lead_err[1], lead_err[2], lead_err[3]);
    fprintf(stderr, "trail_err: %d %d %d %d\n",
            trail_err[0], trail_err[1], trail_err[2], trail_err[3]);
    fprintf(stderr, "bpp=%d sizx=%d sizy=%d\n", bpp, p.sizx, p.sizy);
}
```

### Step 5: Generate LOADW reference verbose output

See the "Regenerating Reference Output" section below. Use `/V5` to get
per-row lead/trail/error values from LOADW and compare directly.

---

## Regenerating Reference Output (DOSBox)

This procedure runs the original LOADW.EXE under DOSBox to generate
reference `.IRW`, `.TBL`, `.GLO`, and `.ASM` files for comparison.

### Prerequisites

- LOADW.EXE at `binary/LOADW.EXE`
- DOSBox installed (`which dosbox`)
- All required `.IMG`, `.BIN`, `.BDB`, `.BDD` files in `workArt/` or `work5/`

### One-Time Setup

```bash
mkdir -p /tmp/ref_test
cp binary/LOADW.EXE /tmp/ref_test/
cp workArt/<LOD>.LOD /tmp/ref_test/
cp workArt/*.IMG /tmp/ref_test/
cp workArt/*.BIN /tmp/ref_test/ 2>/dev/null
```

### Run LOADW in DOSBox

```bash
cat > /tmp/dosbox_ref.conf << 'CONF'
[dosbox]
machine=svga_s3
memsize=16
[cpu]
core=auto
cputype=auto
cycles=max
[autoexec]
mount c /tmp/ref_test
c:
md TMP
LOADW <LOD_BASENAME> /P /F=C:\TMP /T=C:\TMP /V5 > C:\TMP\OUT.TXT
exit
CONF
timeout 120 dosbox -conf /tmp/dosbox_ref.conf 2>&1 | tail -3
```

Flags:
- `/P` — pad to 4-bit boundary (required)
- `/F=C:\TMP` — IRW output directory
- `/T=C:\TMP` — TBL output directory
- `/V5 > C:\TMP\OUT.TXT` — verbose level 5 (includes per-row lead/trail/error)

**Important**: LOADW adds `.lod` extension automatically. Pass the basename
ONLY (e.g. `BB5` not `BB5.LOD`).

### Copy Reference Files

```bash
mkdir -p refArt
cp /tmp/ref_test/TMP/* refArt/
```

### Run loadimg and Compare

```bash
cd workArt
rm -f BB5.IRW *.TBL IMGTBL.ASM IMGTBL.GLO IMGPAL.ASM
../build/loadimg BB5.LOD /P /T
for f in ../refArt/*.TBL; do
    base=$(basename "$f")
    [ -f "$base" ] && diff "$f" "$base" >/dev/null 2>&1 \
        && echo "PASS $base" || echo "FAIL $base"
done
```

---

## Known Fixes Applied (relevant to cascade)

| Fix | agents.md ref | Effect |
|-----|---------------|--------|
| FUN_1000_6f20 lead/trail `else if` | 652-653, 776 | Fixed extra trailing pixel counted when lead cap hit at same iteration. BGSPEAR6 now matches. |
| TM `<=` fix | 775 | TM comparison restructured to match FUN_1000_6f20 |
| Stride-width bpp scanning | 777 | BB6 CHEER: stride padding artifact pixel 96 caused bpp=7 instead of 4 |
| PTTBL offset for v0x654+ | 779 | SEQ/SCR skip version-gated; BB7: 8/16 → 15/16 |
| Minimum SIZX threshold (10) | 780 | Avoids using STAND2 special entry box[0].w as compression width |
| PTTBL positioning via IT.EXE | 781 | SEQ/SCR skip confirmed from wmpstruc.inc struct layout |
| Dual-hash dedup (sum2) | 776 | Byte-sum collision disambiguation fixes BBMUG |

---

## PT0X Sentinel Value — FIXED

BB5 PLYRDSEQ and BB6 PLYRDSQ2 previously had PT0X differences: the
reference uses a 3-way split (`-32768`, `-16384`, `0`) while our tool
output `0` for all entries. This is now fixed.

**Root cause** (2 bugs):
1. `g.ite_pttbl` was a global overwritten by subsequent IMG loads — fixed
   by per-image `ie->ite_pttbl`.
2. The PT0X value in IT.EXE mode comes from the PTTBL `flags` field
   (offset 0), not `x1` (offset 2). `flags=0x8000` → `-32768`,
   `0xC000` → `-16384`, `0x0000` → `0`.

The heuristic was also extended to `n_seqscr=0` IMGs (NBA_DNK1 etc.)
with an IT validity check to avoid false positives.

## Current Test Results

| Test | Passing | Failing |
|------|---------|---------|
| **MK2-8MIL** | 7/7 all pass | — |
| **BB** | PASS | — |
| **BB2** | PASS | — |
| **BB3** | PASS | — |
| **BB4** | PASS | — |
| **BB5** | 7/7 | — |
| **BB6** | 6/6 | — |
| **BB7** | 15/16 | OUTDOOR (LEAF8 unused image, ref dedup bug) |
| **BB8** | PASS | — |
| **BBMUG** | PASS | — |
| **BBVDA** | PASS | — |
| **TROG** | 12/15 (9 TBLs + IMGPAL + IMGTBL.GLO + BGNDTBL.GLO) | IMGTBL.ASM (BBB face images), BGNDTBL.ASM (HDRS indices), BGNDPAL.ASM (FACEPALS) |
| **NARC1** | 20/21 | NARCMUGS (buggy LOAD.EXE ref, accepted) |
| **CARN** | 0/13 | TUNG3 dedup collision cascades all SAGs |
| **MISC** | 21/21 PASS | — |

**Overall: 15 pass, 7 fail** (v0.98)

## Remaining Investigation Questions

1. **Where does BB5 first diverge?** Find the first CMP=1 image in BB5
   whose compressed bit count doesn't match LOADW. Compare per-row lead_n,
   trail_n, stored, and comp_bits against LOADW `/V5` output.

2. **Is the divergence always at a CMP=1 image?** All-passing tests are
   either all-ZON, all-ZOF, or well-behaved mixed. The cascade starts at
   the first ZON image in a mixed section. Verify this theory.

3. **bpp selection edge case?** Stride-width bpp scanning fixed BB6 CHEER.
   Are remaining BB5/BB7 mismatches also bpp-related? Check if the first
   diverging image has bpp determined by auto pixel packing vs PPP>.

4. **LM/TM tie-breaking nuance?** The FUN_1000_6f20 Ghidra decompilation
   might have a subtle difference in tie-breaking (the original Borland C++
   compiled code may evaluate `<` vs `<=` differently for certain
   accumulator values).

5. **Minimum stored = 10 adjustment edge case?** The Ghidra decompilation
   of FUN_1000_6f20's second pass shows specific local variable
   transformations (`iVar6`, `iVar7`, `local_2c`, `iVar9`). Could the C
   implementation differ from the original Borland C++ 4.5 compiled code
   for edge cases where `sizx` is close to 10?

6. **Does the SCL buffer (sizx-stride) differ from IMG stride?** When
   PTTBL-based SIZX < IMG_STRIDE(rec->w), the SCL buffer in encode_image
   has a different row layout (narrower stride). Zero-padding beyond the
   copy width could produce different pixel values for rows where stride
   padding originally held non-zero garbage pixels. Compare SCL-buffer
   per-row pixel values against LOADW's internal `_do_sclpad` buffer.

7. **PT0X sentinel value**: BB5 PLYRDSEQ and BB6 PLYRDSQ2 both have
   cosmetic PT0X differences. Reference uses -16384 (0xC000) or 0 as
   sentinel for "no valid PT0X from shared entry 3 back", our tool uses
   -32768 (0x8000). The IHDR_PT0X handler in `get_ihdr_word_value()` needs
   its fallback logic adjusted to match LOADW's sentinel convention.

8. **Dedup masking encoding differences?** If LOADW deduplicates an image
   (reuses SAG from an earlier identical image), but our tool misses the
   dedup (e.g., CTRL doesn't match due to LM/TM selection), our tool
   encodes new IRW data. This creates a cascade when the dedup miss causes
   extra data in the IRW stream. Look for images where our tool encodes
   but the reference reuses an earlier SAG.

---

## File Reference

| File | Description |
|------|-------------|
| `src/loadimg.c:825-999` | `analyze_image()` — LM/TM selection, space check |
| `src/loadimg.c:1005-1092` | `encode_row()` — per-row ZON encoding |
| `src/loadimg.c:1157-1220` | `encode_image()` — image-level encoding |
| `src/loadimg.c:772-775` | `compute_ctrl()` — CTRL word construction |
| `src/loadimg.c:1644-1695` | Per-image bpp determination |
| `src/loadimg.c:1897-1963` | Dedup lookup and store |
| `src/loadimg.c:1997-2067` | `scan_bpp()` — global bpp pass |
| `src/loadimg.c:2084-1994` | `process_lod()` — main encoding loop |
| `src/loadimg.c:2473-2688` | BBB background encoding |
| `workArt/BB5.LOD` | Test LOD (first diverge) |
| `workArt/BB6.LOD` | Test LOD (PLYRDSQ2 sentinel) |
| `workArt/BB7.LOD` | Test LOD (OUTDOOR false dedup) |
| `refArt/PLYRSEQ2.TBL` | Reference TBL (first diverge in BB5) |
| `refArt/OUT.TXT` | LOADW verbose output (if available) |
| `binary/LOADW.EXE` | Original MS-DOS tool |
| `compression.md` | Full algorithm reference |
| `agents.md` | Implementation status and fix history |

---

