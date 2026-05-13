# LOAD.EXE /OLD Mode — Legacy Game Support

This document describes the `/OLD` flag implementation for supporting legacy
Williams/Midway games (Narc, Trog) that use the original **LOAD.EXE** toolchain
(pre-DMA2, pre-LOADW). These games target DMA1 hardware and use different
encoding, output format, and directives than the DMA2-based games (MK, NBA Jam).

---

## /OLD Mode Overview

Enabled with the `/OLD` CLI flag. Changes behavior in several areas:

| Area | /OLD Behavior | Modern (LOADW) Behavior |
|------|---------------|-------------------------|
| Default IHDR | `SIZX,W,SIZY,W,ANIX,W,ANIY,W,SAG:L,PAL:L` | `SIZX,W,SIZY,W,ANIX,W,ANIY,W,SAG:L,CTRL:W,PAL:L,PWRD1:W,PWRD2:W,PWRD3:W,PT3Y:W` |
| Default bpp | **8** (forced, LOAD.EXE behavior) | Auto-detected from max pixel value |
| ZON/ZOF | Ignored (DMA1 has no compression) | Active |
| Encode width | `IMG_STRIDE(w)` (always 4-byte aligned) | `OUT_STRIDE(w)` (depends on `/P`) |
| TBL SIZX | `/OLD1`: raw `w`, `/OLD2`: `IMG_STRIDE(w)` | `OUT_STRIDE(w)` (depends on `/P`) |
| SAG/PAL output | Combined on same `.long` line | Separate `.long` lines |
| RLC> directive | Supported (2bpp RLE) | Not supported |
| `+META` entries | Stripped for IMG lookup | Processed as-is |

---

## IHDR Format

The default IHDR in `/OLD` mode is:
```
IHDR SIZX:W,SIZY:W,ANIX:W,ANIY:W,SAG:L,PAL:L
```

The TBL output for each image is:
```asm
IMAGE_NAME:
    .word   SIZX, SIZY, ANIX, ANIY
    .long   0<SAG>H,<palette_name>      ; SAG and PAL on SAME line
```

When `POF>` is active, PAL is omitted entirely and SAG stands alone:
```asm
    .long   0<SAG>H
```

---

## RLC Run-Length Code (Narc)

RLC is a 2bpp run-length encoding used by the original LOAD.EXE for 4-color
images in DMA1-era games (Narc). Enable with the `RLC>` directive.

### Format

The encoding is confirmed by the `UnpackRLC` routine in `NARCMUGS.ASM`:

```
[1][rrrrr][cc]  = run of N pixels of 2-bit color cc
  r = 0      → N = 68 pixels
  r = 1..31  → N = r + 3  (4..34 pixels)
  cc          = 2-bit color value (0-3)

[00][c2][c1][c0] = 3 literal 2-bit pixels
  c0 = pixel 0 (bits 1-0)
  c1 = pixel 1 (bits 3-2)
  c2 = pixel 2 (bits 5-4)
```

Key properties:
- **Flat encoding**: Runs can span row boundaries (image treated as a single
  pixel strip of `w × h` pixels)
- **Pixel stride**: Reads `w` pixels per row from a stride-width buffer
  (`IMG_STRIDE(w)` bytes per row)
- **The decoder stops at `ISIZEX × ISIZEY` pixels** — any extra trailing bytes
  are ignored
- **Destination is bit-addressable** (2bpp pixels)

### Quantization

The 8bpp→2bpp color reduction is image-specific. The exact algorithm LOAD.EXE
uses is undocumented. Our implementation uses `pixel & 3` (low 2 bits), which
produces correct RLC-formatted data but may differ from the reference in
color mapping at stride boundaries (3-padding-pixel transitions).

### Implementation

The `UnpackRLC` decoder in `NARCMUGS.ASM` (line 2246):
1. Reads `ISIZEX × ISIZEY` from image frame (A0)
2. Reads RLC bytes from `ISAG` address (A6)
3. Writes 2bpp pixels to destination (A2)
4. Has a long-run optimization (≥16 pixels → word-expand the color)
5. Clamps overlong runs to remaining pixel count

The encoder (`rlc_encode` in `src/loadimg.c`):
1. Reads `w × h` pixels from stride-width source buffer
2. Reduces to 2bpp via `pixel & 3`
3. Encodes runs ≥4 pixels or literals of 3 pixels
4. Uses flat encoding (runs can span rows)

### RLC> Directive

The `RLC>` directive toggles RLC encoding on/off in the LOD file:
```
RLC>            ; enable RLC
---> img1,img2  ; these use RLC encoding
RLC>            ; disable RLC
```

---

## +META Variant Names (Trog)

Trog `--->` lines use a `NAME+META` syntax:
```
---> SPSTP0+STP0L,SPWAP4F1
```

