# loadimg — Williams/Midway Arcade Image Loader

A modern replacement for the MS-DOS **LOAD2.EXE** / **LOADW.EXE** (Williams Electronics Games Inc., 1993–1995) toolchain. Reads `.lod` script files and `.img` container files from arcade hardware and outputs `.tbl`/`.asm`/`.glo`/`.irw` files targeting the **TMS34020 GSP DMA2** graphics co-processor.

**Supported games:** Mortal Kombat 2, NBA Jam, NBA Jam Tournament Edition, Hangtime.

---

## Table of Contents

- [What It Does](#what-it-does)
- [Build Instructions](#build-instructions)
- [Usage](#usage)
- [Output Files](#output-files)
- [The LOD/IMG Pipeline](#the-lodimg-pipeline)
- [Test Suite](#test-suite)
- [Known Issues & Quirks](#known-issues--quirks)
- [Reverse Engineering](#reverse-engineering)
- [Credits](#credits)

---

## What It Does

The Midway arcade toolchain stored game sprites and backgrounds in **IMG container files** — a format with palette records, image headers (position, size, animation anchors), and 8-bit indexed pixel data. A **LOD script** tells the loader which images to extract, how to compress them (zero-run, uncompressed, or raw movie footage), and where to place them in the GSP's memory space.

**loadimg** reads these inputs and produces:

| File | Content |
|------|---------|
| `.TBL` | Assembly image tables — per-image SIZX, SIZY, SAG (bit offset), CTRL (DMA2 control word), palette reference, animation points |
| `IMGTBL.ASM` | Master table assembly, `.include`-ing all per-game TBL files |
| `IMGPAL.ASM` | Colour palette data as `.word` arrays (RGB565) |
| `IMGTBL.GLO` | Global symbol declarations for all labels |
| `.IRW` | Bit-packed compressed (or raw) image binary ready for DMA transfer |
| `BGNDTBL.ASM` / `BGNDPAL.ASM` / `BGNDEQU.H` | Background layer tables (from `BBB>` directive, MK2 stage backgrounds) |

The output is assembled by the TI TMS34010 toolchain (`gspa / gsplnk`) and GFX are burned into EPROMs for the arcade hardware.

---

## Build Instructions

**Dependencies:** C99 compiler, CMake ≥ 3.10. No external libraries (only libm on Linux).

### Linux

```bash
mkdir build && cd build
cmake ../src
make
```

### Windows (MinGW cross-compile)

A toolchain file is provided:

```bash
mkdir build_win && cd build_win
cmake ../src -DCMAKE_TOOLCHAIN_FILE=../src/toolchain-mingw.cmake
make
```

Native Windows builds with MSVC also work (set `CMAKE_C_STANDARD 99`).

---

## Usage

```
loadimg <lod_file> [flags]
```

| Flag | Effect |
|------|--------|
| `/T[=dir]` | Build TBL/ASM/GLO table files (optionally to directory) |
| `/F[=dir]` | Build IRW binary (optionally to directory) |
| `/X` | Skip IRW generation (TBL only) |
| `/I[=dir]` | Source image directory for `.IMG` files |
| `/D[=dir]` | LOD file directory |
| `/V` | Verbose output |
| `/E` | Dual-banked image memory (ED adjustment) |
| `/P` | Pad images to 4-bit boundary (stride alignment) |
| `/L` | Align images to 16-bit boundaries |
| `/B` | Derive bpp from pixel data, not palette size |
| `/3` | Limit LOD scales to 3 (full, half, quarter, no eighth) |
| `/A` | Append mode — append new entries to existing GLO/TBL files |

Output filenames derive from the LOD base name (uppercased):

```
loadimg MK2MIL.LOD /P /T
  → MK2MILIMG.TBL, IMGTBL.ASM, IMGTBL.GLO, IMGPAL.ASM
loadimg MK2MIL.LOD /F
  → MK2MIL.IRW
```

---

## Output Files

### TBL Format (Assembly)

```
        .DATA
        .word   2               ; scale count
IMAGE_NAME:
        .word   SIZX
        .word   SIZY
        .long   0<SAG>H         ; bit offset into IRW data section
        .word   0<CTRL>H        ; DMA2 control word
        .long   PALNAME         ; palette label
        .long   0<SAG_S1>H      ; scale 1 SAG
        .word   0<CTRL_S1>H     ; scale 1 CTRL
```

### IRW Format

| Offset | Content |
|--------|---------|
| `0x00` | ASCII date string (`03/14/95`) |
| `0x20` | Image count (uint16 LE) |
| `0x22` | Global bpp |
| `0x2e` | Flags (`0x02`) |
| `0x30` | Total file size (uint32 LE) |
| `0x44+` | Bit-packed image data (LSB-first) |

SAG values in the TBL are **bit offsets** from the start of the IRW data section (plus the base address from the `***>` directive).

### DMA2 CTRL Word

```
Bits [15:12]  PIX — pixel size (0=8bpp, 1-7=bpp)
Bits [11:10]  TM  — trailing-zero multiplier (0=×1, 1=×2, 2=×4, 3=×8)
Bits [9:8]    LM  — leading-zero multiplier (0=×1, 1=×2, 2=×4, 3=×8)
Bit  [7]      CMP — 1=ZON compression, 0=ZOF uncompressed
```

Each compressed row: 1 header byte `[trail_n:4][lead_n:4]` + stored pixels at `bpp` bits each, LSB-first. The hardware skips `lead_n × lm_mult` leading zeros and `trail_n × tm_mult` trailing zeros per row.

---

## The LOD/IMG Pipeline

1. **LOD Parsing** — Text script with directives (`ZON>`, `ZOF>`, `CON>`, `COF>`, `PPP>`, `XON>`, `ASM>`, `GLO>`, `***>`, `FRM>`, `BBB>`, `---->`) controlling compression mode, dedup, bpp, and image selection.

2. **IMG Loading** — Binary container with `LIB_HDR` (28 bytes), `IMG_REC` records (50 bytes each, 42 for old format), `PAL_REC` records (26 bytes), optional SEQ/SCR blocks, and PTTBL (point table) entries (40 bytes each). Pixel data is 8-bit indexed, row-stride aligned to 4 bytes.

3. **Two-Pass Encoding**:
   - **Pass 1** (`scan_bpp`): scans all `---->` image lists to determine global bpp (max pixel value), respecting `PPP>` override.
   - **Pass 2** (`process_lod`): for each image, analyzes the compression window (SIZX from PTTBL or image width), selects LM/TM multipliers via error-minimizing analysis (reverse-engineered from `FUN_1000_6f20`), encodes rows, writes TBL entries and palette data, and handles dedup (`CON>/COF>`) and `FRM>`/`BBB>` directives.

4. **IRW Writing** — Flushes the bit-packed header and data to disk.

---

## Test Suite

Run `make test` from the build directory. Compares all TBL/ASM/GLO/IRW output against LOADW reference files.

```bash
cd build && make test
```

### Current Results: 15 pass, 3 fail

| Test | Mode | TBLs | Result | Notes |
|------|------|------|--------|-------|
| **MK2MIL** | ZON + ZOF | 5/5 | PASS | IRW + TBLs byte-exact |
| **MK3MIL** | ZOF | 5/5 | PASS | IRW + TBLs byte-exact |
| **MK4MIL** | ZON | 6/6 | PASS | IRW + TBLs byte-exact |
| **MK5MIL** | ZON | 7/7 | PASS | IRW + TBLs byte-exact |
| **MK6MIL** | ZON/ZOF | 17/17 | PASS | All TBLs byte-exact |
| **MK7MIL** | Mixed | 11/11 | PASS | Background dedup fixed |
| **MK8MIL** | FRM | 1/1 | PASS | MKREVX.TBL match |
| **BB** | ZOF+XON | 2/2 | PASS | CMP=0 XON width fix |
| **BB2** | ZOF+XON | 3/3 | PASS | |
| **BB3** | ZOF+PT | 2/2 | PASS | PTTBL bounds fixed |
| **BB4** | ZOF+XON | 1/1 | PASS | |
| **BB5** | Mixed | 3/7 | FAIL | CMP=1 encoder cascade |
| **BB6** | Mixed | 5/6 | FAIL | CMP=1 cascade + PLYRDSQ2 PT fields |
| **BB7** | Mixed | 15/16 | FAIL | OUTDOOR SAG shift (pre-existing FRM alignment) |
| **BB8** | XON | 3/3 | PASS | |
| **BBMUG** | ZOF+XON | 2/2 | PASS | Dual-hash dedup fix |
| **BBVDA** | VDA | 1/1 | PASS | |
| **MISC** | Mixed | 21/21 | PASS | NBA Jam/Hangtime, dual-bank mode |

Reference files can be regenerated via `make regen` (requires DOSBox).

---

## Known Issues & Quirks

| Issue | Scope | Root Cause |
|-------|-------|------------|
| **CMP=1 encoder cascade** | BB5, BB6 | LM/TM/bpp selection differs from LOADW for compressed images. Affects compressed IRW output starting at some image, cascading ~3–31 bytes per TBL. MK2MIL/MK4MIL/MK8MIL are fully byte-exact, confirming the encoder is correct for those datasets. |
| **PLYRDSQ2 PT fields** | BB6 | PTTBL 40-byte stride aliasing reads pixel colour data for `x1` field, preventing geometry-based PT pair computation fallback. |
| **OUTDOOR 20-byte SAG shift** | BB7 | Pre-existing FRM/LEAF ZOF alignment difference in the NBA Jam dataset. |
| **16-bit checksum collisions** | LOADW (CON>) | LOADW's word-wise checksum misses the last byte of odd-length buffers, causing false dedup matches on `BBMUG` mugshots and `BB7` leaf sprites (`OUTDOOR`). Fixed in loadimg with a dual-hash (word-sum + byte-sum). |
| **PTTBL dense stride** | LOADW | PTTBL data stored at 12-byte stride in IMG files but LOADW reads at 40-byte stride, causing aliasing that reads palette colour data or IMG_REC name fields for high index entries. loadimg version-gates the SEQ/SCR skip and enforces a minimum SIZX threshold. |
| **BPP from stride-width** | LOADW | LOADW computes bpp from stride-width pixels (including padding bytes), not just image width. loadimg matches this behavior. |
| **FRM> word alignment** | LOADW | Movie footage (`FRM>`) uses word alignment *after* each entry, matching LOADW's byte-exact IRW layout. |
| **PAL_REC offset bug** | LOADW | Adding `n_special` again to palette offset caused a 100-byte overrun (2 records × 50 bytes). loadimg correctly uses `imgcnt` directly. |

The BB5/BB6/BB7 compressed encoder cascade is the primary remaining open issue. All MK2 datasets and NBA Jam/Hangtime ZOF/XON images pass fully.

---

## Reverse Engineering

The original **LOADW.EXE** (290 KB MZ executable, dated 5/25/94, Borland C++ 4.5) was decompiled with **Ghidra 12.0**. The binary contains COFF debug symbols preserving C function names and source file references (`load2.c`, `zcom.c`, `emm.c`, `ldbgnd2.c`).

### Key Decompiled Functions

| Function | Address | Purpose |
|----------|---------|---------|
| `_packbits` | `1000:5b64` | Main compression — lead/trail analysis, row encoding |
| `FUN_1000_6f20` | `1000:6f20` | Error-minimizing LM/TM multiplier selector |
| `_do_zcom` | `100a:fa02` | Zero-compression row writer |
| `_load_bits` | `1000:737c` | Bitstream I/O |
| `_compute_bpp` | `1000:35a1` | Bits-per-pixel calculation |
| `_create_point_table` | `1000:75e1` | PT pair output for TBL |
| `FUN_1854_35fc` | `1854:35fc` | Checksum computation (dedup) |
| `FUN_1854_1a49` | `1854:1a49` | BBB background processor |

### COFF Debug Symbols

Extracted via `strings` from the binary:

- `_packbits`, `_do_zcom`, `_load_bits`, `_compute_bpp`, `_create_point_table`
- `_write_palette`, `_write_row`, `_write_tbl`
- `_do_sclpad`, `_do_pad`, `_dataword`, `_do_table`, `_ctrl_word`
- `_zero_pad`, `_do_align0`, `_do_cksum`, `_do_superbpp`, `_color_average`

See `ghidra.md` for the full analysis guide and `compression.md` for the complete algorithm reference.

### Hardware Spec

The DMA2 compression format is documented in **`DMA2.DOC`** (Keep Enterprises, January 1992, Rev 1.5) — the official hardware specification for the Williams/Midway TMS34010 DMA co-processor.

### Format References

- **`wmpstruc.inc`** — Midway assembly struct definitions for IMG/PTTBL/SEQSCR
- **`agents.md`** — Full IMG container format specification, TBL output, PT pair computation, implementation status, and all known bug fixes
- **`bbb.md`** / **`bdd.md`** — BLIMP background format (BDB/BDD) specification
- **`compression.md`** — DMA2 ZON/ZOF compression algorithm, verified against Ghidra decompilation and LOADW verbose output

---

## Credits

The original LOADIMG was created by Warren B. Davis around 1988 for Y-Unit hardware. Possibly other developers updated it for Wolf Unit/DMA2. Thank you! You've made our lives better with the tools that helped build games that excited and shaped our life during the 80's and 90's. Without you, this would not exist!

- Based on reverse-engineering of **LOADW.EXE** (Williams Electronics Games Inc., 1993–1995, Borland C++ 4.5)
- DMA2 hardware documentation: **Keep Enterprises**, Jan 1992
- Original struct definitions: **Midway Manufacturing** (`wmpstruc.inc`, `itimg.asm`)
- Test data extracted from **Mortal Kombat 2**, **NBA Jam**, **NBA Jam Tournament Edition**, and **Hangtime** arcade ROMs