The `+STP0L` suffix is a **display modifier** — it provides alternate display
parameters (animation frame metadata) for the base image. LOAD.EXE:

1. Strips the `+META` suffix for IMG record lookup (`SPSTP0` → look up `SPSTP0`)
2. Outputs the TBL entry with the **base name** (`SPSTP0:`), not the full name
3. Uses the base image's pixel data

### Suffix Sharing

`+META` entries with the **same suffix on the same `--->` line** share a
single SAG (size 0 for all but the first). Example:
```
---> GWENHL1+GHL1L,GWENHC1+GHL1L,GWENHC2+GHL1L,GWENHU1+GHL1L
```
All four use `+GHL1L`. Only `GWENHL1` is encoded; the other three reuse its SAG.

`+META` entries with the **same suffix on DIFFERENT `--->` lines** each encode
independently (different lines → different source IMG files → different pixel
data).

### Derived Images

Some `+META` entries reference a base name that does **not exist** in any IMG
file (e.g., `BLOOVHAND2+VHAND2L` where `BLOOVHAND2` has no IMG record). In the
reference output, these still have a SAG and pixel data — LOAD.EXE must
generate them from other sources (possibly by transforming the previously
processed image). This behavior is not yet implemented.

---

## SEQ/SCR Data

The IMG container format includes sequence (`seqcnt`) and script (`scrcnt`)
entries between the palette records and PTTBL. For old-format IMGs (version
< 0x654):

- SEQ entries: 98 bytes each, frame data at offset 20
- Format differs from the documented `wmpstruc.inc` structure:
  - Sequence names appear at varying offsets within the 98-byte block
  - Frame entry format is not simple (index, duration) pairs
- Some sequence data is stored OUTSIDE the SEQ/SCR area (e.g., SPBOING*
  sequences in TROG5.IMG are in the pixel data section)
- Sequences can reference images across multiple IMG files

The `orig_seqcnt` and `orig_scrcnt` fields are saved in the `ImgFile` struct
before the old-format conversion zeros them, enabling future SEQ processing.

---

## BBB Backgrounds

The `BBB>` directive processes BLIMP background files (`.BDB` + `.BDD`).
In `/OLD` mode, background images use the same 8bpp stride-padded encoding
as regular images. Background image data contributes to the IRW bitstream
and affects SAG offsets for subsequent images.

---

## Trog Reference Output

The `reftrog/` directory contains LOAD.EXE reference output for Trog:

| File | Content | Matching |
|------|---------|----------|
| `IMGTBL.ASM` | Main image table | 341/343 labels match (2 missing from BBB) |
| `TROGDDAT.TBL` | Sprite data table | SAGs match for first 400 entries |
| `TROGSPRG.TBL` | Sprite program table | ALL SAGs MATCH |
| `TROGWHL.TBL` | Wheel table | ALL SAGs MATCH |
| `TROGTEXT.TBL` | Text table | ALL SAGs MATCH |
| `IMGTBL.GLO` | Global symbols | .globl entries missing (not yet implemented) |
| `BGNDTBL.GLO` | Background globals | PASS |
| `IMGASEQ.ASM` | Animation sequences | Not yet generated (SEQ format needs research) |
| `IMGSRC.ASM` | Raw pixel source data | Not yet generated |

### Remaining Differences

| Issue | Scope | Root Cause |
|-------|-------|------------|
| **-1764B cascade** | IMGTBL.ASM at image 6 | Cumulative IRW size difference from intermediate images; same class as CMP=1 encoder cascade |
| **Motorola `>` format** | All .TBL/.ASM files | Different hex prefix style (cosmetic) |
| **BLOOVHAND2 missing** | IMGTBL.ASM SAG[62] | Derived image from `+VHAND2L` modifier; base name doesn't exist in any IMG |
| **SEQ output** | IMGASEQ.ASM | Old-format SEQ structure differs from documented format |
| **IMGSRC.ASM** | Raw pixel data | Not yet implemented |

---

## Narc Reference Output

The `refnarc/` directory contains LOAD.EXE reference output for Narc:

| File | Content | Notes |
|------|---------|-------|
| `NARCMUGS.TBL` | Mugshot image table | All 16 images present; SAG values match for filestxt |
| `IMGTBL.ASM` | Main image table | Comparison pending |

---

## Known Limitations

1. **Image concatenation** (`+META` operator): Cross-line same-suffix sharing
   not fully implemented
2. **Derived images**: Images whose base name doesn't exist in any IMG file
   can't be generated
3. **Motorola ASM syntax**: Our output uses Intel `H` suffix instead of
   `>` prefix — cosmetic only
4. **IMGASEQ.ASM**: SEQ data processing not yet implemented for old-format IMGs
5. **IMGSRC.ASM**: Raw pixel data not generated
