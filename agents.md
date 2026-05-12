# loadimg — Agent Reference

Williams/Midway arcade image loader replacement for the MS-DOS LOAD2/LOADW tool (Williams Electronics Games Inc., 1995). Reads `.lod` script files and `.img` container files, outputs `.tbl`/`.asm`/`.glo`/`.irw` files for TMS34020 GSP hardware.

All LOD test files (MK2MIL through MK8MIL) are from **Mortal Kombat 2** arcade data. The naming convention (MK4MIL = MK2 ROM bank 4, etc.) reflects the EPROM bank that the IRW data targets, not different game revisions.

---

## IMG Container Format

### File Layout

IMG files use a **data-first** layout. The metadata directory is at the end, pointed to by the OSET field:

```
[LIB_HDR 28 bytes][pixel data + palette color data ... ~986KB][IMAGE records at OSET][PAL_REC records]
```

The data section immediately after the header begins with RGB565 palette color values (e.g. `0xff7f`), not struct records.

### LIB_HDR (28 bytes, `#pragma pack(2)`)

| Field   | Type     | Notes |
|---------|----------|-------|
| imgcnt  | uint16   | Total image record count, **including** special `!` records |
| palcnt  | uint16   | Number of palette records |
| oset    | uint32   | File offset to start of IMAGE records |
| version | uint16   | e.g. `0x64e`; old format uses `0x634` |
| seqcnt  | uint16   | Number of sequence (SEQSCR) entries |
| scrcnt  | uint16   | Number of script entries |
| damcnt  | uint16   | Number of damage table entries |
| temp    | uint16   | Magic value `0xabcd` (validation) |
| bufscr  | uint8[4] | |
| spare1-3| uint16   | |

### IMG_REC (50 bytes, `#pragma pack(2)`)

| Field    | Type   | Notes |
|----------|--------|-------|
| name     | char[16] | Sprite name, space-padded. `!` prefix = special record (palette ref, stand-in) |
| flags    | uint16 | e.g. `0x4` |
| anix     | int16  | Animation anchor X |
| aniy     | int16  | Animation anchor Y |
| w        | uint16 | Pixel buffer width (8bpp stride width, multiple of 4) |
| h        | uint16 | Pixel buffer height |
| palnum   | uint16 | Index into palette table |
| oset     | uint32 | File offset to pixel data (8bpp, row stride = `(w+3)&~3`) |
| data_p   | uint32 | Runtime data pointer (zero in file) |
| lib      | uint16 | Library index |
| anix2    | int16  | |
| aniy2    | int16  | |
| aniz2    | int16  | |
| frm      | uint16 | |
| pttblnum | int16  | Point table index; `-1` = none |
| opals    | uint16 | Usually `0xffff` |

**Special records:** Records whose names start with `!` (e.g. `!STAND2`, `!STAND4`) are counted in `imgcnt` but excluded from the image list. `n_special` is determined by counting leading `!`-prefix records; `n_images = imgcnt - n_special`.

**Critical offset rule:** `pal_start = oset + imgcnt * sizeof(IMG_REC)`. Do **not** add `n_special` again — `imgcnt` already includes them. Adding `n_special` was a confirmed bug that produced a 100-byte error (2 records × 50 bytes).

### PAL_REC (26 bytes, `#pragma pack(2)`)

| Field   | Type      | Notes |
|---------|-----------|-------|
| name    | char[10]  | Palette name (e.g. `YOKRED_P`) |
| flags   | uint8     | |
| bitspix | uint8     | Bits per pixel (e.g. 6 or 8) |
| numc    | uint16    | Number of colors |
| oset    | uint32    | File offset to color data |
| data_p  | uint16    | Runtime pointer |
| lib     | uint16    | |
| colind  | uint8     | |
| cmap    | uint8     | |
| spare   | uint16    | |

Color data is RGB565 16-bit values stored inline at `pal->oset`.

### PTTBL (Point Table, `#pragma pack(1)`)

Authoritative layout from `IT/wmpstruc.inc`. Located after PAL_RECs in the file (skip SEQSCR/SCR blocks first when seqcnt/scrcnt > 0).

```c
// PTBOX: all fields unsigned
// X = left edge (pixel column, 0-based)
// Y = top edge (pixel row, 0-based)
// W = box width − left_edge  (= right_x − X, stored as offset not absolute)
// H = box height − top_edge  (= bottom_y − Y, stored as offset not absolute)
typedef struct { uint8_t x, y, w, h; } PTBOX;   // 4 bytes

typedef struct {
    uint16_t flags;
    int16_t  x1, x2, x3;       // PWRD1/2/3 — packed collision / custom data
    int16_t  x_anipt3, y_anipt3, z_anipt3;  // 3rd animation point
    uint16_t id;                // PT3Y / misc
    PTBOX    box[5];            // up to 5 hit/display boxes
    PTBOX    cbox[1];           // collision box
} PTTBL;   // 40 bytes total
```

Each `IMAGE` record has a `pttblnum` field (int16, −1 = no table). This is an index into the full record array (including `!`-prefix special records). To get the PTTBL array index, subtract `n_special`: `pt_idx = pttblnum - n_special`. The LOD never references `!` images, but they consume PTTBL slots normally.

**SEQSCR size** (from wmpstruc.inc, pack 2): `name(16) + flags(2) + num(2) + entry_t(64) + startx(2) + starty(2) + dam(6) + spare(4)` = **98 bytes** per entry. Skip `seqcnt + scrcnt` of these before the PTTBL block.

### Pixel Storage

- Raw 8bpp indexed pixels, row stride = `(w + 3) & ~3` (4-byte alignment)
- Pixel buffer is zero-initialized; stride padding is guaranteed zero
- Maximum palette index determines effective bpp for compression

---

## SIZX / SIZY — Compression Window

SIZX is the **compression window width** used by the DMA engine. Defaults to `rec->w`
(used when `pttblnum=-1` or BOX[1].W = 0).

When a PTTBL is present, LOADW uses `PTTBL[pttblnum - n_special].BOX[1].W + 1` as the
compression width. **The TBL output writes `rec->w` as SIZX** (matching LOADW's TBL format),
but the internal compression uses the PTTBL-derived value.

SIZY defaults to `rec->h`. The Y-offset (`BOX[1].Y`) skips leading transparent rows
during LM/TM analysis but ALL rows are encoded in the IRW.

## Point Table / PT Pairs — Animation Points

The PTTBL (point table) structure from `wmpstruc.inc` contains:

```
PTTBL: FLAGS(dw) + x1..x3(int16) + X,Y,Z(int16) + ID(dw)    = 16 bytes
       BOX[0..4]: X,Y,W,H(bytes) × 5                          = 20 bytes
       CBOX[0]:   X,Y,W,H(bytes) × 1                          = 4 bytes
Total = 40 bytes
```

### IT Tool display (collision box info)

The IT tool (`itimg.asm` at line 7328) prints collision box data:
```
X_disp = (signed)CBOX.X - ANIX + CBOX.W
Y_disp = (signed)CBOX.Y - ANIY + CBOX.H
W_disp = BOX[1].W + (CBOX.W - CBOX.H)  (no +1, internal format)
H_disp = BOX[1].Y - CBOX.W
```

For Y4AH4A01 this displays: `-21 -106 36 111` (matching user observation).

### TBL PT Pairs (4 animation point pairs)

LOADW outputs 8 values (4 coordinate pairs) as the extra point table data
after the PWRD fields. Verified by matching LOADW output for Y4AH4A01,
Y4AH4A02, and Y4AH4A03 across the YOKOIMG.TBL reference.

When PTTBL x1/x2/x3/X/Y/Z fields are zero (default), LOADW computes them
from the box geometry as follows:

```
PT1 = (CBOX.X-signed - ANIX + CBOX.W,  CBOX.Y-signed - ANIY + CBOX.H)
PT2 = (pt0.BOX[1].W + pt0.CBOX.W - pt0.CBOX.H - 1,
       pt0.BOX[1].Y - pt0.CBOX.W - 1)                     # from PTTBL[0] (!STAND2)
PT3 = (pt.BOX[2].X + 1,
       ANIY - pt.BOX[1].H + pt0.CBOX.H)                    # pt0=PTTBL[0] always
PT4 = (ANIX - pt.BOX[1].W, ANIY - pt.BOX[1].H)
```

Where `pt` = PTTBL[idx] (image's own table at `pttblnum - n_special`)
and `pt0` = PTTBL[0] (!STAND2 special record, always used for shared values).

PT1 and PT2 are **shared** (from the special records' tables). PT3 and PT4
are **per-image** (from the image's own table).

**Verification table:**

| Image      | PT1       | PT2      | PT3      | PT4     |
|------------|-----------|----------|----------|---------|
| Y4AH4A01   | -21,-106  | 35,110   | 21,114   | -7,110  |
| Y4AH4A02   | -21,-106  | 35,110   | 24,94    | -7,90   |
| Y4AH4A03   | -23,-91   | 35,110   | 31,91    | -7,88   |

---

## IRW Binary Format

The IRW is the output container for compressed (or uncompressed) GSP image data.

### Header (0x44 bytes)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `0x00` | 8 | Date string | ASCII date, NUL-padded (e.g. `"03/14/95"`) |
| `0x08` | 24 | Reserved | Zero-filled |
| `0x20` | 4 | Magic | Always `0x00640194` (little-endian) |
| `0x24` | 8 | Reserved | Zero-filled |
| `0x2C` | 4 | ROM address | Target ROM address (little-endian) |
| `0x30` | 4 | Data size | Payload byte count, header-exclusive (little-endian) |
| `0x34` | 4 | Checksum | Sum of all uint16 LE words in payload, truncated to 32 bits. Trailing odd byte discarded. |
| `0x38` | 4 | Constant | Always `0x00000004` |
| `0x3C` | 2 | Type/flags | `0x0000`, `0x0001`, `0x0002`, or `0xFFFF` |
| `0x3E` | 6 | Reserved | Zero-filled |

### Data Section (from offset 0x44)

Continuous bit-packed image data. Images are stored sequentially with no delimiters or padding between them.

- SAG values from the TBL are **bit offsets** into this data section (TMS34010 uses bit-addressable memory)
- Multi-scale images store full → half → quarter resolution sequentially; the next image's SAG starts immediately after the last scale's bits

---

## DMA2 CTRL Word

```
Bits [15:12]  PIX SIZE: 0=8bpp, else = bpp value (e.g. 6 for 6bpp)
Bits [11:10]  TM: trailing-zero multiplier selector (0–3 → ×1,×2,×4,×8)
Bits [9:8]    LM: leading-zero multiplier selector (0–3 → ×1,×2,×4,×8)
Bit  [7]      CMP: 1 = compression enabled (ZON mode)
```

Multiplier values: `mult = 1 << selector` (so LM=1 → ×2, LM=2 → ×4, etc.)

LM/TM selection uses `choose_mult_min_error()` — FUN_1000_6f20's error-minimizing
formula: select the multiplier that minimizes `sum(lead − min(lead/mult,15)×mult)`
across all rows. See `compression.md` for details.

---

## Row Compression Format (ZON mode)

Each compressed row = **1 header byte** + **stored pixels** bit-packed LSB-first.

```
Header byte:  [trail_n : 4 bits][lead_n : 4 bits]
```

- `lead_c = lead_n × lm_mult` — leading zero pixels skipped
- `trail_c = trail_n × tm_mult` — trailing zero pixels skipped
- `stored = sizx − lead_c − trail_c` — pixels actually written to the stream

**Invariant:** `lead_c + stored = sizx` when `trail_n = 0` (holds for most early rows).

Pixels are written at `bpp` bits each, LSB first. Total bits per row = `8 + stored × bpp`.

### lead_n and trail_n

Both use per-row values (no running minimum). The DMA2 hardware decodes each row independently:
- lead counted from left of `rec->w` (full buffer width)
- trail counted from SIZX right edge, zero-padded beyond rec->w
- `lead_n = min(lead / lm_mult, 15)`, `trail_n = min(trail / tm_mult, 15)`
- `lead_c = lead_n × lm_mult`, `trail_c = trail_n × tm_mult`
- `stored = max(0, sizx − lead_c − trail_c)`

### Uncompressed mode (ZOF)

Pixels are packed directly: `bpp` bits each, LSB first, no row header. No lead/trail optimization.

---

## Multi-Scale Encoding

Each image can have 1–4 LOD scales (full, ½, ¼, ⅛). Controlled by `*N` suffix in LOD `--->` lines.

- Scale 0 (full): encoded with ZON compression using the analyzed LM/TM multipliers
- Scale 1 (half): subsampled then encoded with ZON compression using BOX[2] parameters
- Scales 2–3: subsampled and encoded with ZON compression using simplified LM/TM
- Each scale gets its own SAG offset and CTRL word in the TBL entry

---

## LOD File Format

LOD files are text scripts processed line by line. Lines beginning with `;` or `/` are comments.

### Directives

| Directive | Effect |
|-----------|--------|
| `ZON>`    | Enable zero-run compression |
| `ZOF>`    | Disable zero-run compression |
| `PON>`    | Enable palette output |
| `POF>`    | Disable palette output |
| `XON>`    | Extra zero pixel mode on |
| `XOF>`    | Extra zero pixel mode off |
| `CON>`    | Checksum deduplication on |
| `COF>`    | Checksum deduplication off |
| `MON>`    | (monitor — ignored) |
| `BON>`    | (ignored) |
| `ROM>`    | (ignored) |
| `PPP>N`   | Force N bits per pixel (1–8); auto-detect if omitted |
| `ASM> file` | Set output TBL assembly file |
| `GLO> file` | Set output GLO globals file |
| `***> addr,end,bank` | Set base address for IRW encoding |
| `IHDR field:size,...` | Define image header field layout |
| `FRM> name` | Load `.BIN` file (compressed movie footage), write raw bytes to IRW |
| `filename.IMG` | Load IMG container file |
| `---> name[:hex][*N],...` | Process named images from current IMG |
| `BBB> name` | Load BLIMP background (`.BDB` + `.BDD` files) |

### IHDR Fields

`SIZX`, `SIZY`, `SAG`, `CTRL`, `ANIX`, `ANIY`, `PAL`, `ALT`, `PWRD1`, `PWRD2`, `PWRD3`, `PT3Y`, `PT0X`–`PT4Y`

Sizes: `B` (byte), `W` (word, default), `L` (long)

Default IHDR: `SIZX:W,SIZY:W,ANIX:W,ANIY:W,SAG:L,CTRL:W,PAL:L,PWRD1:W,PWRD2:W,PWRD3:W,PT3Y:W`

---

## TBL Output Format (Assembly)

```asm
        .DATA
        .word   <scale_count>
IMAGE_NAME:
        .word   <SIZX>
        .word   <SIZY>
        ...                     ; per IHDR field list
        .long   0<SAG>H
        .word   0<CTRL>H
        .long   <PAL_LABEL>
        ; additional scales (scale 1+):
        .long   0<SAG_S1>H
        .word   0<CTRL_S1>H
```

Palette file (`imgpal.asm`) format:
```asm
PALNAME:
        .word   <numc>
        .word   XXXXH,XXXXH,...  ; 8 RGB565 values per line
```

---

## BBB Background (BLIMP) Handler

The `BBB>` directive loads BLIMP format background files. It processes a pair of
files: `<name>.BDB` (object placement) and `<name>.BDD` (binary image container).

See `bbb.md` for the full implementation reference and `bdd.md` for the canonical
BDB/BDD file format specification.

### Output Files

| File | Content |
|------|---------|
| `BGNDTBL.ASM` | HDRS (all BDD images), BLKS (per-module objects), BMOD (module metadata) |
| `BGNDPAL.ASM` | Palette colour data as `.word` arrays |
| `BGNDEQU.H` | World dimension equates: `W<name> .EQU <w>`, `H<name> .EQU <h>` |
| `BGNDTBL.GLO` | `.globl` declarations for all module labels and palette names |

### Image Compression

Background images use the same compression algorithm as regular sprites
(FUN_1000_6f20 lead/trail counting, LM/TM selection, minimum stored=10 adjustment):
- **PPP> bpp**: `g.ppp` respected when set; otherwise per-image from max pixel
- **Unique colors**: increases bpp when image has >64 unique colors
- **Brute-force LM/TM search**: all 16 combinations tried
- **CMP decision**: `g.zon && comp_bits < raw_bits`; forced to 0 for w<10 or h<10
- **Dedup**: checksum-based, shared dedup_table with sprites
- **Stride**: `(w + 3) & ~3` — 4-byte aligned
- **LM/TM reset**: LM=TM=0 when CMP=0 (no compression)

### Current Status

- **BGNDTBL.GLO** — exact match
- **BGNDEQU.H** — exact match
- **BGNDTBL.ASM** — structural content matches; BLKS wx, coordinates, HDRS entries correct
- **IRW** — NUPOOL 100% byte-identical; TOMB/TOWER2 differ on LM/TM selection
  (same FUN_1000_6f20 mismatch as sprite MK3MIL/MK5MIL cascade)
- **Dedup** — 4 background checksum matches, verified against LOADW

### Reference Test Files

| Directory | LOD | Files |
|-----------|-----|-------|
| `refBBB/` | MKBBB.LOD | BGNDTBL.ASM, GLO, EQU, PAL, IRW, OUT.TXT |
| `work5/` | MKBBB.LOD | Test LOD with BDB/BDD files |
| `ref2/`..`ref8/` | MKxMIL.LOD | Sprite-only reference outputs |

Generation: `loadimg work5/MKBBB.LOD /P /T /V`; LOADW ref via DOSBox (see agents.md).## loadimg Tool — Command Line

```
loadimg <lod_file> [flags]
  /T[=dir]  Build TBL/ASM/GLO table files (optionally to directory)
  /F[=dir]  Build IRW raw file (optionally to directory)
  /X        Skip IRW generation
  /I[=dir]  Source image directory
  /D[=dir]  LOD file directory
  /V        Verbose output
  /E        Dual-banked image memory
  /P        Pad to 4-bit boundary
  /L        Align to 16-bit boundary
  /B        Derive bpp from palette size
  /3        Limit scales to 3
  /A        Append mode for GLO file
```

Output filenames are derived from the LOD file's base name (uppercased):
- `<BASE>IMG.TBL` — image table assembly
- `IMGTBL.GLO` — global symbols
- `IMGPAL.ASM` — palette data
- `<BASE>.IRW` — compressed image binary

### Processing Pipeline

1. **scan_bpp pass** — reads all `--->` image lists, computes global max pixel value → global bpp. Respects `PPP>` override.
2. **process_lod pass** — for each image: analyze compression window (SIZX from PTTBL), choose LM/TM multipliers, encode all rows to IRW bitstream, write TBL entry, write palette if needed. Also processes `FRM>` and `BBB>` directives inline.
3. **write_irw** — flush IRW header + bit-packed data to file.

### Key Implementation Notes

- **Two-pass architecture:** bpp determined globally before encoding begins.
- **Case-insensitive IMG loading:** tries original, uppercase, and lowercase filenames, in both `imgdir` and current directory.
- **n_special handling:** special `!` records are identified by scanning leading `!`-prefix records; `n_images = imgcnt − n_special`. The palette offset is `oset + imgcnt × 50` — do NOT add `n_special` again, as `imgcnt` already includes them (confirmed bug: adding it caused a 100-byte overrun).
- **PTTBL offset:** after palettes, skip `seqcnt + scrcnt` SEQSCR blocks (98 bytes each per wmpstruc.inc). PTTBL entries then follow directly.
- **PTTBL indexing:** PTTBL array index = `pttblnum - n_special`. Implemented by shifting the PTTBL pointer:
`pttbls = pal_end + 6 - n_special * sizeof(PTTBL)`. Then `pttbls[pttblnum]` resolves
to entry `(pttblnum - n_special)`. `n_pttbls = n_images + n_special`. The shared
entry 0 (!STAND2) is accessed via `pttbls0 = pal_end + 6` (always actual PTTBL start).
- **SIZX source:** `PTTBL[pttblnum - n_special].BOX[1].W`. When no PTTBL (pttblnum=-1), falls back to `rec->w`. Verified by YOK_HIT2.IMG removal test. SIZX is used unconditionally (even when > rec->w, pixels beyond rec->w are treated as zero in the SIZX-stride buffer model).
- **PT pairs:** When PTTBL x1/x2/x3 fields are zero, computed from BOX/CBOX geometry (documented in Point Table section above). When non-zero, read directly from PTTBL fields.
- **LM/TM selection:** uses `choose_mult_min_error()` — per-row error-minimizing formula matching `FUN_1000_6f20`. Lead counts SIZX-bounded with 120 cap; trail counts only after lead finishes (like FUN_1000_6f20's bVar8 logic). SIZX ≤ 15 forces LM=0/TM=0.
- **Per-row lead_n:** uses current row's lead directly (no running minimum). Trail from SIZX right edge with zero-padding beyond rec->w (matching LOADW's internal SIZX-stride buffer model).
- **CMP=0 fallback:** When `sizx < 10` or `comp_bits >= raw_bits`, compression is disabled (CMP=0). The sizx < 10 check matches LOADW's "Need 10 non-zero pixels minimum" — if the image is narrower than 10 pixels, the minimum-stored=10 adjustment consumes the entire row.
- **Space check:** Uses `<=` comparison — CMP=0 when compressed size >= raw size. If equal, compression is disabled (not worth encoding).
- **Per-image bpp:** When `PPP>` is not set, bpp is computed from the image's maximum pixel value (auto pixel packing). This is done per-image during encoding, not from the palette size.
- **FRM> directive:** Loads a `.BIN` file (compressed movie footage), writes raw bytes to IRW without compression. Generates a `.set` TBL entry with `base_addr + irw_bit` offset and a `.globl` symbol.
- **BBB> directive:** Loads `.BDB` + `.BDD` background files, encodes images using the same FUN_1000_6f20 algorithm, writes to BGNDTBL.ASM/PAL/GLO/EQU files. See `bbb.md`.
- **Checksum dedup (CON>/COF>):** Uses DWORD-based `loadw_checksum()` (sum as uint32 + max over byte-pairs), matching `FUN_1854_35fc`. Table resets on IMG change (new `.IMG` file loaded). Up to 4096 entries keyed by `{sum, max_val, sizx, sizy, ctrl}`.
- **ASM> append mode:** When the same TBL filename is used multiple times (e.g. via `ASM>` directive in different LOD sections), output is appended rather than overwritten. Controlled by the `/A` flag on the command line.
- **DOS path basename:** File paths from `c:\path\to\file.IMG` format are correctly parsed — the basename extraction looks for the last `\`, `/`, or `:` separator.
- **BPP from palette:** by default, per-image bpp is derived from palette size (`ceil(log2(numc))`), not max pixel value. This matches LOADW behavior (palette-based, not `/B` pixel-based). Use `/B` flag for pixel-based bpp.
- **IRW bit stream:** LSB-first packing. Each call to `irw_write_bits(val, n)` appends `n` bits starting from the LSB of `val`.
- **SAG in TBL:** stored as `base_addr + bank * 0x2000000 + ie->sag` where `ie->sag` is the raw bit offset from IRW data section start. The `***>` base address is included.
- **IRW encoding always runs:** even when `/X` skips writing the IRW file, encoding still executes so that SAG offsets and scale CTRLs are computed correctly for TBL output.
- **`g.tbldir` must be set from `/T=` flag** before `process_lod` runs, so that `ASM>` directives inside the LOD redirect to the correct output directory.
- **`write_palette` guards `g.pal_fp`:** if no palette file is open (e.g. `/T` not specified), write_palette returns early rather than crashing.

### Debugging SAG Cascades

When a TBL diff shows a mismatching SAG, the compressed size of the **image before it** (in the IRW stream, i.e. the preceding image in the LOD's processing order) differs. To find the root cause:

1. Find the first line in the TBL where SAG or CTRL differs — this is the first image whose encoding diverges.
2. Look backward in the LOD file for the `--->` line containing this image's name. Check its compression mode (`ZON>`/`ZOF>`), `PPP>` bpp override, and any toggles (`XON>`, etc.).
3. If the SAG is wrong but the CTRL matches, the preceding image's compressed size differs (same LM/TM but different pixel data output — checked the per-row lead/trail encoding).
4. If the CTRL itself differs, the LM/TM selection (FUN_1000_6f20) or bpp computation diverged for this image. Check `PPP>` / auto bpp, and compare `lead_err`/`trail_err` accumulator values against LOADW's verbose output (`/V5` under DOSBox).

---

## SEQSCR / Sequence Structures (IMG)

When `seqcnt > 0`, SEQSCR entries appear between the palette records and the PTTBL section. From `wmpstruc.inc` (pack 2):

```
name_s    byte[16]      ; INAMELEN+1
flags     sword         ; 2
num       sword         ; 2
entry_t   dd[16]        ; 64  (16 frame pointers)
startx    sword         ; 2
starty    sword         ; 2
dam       byte[6]       ; 6
spare1    sword         ; 2
spare2    sword         ; 2
Total = 98 bytes
```

Skip `seqcnt` SEQSCR entries then `scrcnt` SEQSCR entries (scripts use the same struct) to reach the PTTBL block. The `num` field is the count of active frames, not the entry array size (always 16 slots allocated).

---

## Reference Files

| File | Description |
|------|-------------|
| `loadimg/src/loadimg.c` | Main implementation (2001 lines) |
| `loadimg/load2.hlp` | Original LOAD2 documentation |
| `loadimg/DMA2.DOC` | DMA2 CTRL word documentation |
| `loadimg/lod/YOK_HIT.IMG` | Reference IMG container (126 images, 4 palettes) |
| `loadimg/build/` | CMake build directory |
| `IT/it.inc` / `IT/wmpstruc.inc` | Assembly struct definitions for IMG format |
| `loadimg/binary/LOADW.EXE` | Original MS-DOS LOADW binary (5/25/94) |
| `loadimg/output/YOKOIMG.TBL` | Reference LOADW YOKO output |
| `loadimg/output2/YOKOTEST.TBL` | Reference LOAD2 YOKOTEST output (03/14/95) |
| `loadimg/output3/BAMIMG.TBL` | Reference LOADW BAM output |

## LOADW Binary Analysis

The LOADW.EXE at `loadimg/binary/LOADW.EXE` is an MS-DOS MZ executable (16-bit x86,
290KB, dated 5/25/94). Entry point: CS=0x0c9a, IP=0x0018. Code segment at file
offset 0x1A00 (416×16).

### Compression Algorithm — Key Functions (Ghidra)

Decompiled from LOADW.EXE. See `compression.md` for full details.

| Function     | Address       | Source file | Purpose |
|-------------|---------------|-------------|---------|
| `_packbits`  | 0x1000:5b64  | `load2.c`   | Main compression — lead/trail analysis, row encoding |
| `_do_zcom`   | 0x100a:fa02  | `zcom.c`    | Zero-compression row writer |
| `FUN_1000_6f20` | 0x1000:6f20 | —          | Error-minimizing LM/TM selector |
| `_load_bits` | 0x1000:737c  | `load2.c`   | Bitstream I/O (write bits, flush) |
| `_compute_bpp` | 0x1000:35a1 | `load2.c`   | Bits-per-pixel computation |
| `FUN_1854_37dd` | 0x1854:37dd | —          | Checksum/dedup (CON> feature) |

Address format: flat offset from load module base (file offset 0x1A00 = Ghidra segment 1000).

### COFF Debug Symbols

The binary contains COFF-style debug symbols appended at the end of the file,
revealing C function names and source files. Extracted via `strings`:

- `_create_point_table` at file offset 247675
- `_compute_bpp` at file offset 248804
- `_write_palette`, `_write_row`, `_write_tbl`
- Source files: `load2.c`, `zcom.c`, `emm.c`, `ldbgnd2.c`

The debug symbol addresses use a 4-byte field after the null-terminated name.
For `_create_point_table`, the segment/offset maps to `1000:5BE1` in Ghidra's
memory layout (confirmed by matching disassembly).

### SIZX computation (from BOX[1] references)

The code accesses PTTBL BOX[1] at offsets 0x14 (X), 0x15 (Y), 0x16 (W), 0x17 (H):
- `mov ax,[bx+0x16]` loads BOX[1].W into AX
- `cmpw $0xa,es:[bx+0x16]` — threshold check: if BOX[1].W ≤ 10, special handling

### Format Strings (TBL output)

Located at addresses `4000:7abe`–`4000:7ad9+` in Ghidra (file offsets ~234688–234734).
The cluster contains 5 null-terminated format strings used sequentially:

```
4000:7ac2: "%d"              — scale count
4000:7ac4: "\t.word\t%d,%d"  — PT values 1–2
4000:7ad1: ",%d,%d"          — PT values 3–4 (continuation, no leading tab)
4000:7ad9: "\t.word\t0,0,0,0"— hardcoded default (not used for real PT output)
4000:7ae6: "\t.global\t%s"   — global label
```

### Key Findings

1. **PTTBL offset formula**: `pttbl_ofs = pal_end + seqscr + 6 - n_special * sizeof(PTTBL)`.
   The 6-byte gap after palette records always exists. SEQSCR blocks (98 bytes each) are
   skipped before the gap. Verified by matching per-image BOX[1] values to LOADWV output.

2. **Scale SAGs point within image data**: LOADW encodes two sub-blocks per image (BOX[1] +
   BOX[2]) concatenated into a single IRW entry. Scale 0 SAG = sub-block 0 start. Scale 1
   SAG = sub-block 1 start (within same image data). No separate scale data is generated
   in the IRW. The `*N` flag in LOD controls how many SAG entries appear in the TBL.

3. **SIZX in TBL vs compression**: The TBL writes `rec->w` as SIZX, but the DMA2
   compression engine internally uses `PTTBL[pttblnum - n_special].BOX[1].W + 1`.
   These differ when BOX[1].W < rec->w (most sprites are smaller than their buffer).

4. **PWRD = Power Words**: PTTBL fields x1/x2/x3 map to PWRD1/2/3 in the TBL. When stored
   values are zero, LOADW computes them from BOX/CBOX geometry. PT3Y maps to the PTTBL id
   field.

5. **LOADW state-dependent output**: LOADW's IRW output varies between single-image runs
   and full LOD runs (different CTRL values observed). The reference files in `output3/`
   are the only reliable ground truth.

### CTRL+PWRD line formatting

LOADW outputs CTRL and PWRD1/2/3/PT3Y on a single `.word` line
(e.g. `06580H,-1,-1,-1,0`). Since v0.91, `write_image_tbl` follows the IHDR>
directive dynamically — CTRL is no longer hardcoded to its own line, so
consecutive `:W` fields share a `.word` line matching LOADW's output.

## Implementation Status

| Feature | Status | Notes |
|---------|--------|-------|
| PTTBL offset | ✓ | `pal_end + seqscr + 6` (no n_special shift — pttblnum directly indexes) |
| SIZX (compression) | ✓ | `pttbl_sizx : OUT_STRIDE(w)` with XON-before-stride |
| SIZX (TBL output) | ✓ | `OUT_STRIDE(w + XON)` matches LOADW |
| XON>/XOF> | ✓ | Extra zero pixel column, applied BEFORE stride alignment |
| SIZY | ✓ | `rec->h` plus XON |
| SAG format | ✓ | `base_addr + bank * 0x2000000 + bit_offset` |
| Two-sub-block encoding | ✓ | BOX[1] + BOX[2] concatenated in IRW; scale 1 SAG = sub-block 1 start |
| Per-row encoding | ✓ | Byte-exact — matches FUN_1000_6f20 |
| PAL | ✓ | Palette label name (e.g. `YOKRED_P`) |
| PWRD | ✓ | From IMG_REC anix2/aniy2/aniz2 |
| PT pairs | ✓ | Computed from geometry when stored fields zero; stored values used otherwise |
| Scale format | ✓ | SAG:L + CTRL:W only |
| .TEXT trailer | ✓ | `\t.TEXT\r\n` + `0x1a` EOF marker |
| Palette (.globl) | ✓ | `main_glo_fp` for IMGTBL.GLO (never redirected) |
| IRW header | ✓ | Date, n_images, bpp, total_size |
| FUN_1000_6f20 (LM/TM) | ✓ | Error-minimizing, 120 cap, `else if` for trail, minimum stored=10 |
| PTTBL struct | ✓ | 40-byte struct at 40-byte stride from 12-byte dense file data |
| IMG record duplicate handling | ✓ | Last-wins for new-format (0x63c/0x64e), first-wins for old (0x634) |
| IMG record name comparison | ✓ | Case-sensitive strcmp (vfontA ≠ vfonta) |
| PWRD1/PWRD2/PWRD3 | ✓ | From IMG_REC anix2/aniy2/aniz2 |
| Geo PT fields (PT0X..PT5X) | ✓ | From PTTBL header fields with box geometry fallback |
| Auto bpp (PPP=0) | ✓ | Per-image from max pixel value |
| FUN_1854_35fc (checksum) | ✓ | 16-bit wrapping sum + max over byte-pairs; stride-padded for sprites |
| Minimum stored = 10 | ✓ | Exact Ghidra-decompiled FUN_1000_6f20 second pass |
| Space check (CMP=0) | ✓ | `sizx < 10` or `comp_bits >= raw_bits` (`<=` comparison) |
| CMP=0 XON width | ✓ | `OUT_STRIDE(w + XON)` matches LOADW |
| Dedup (sprite) | ✓ | 5-field key {sum, max, sizx, sizy, ctrl}, stride-padded cksum |
| Dedup (background) | ✓ | 3-field key {sum, max, ctrl}, raw pixel cksum |
| Dedup table persistence | ✓ | Not reset per IMG (persists across entire LOD) |
| BBB Y-offset | ✓ | `y = sy - min_sy_of_module` from FUN_1854_1a49 |
| BBB object matching | ✓ | First-fit by BDB order, inclusive bounds `x+w-1 ≤ de` |
| BBB BLKS/BMOD output | ✓ | Exact match with LOADW reference |
| FRM> directive | ✓ | Loads .BIN files, writes raw to IRW with .set TBL entries |
| IMGTBL.ASM generation | ✓ | Wrapper including all GLO> files |
| IMGPAL.ASM formatting | ✓ | Header, `%3d` count, conditional hex width |
| CON>/COF> dedup | ✓ | 16-bit checksum, shared dedup_table |
| ASM> append mode | ✓ | Same TBL filename appends via `/A` flag |
| DOS path basename | ✓ | Extracts filename from `c:\path\to\file.IMG` |
| make regen | ✓ | DOSBox-based reference regeneration |
| Cross-platform | ✓ | Linux + Windows (MinGW) |
| Old-format palette offset | ✓ | v0.91 — 42-byte rec_size for `pal_ofs` instead of `IMG_REC_SIZE` |
| IHDR> dynamic field output | ✓ | v0.91 — CTRL no longer hardcoded; fields grouped by IHDR spec |
| WWF test data | ✓ | v0.91 — MAIN.LOD, MISC.LOD with LOADW references |

### Remaining Issues

| Issue | LODs | Root Cause |
|-------|------|------------|
| CMP=1 encoder cascade | BB5, BB6, BB7, WWF | LM/TM/bpp selection differs from LOADW for compressed images |
| PLYRDSQ2 PT0X sentinel values | BB6 | 2 cosmetic differences: PT0X = 0 vs -32768 (sentinel for "no PT0X"), reference inconsistency in LOADW |
| OUTDOOR wrong LEAF pixels | BB7 | Pre-existing LOADW false dedup bug — reference has wrong LEAF pixels (image deduped when it shouldn't have been) |
| WWF TBL format | BAM, MAIN, MISC | `/SEQ` mode needed: PTTBL-based SIZX, scale count, PT pairs, scale SAG/CTRL |

### Test Results (current dataset)

All LOD files are from **Mortal Kombat 2** arcade data. Naming: MK2MIL = MK2 ROM bank 2, MK4MIL = bank 4, etc.
BB* LODs are from **NBA Jam / Hangtime** arcade data.

| Test | Mode | Result | Notes |
|------|------|--------|-------|
| **MK2MIL** | ZON + ZOF | **PASS** (5/5) | |
| **MK3MIL** | ZOF | **PASS** (5/5) | |
| **MK4MIL** | ZON | **PASS** (6/6) | |
| **MK5MIL** | ZON | **PASS** (7/7) | |
| **MK6MIL** | ZON/ZOF | **PASS** (17/17) | |
| **MK7MIL** | Mixed | FAIL (10/11) | BGNDTBL.GLO has extra ENDMARKER entry |
| **MK8MIL** | FRM | **PASS** (1/1) | |
| **BB** | ZOF+XON | **PASS** (2/2) | |
| **BB2** | ZOF+XON | **PASS** (3/3) | |
| **BB3** | ZOF+PT | **PASS** (2/2) | |
| **BB4** | ZOF+XON | **PASS** (1/1) | |
| **BB5** | Mixed | **PASS** (7/7) | |
| **BB6** | Mixed | **PASS** (6/6) | |
| **BB7** | Mixed | FAIL (15/16) | OUTDOOR LEAF8 unused image, ref dedup bug |
| **BB8** | XON | **PASS** (3/3) | |
| **BBMUG** | ZOF+XON | **PASS** (2/2) | |
| **BBVDA** | VDA | **PASS** (1/1) | |
| **TROG** | /OLD | FAIL (12/15) | 9 TBLs + IMGPAL + IMGTBL.GLO + BGNDTBL.GLO pass; BBB handler |
| **NARC1** | /OLD | FAIL (20/21) | NARCMUGS buggy LOAD.EXE ref (accepted) |
| **CARN** | /OLD2 | FAIL (0/13) | TUNG3 dedup collision cascades all SAGs |
| **MISC** | Dual-bank | **PASS** (21/21) | NBA Jam/Hangtime |

**16 pass, 5 fail** (v0.96). WWF tests (MAIN, MISC) not yet in automated suite.

**LM/TM mismatch note**: The FUN_1000_6f20 lead/trail analysis had a subtle bug
(the trail loop used a separate `if (lead_done)` block instead of `else if`,
causing one extra trailing pixel to be counted when the lead cap of 120 was hit
on the same iteration). This has been fixed in all three code paths (analyze_image,
encode_row, second-pass comp_bits) — TE values now match LOADW's verbose output
exactly (e.g. BGSPEAR6: `TE[34 24 72 128]`).

Additional fixes:
- **Duplicate IMG record handling**: LOADW uses the LAST record when two IMG
  records share the same name (hash-table overwrite). Fixed by continuing the
  scan for new-format IMG files instead of breaking on first match.
- **Case-sensitive IMG name lookup**: IMG record names are case-sensitive
  (vfontA ≠ vfonta are different images). Changed strcasecmp to strcmp in
  IMG record scan.
- **Auto-bpp garbage pixel detection**: When maxpx > 127 and exceeds palette
  range, cap to palette bitspix (fixes pitblood1a where pixel data has garbage
  byte values 255 despite having only 15 colors).
- **PTTBL struct fix**: Changed from 40 bytes (struct with flags, x1..z_anipt3,
  box[5], cbox[1]) to 12 bytes (3 PTBOXes). Compression width from box[0].w
  (was box[1].w — 1-based index). PTTBL indexing uses pttblnum directly,
  not adjusted by n_special (the PTTBL array includes all IMG records).
- **PWRD1/PWRD2/PWRD3**: Read from IMG_REC anix2/aniy2/aniz2 instead of PTTBL.
- **seen_names reset**: Uses imgpath (string) comparison instead of ImgFile
  pointer (which could collide after free+realloc).
- **XON>/XOF> (extra zero pixel mode)**: Adds +1 to SIZX/SIZY in `analyze_image`,
  widens ZOF encoder output by 1 pixel, and includes the extra row in lead/trail
  analysis (all three loops).
- **FRM padding**: Word-alignment applied AFTER each FRM entry (was before),
  matching LOADW's byte-exact IRW output.
- **PTTBL 40-byte struct**: Restored full PTTBL structure with header fields
  (flags, x1/x2/x3, X/Y/Z, id, box[0..4], cbox). PT fields in IHDR now read
  from correct shared PTTBL entries (PT2X/PT2Y from pttblnum-2, PT0X from
  pttblnum-3 cbox, PT3X/PT3Y/PT5X from pttblnum-2 X/Y/id).
- **BPP overflow check**: When `PPP> N` forces bpp < palette color count,
  CTRL bpp nibble is zeroed (preserving LM/TM/CMP bits).
- **Auto pixel packing**: Only applies when `PPP=0` (auto mode). Not when
  `PPP>0` forces a specific bpp.
- **IMG DOS path handling**: Skips basename fallback when path has directory
  separator (`\`, `/`, `:`), matching LOADW behavior. Prints warning on failure.
- **PWRD1/PWRD2/PWRD3 from IMG_REC**: Set from `rec->anix2`/`aniy2`/`aniz2`
  (was hardcoded to -1).

The BB5 CMP=1 encoder cascade was resolved in v0.95 with a PTTBL shared-entry
pointer arithmetic fix (`&pttbls[pttblnum-2]` UB → explicit `ptrdiff_t` offset).
BB5/BB6 PT0X sentinel issues were fixed in v0.96 (PT0X reads PTTBL `flags` in
IT.EXE mode, per-image `ite_pttbl`, heuristic extended to `n_seqscr=0`).
BB5: 7/7, BB6: 6/6.

The specific BGSPEAR6 LM/TM mismatch was fixed (the `if`/`else if` trail loop
and 120-cap logic now match FUN_1000_6f20 exactly), and the broader cascade
for BB6/BB7 was resolved with the PTTBL version gate and stride-width bpp scan
fixes. BB6 CHEER now passes (stride-width bpp scan). BB7 went from 8/16→15/16 with
PTTBL version gate + min-10 SIZX + IT.EXE validation; the sole remaining
failure is OUTDOOR (pre-existing LOADW false dedup bug — reference has wrong
LEAF pixels). MK2MIL, MK4MIL, and MK8MIL are fully byte-exact, confirming the
encoder is correct for those datasets.

### Reference File Sources

| Directory | Content |
|-----------|---------|
| `work3/` | MK7MIL reference (images + background tables) |
| `ref2/` | MK2MIL reference |
| `ref3/` | MK3MIL reference |
| `ref4/` | MK4MIL reference |
| `ref5/` | MK5MIL reference |
| `ref8/` | MK8MIL reference |
| `refBBB/` | MKBBB reference (background tables) |
| `work5/` | Test BDB/BDD files and MKBBB.LOD |
| `binary/LOADW.EXE` | Original MS-DOS LOADW binary |

### DMA2 Compression Format (from DMA2.DOC)

The DMA2 chip hardware decode format (confirmed by the official DMA2.DOC from Keep Enterprises, Jan 1992):

```
Header byte:  [trail_n : 4 bits][lead_n : 4 bits]
lead_c = lead_n × lm_mult       — leading zeros skipped by hardware
trail_c = trail_n × tm_mult     — trailing zeros skipped by hardware
stored = sizx − lead_c − trail_c — pixels actually in the bitstream
```

Each row is encoded as 1 header byte + stored pixels bit-packed at `bpp` bits each, LSB-first.

### Verified Reverse-Engineered Functions (Ghidra + DMA2.DOC)

| Function | Address | File | Status |
|----------|---------|------|--------|
| `FUN_1000_6f20` (LM/TM) | 0x1000:6f20 | `/tmp/decomp_checksum_lead.txt` | ✅ Matched by `choose_mult_min_error()` |
| `FUN_1854_35fc` (checksum) | 0x1854:35fc | `/tmp/ghidra_con_dedup.txt` | ✅ Matched by `loadw_checksum()` |
| `FUN_1854_37dd` (dedup) | 0x1854:37dd | `/tmp/ghidra_con_dedup.txt` | ✅ Matched by `dedup_table[]` |
| `_packbits` | 0x1000:5b64 | `/tmp/ghidra_packbits_new.txt` | Verified — dispatch loop |
| `_do_zcom` | 0x100a:fa02 | `/tmp/ghidra_do_zcom.txt` | Memory wrapper only |
| `FUN_1854_38f9` | 0x1854:38f9 | `/tmp/ghidra_rowenc.txt` | Queue builder |
| `_load_bits` | 0x1000:737c | `/tmp/ghidra_7505.txt` | ✅ Matched by `irw_write_bits()` |
| `DMA2.DOC` | — | `loadimg/DMA2.DOC` | 📄 Hardware spec (decode format) |

### Key Fixes Applied (in order of impact)

1. **Palette-based bpp** — 6bpp for BAM (not 8bpp) → 176% → 153%
2. **FUN_1000_6f20 lead/trail** — bVar8, 120 cap, trail-after-lead → 153% → 120%
3. **SIZX/SIZY/Y-offset from PTTBL** — BOX[1].W+1, H+1, Y as row start
4. **Scale 2 compression** — BOX[2] from PTTBL for half-size
5. **PTTBL scan** — auto-detects offset; handles SEQ/SCR and variable padding
6. **CON>/COF> dedup** — sum+max checksum matching FUN_1854_35fc
7. **Per-row lead encoding** — DMA2.DOC format; no running minimum
8. **FUN_1000_6f20 LM/TM selection** — error-minimizing multiplier selection matched to Ghidra decompilation (replaced `choose_mult` threshold heuristic)
9. **Minimum stored = 10 adjustment** — second-pass adjustment when stored < 10 pixels (matching FUN_1000_6f20 post-processing)
10. **ZOF stride width** — `/P` flag controls stride vs tight packing in ZOF mode
11. **CON>/COF> toggling** — checksum dedup can be turned on/off mid-LOD; state is tracked by `g.dedup` flag (1=ON, 0=OFF). Default is ON (matching LOADW).
12. **Old-format IMG (42-byte records)** — detected by `temp != 0xabcd`, converted to 50-byte `IMG_REC` via `norm_images` allocation in `img_load()`.
13. **CMP=0 space check** — `sizx < 10` or `comp_bits >= raw_bits` disables compression
14. **Per-image bpp** — auto pixel packing when PPP> not set
15. **FRM> directive** — loads .BIN files into IRW with .set TBL entries
16. **BBB> directive** — BDD/BDB parsing, byte-level offset tracking, compression
17. **PTTBL fix** — offset computation accounts for SEQ/SCR entries between palette records and PTTBL
18. **ASM> append mode** — same TBL filename used multiple times appends rather than overwrites
19. **DOS path basename** — extracts filename from `c:\path\to\file.IMG` paths
20. **XON>/XOF> (extra zero pixel mode)** — adds +1 to SIZX/SIZY in `analyze_image` and widens ZOF encoder output by 1 pixel (matching LOADW's DMA scaling border)
21. **FRM padding after data** — word-alignment applied AFTER each FRM entry (was before), matching LOADW's IRW layout
22. **PTTBL 40-byte struct** — restored full PTTBL with header fields, box[5], cbox; PT fields read from correct shared entries
23. **PT3Y/PT5X mapping** — PT3Y from shared PTTBL Y field, PT5X from shared id field
24. **PT0X from pttblnum-3** — PT0X reads cbox from shared entry 3 back (not own entry)
25. **XON extra row in analysis** — lead/trail analysis loops use `p.sizy` (includes XON +1) instead of `rec->h`
26. **BPP overflow flag** — CTRL bpp nibble zeroed when `PPP> N` bpp < palette color count
27. **Auto pixel packing gated** — only when PPP=0, not when PPP>0 forces specific bpp
28. **IMG path has_dir_sep guard** — skips basename fallback for DOS paths with directory separators
29. **PWRD from IMG_REC** — set pwrd1/2/3 from rec->anix2/aniy2/aniz2 (was hardcoded to -1)
30. **TM selection `<=` fix** — TM comparison uses `<=` (matching Ghidra FUN_1000_6f20), LM uses `<`
31. **Dedup byte-sum hash** — Added `sum2` field (byte-sum of pixel data) to `DedupEntry` to disambiguate 16-bit word-sum collisions. The word-sum (`loadw_checksum`) misses the last byte of odd-length buffers; the byte-sum covers all bytes. Together they form a ~32-bit effective hash, fixing BBMUG (1/2 → 2/2).
32. **Stride-width bpp scanning** — Changed `img_max_pixel()` and per-image auto bpp scan to iterate over stride pixels per row (not `rec->w`). Matches LOADW's `_compute_bpp`. Fixes BB6 CHEER images where stride padding held artifact pixel 96 (bpp: 4→7). BB6: 3/6 → 5/6.
33. **Remove debug dedup prints** — Removed `smfirebone3`/`smfirebone6`/`w==8`/`h==21` debug-specific verbose conditions from dedup lookup.
34. **PTTBL offset for v0x654+ IMGs** — SEQ/SCR entries are not between PAL_REC and PTTBL for version >= 0x654 files (e.g. NBBD8.IMG). Version-gated the seq/scr skip to < 0x654.
35. **Minimum SIZX threshold** — PTTBL-based SIZX < 10 falls back to `rec->w`. Matches the "Need 10 non-zero pixels minimum" rule; also avoids using STAND2 special entry (pttblnum=0) box[0].w values as compression width.
36. **PTTBL positioning via IT.EXE validation** — PTTBL offset computation validated against IT.EXE's `wmpstruc.inc` struct layout. SEQ/SCR skip is version-gated (< 0x654). PTTBL indexing confirmed: `pttbls[pttblnum]` directly indexes entry `(pttblnum - n_special)` with pointer shifted by `-n_special * sizeof(PTTBL)`. Fixes BB6 PLYRDSQ2 PT field computations.
37. **PT field mapping from PTTBL** — PT0X reads cbox from shared entry 3 back (pttblnum-3), PT3Y from shared PTTBL Y field, PT5X from shared id field. When PTTBL header fields are zero, geometry-based fallback from BOX/CBOX computes PT pairs. Resolves PLYRDSQ2 PT pair output to 5/6 match (2 cosmetic sentinel differences: PT0X = 0 vs -32768).
38. **Old-format palette offset (v0.91)** — Fixed `pal_ofs` computation for 42-byte IMG_REC files. The conversion was adding both `n*42` (via adjusted `oset`) and `n*IMG_REC_SIZE` (via the palette formula), producing `old_oset + n*92` instead of `old_oset + n*42`. Fixes palette lookups in WWF font files (TROGF15.IMG, TROGF7.IMG).
39. **Dynamic IHDR output (v0.91)** — Removed hardcoded `CTRL` special case in `write_image_tbl`.
40. **PTTBL shared entry signed arithmetic (v0.95)** — `&pttbls[pttblnum-2]` for `pttblnum<2` is undefined behavior (negative array index). Replaced with `ptrdiff_t` offset-from-file-base arithmetic. Fixes BB5 CMP=1 cascade (3/7->6/7).
41. **section_base_bit for continuous IRW (v0.95)** — Instead of resetting `g.irw_bit=0` at each `***>` directive, saves current bit position. Fixes SAG with two `***>` sections in Trog.
42. **+META cache stores final TBL SAG (v0.95)** — Global cache stores `base_addr + relative_offset`, so cross-section hits get correct base address.
43. **IRW header format update (v0.97)** — All IRW files now use the same 0x44-byte header: `"03/14/95"` version string, `0x00640194` magic at 0x20, ROM address at 0x2C, data-only size at 0x30, uint16 LE sum checksum at 0x34 (trailing odd byte discarded), `0x00000004` at 0x38, flags at 0x3C. See `irw-header.md` for the full spec.

### COF and CON Directives

LOADW supports toggling checksum dedup mid-LOD via `COF>` (OFF) and `CON>` (ON).
Correct semantics: `CON>` enables dedup, `COF>` disables it (default is ON).

Our implementation:

- `g.dedup = 1` = dedup ON (default, matching LOADW)
- Parsing: `CON>` → `g.dedup = 1`, `COF>` → `g.dedup = 0`
- Dedup logic: before encoding each image, compute `loadw_checksum()` (sum + max of pixel data). Look up in `dedup_table[]` matching `{sum, max_val, sizx, sizy, ctrl}`. If found, reuse SAG and skip encoding. Otherwise, encode and store in table.
- The dedup table (`DedupEntry[4096]`) persists across CON>/COF> state changes — entries accumulated while ON are reused when ON again.
- **Table reset**: when a new `.IMG` file is loaded, the dedup table is cleared (matching LOADW behavior where `FUN_1854_35fc`'s checksum table is scoped to the current IMG).

This allows LOD files like MK2MIL to toggle dedup for specific image ranges:
```
COF>    ; dedup OFF for first set of images
...
CON>    ; dedup ON for second set  
...
COF>    ; dedup OFF for third set
```

### Checksum Dedup — DWORD-Based Implementation

The checksum function `loadw_checksum()` (matching `FUN_1854_35fc`) operates on
pixel data as follows:

```c
uint32_t sum = 0;
uint16_t max_val = 0;
for (int i = 0; i < stride * h; i++) {
    sum += buf[i];
    // max over byte-pairs (16-bit groups)
    if (i % 2 == 0) {
        uint16_t pair = (uint16_t)buf[i] | ((uint16_t)buf[i+1] << 8);
        if (pair > max_val) max_val = pair;
    }
}
```

Key properties:
- **Sum as uint32**: the running sum of all pixel bytes (overflows naturally)
- **Max over byte-pairs**: every two bytes form a 16-bit word, the maximum word is tracked
- **Table reset**: on IMG change (new `.IMG` file loaded), the dedup table is cleared
- **Key fields**: `{sum, max_val, sizx, sizy, ctrl}` — all must match for dedup

### ZON (Compressed) Mode — 100% Byte-Exact Match

ZON mode now produces **byte-exact output** matching LOADW across all tested LODs.

| Test | Images | Mode | Match |
|------|--------|------|-------|
| **MKSMALL** | 4 | ZON | **100.0%** |
| **MK2MIL** | 159 | ZON (IRW+TBL) | **100.0%** |
| **MK4MIL** | 1899 | ZON (IRW+TBL) | **100.0%** |
| **MK7MIL** image TBLs | ~1900 | ZON | **100.0%** |

ZON mode implements the verified FUN_1000_6f20 algorithm:
- **LM/TM selection**: Error-minimizing — for each multiplier m (0-3), accumulates `lead_err[m] += lead - mult*min(lead/mult,15)` across all rows. Selects LM with minimum error (strict `<`), TM with minimum error (`<`).
- **Lead counting**: 120 cap (0x78), bVar8 logic (trail only after lead finishes), counted over sizx pixels.
- **Trail counting**: Only after lead finishes, only when `sizx - 120 < position` (always true for sizx ≤ 120). Resets to 0 on non-zero.
- **Second pass (per-row header)**: Computes lead_n, trail_n, applies minimum-stored=10 adjustment when `sizx - lead_c - trail_c < 10`.
- **Stride**: FUN_1000_6f20 uses SIZX-stride (`(sizx+3)&~3`), NOT rec->w-stride. The `_do_sclpad` buffer copy at `_packbits` lines 725-757 creates an internal buffer with stride = sizx.
- **Space check**: CMP=0 if `sizx < 10` or `comp_bits >= raw_bits` (uses `<=` comparison).

### ZOF (Uncompressed) Mode — Byte-Exact Match

ZOF mode (`ZOF>` directive, `g.zon=0`) produces **byte-exact output** matching LOADW
for new-format IMG files. Verified with `MKSMALL.LOD`:

| Test | `/P` flag | Match |
|------|-----------|-------|
| MKSMALL (4 images) | With `/P` | **100.0%** (1 trailing 0x00) |
| MKSMALL (4 images) | Without `/P` | **100.0% exact** |
| MK3MIL (159 images, 4 IMG files) | With `/P` | **100.0% binary match** |
| MK2MIL (159 images, CON/COF toggling) | With `/P` | **100.0% binary match** |

Key fixes for ZOF:
1. **Stride width**: `/P` flag controls stride `(w+3)&~3` vs tight `w` packing
2. **No scale data**: `encode_scaled()` disabled — all scale SAGs point to scale 0
3. **Palette bpp cap**: max 8
4. **Old-format IMG**: supported via `norm_images` conversion (42→50 byte IMG_REC)
5. **CON>/COF> dedup**: `loadw_checksum()` + `dedup_table[4096]` lookup-before-encode

### Old-Format IMG (Pre-WimpV5)

Files with `temp != 0xabcd` (old LOAD2 format) use a **42-byte IMG_REC** instead of 50 bytes.
Field mapping (old offset → new offset):
```
name_s[16] (0-15)  → N_s[16] (0-15)       [same]
xoff(2)    (16-17) → ANIX(2) (18-19)      [+2]
yoff(2)    (18-19) → ANIY(2) (20-21)      [+2]
xsize(2)   (20-21) → W(2)    (22-23)      [+2]
ysize(2)   (22-23) → H(2)    (24-25)      [+2]
palind(2)  (24-25) → PALNUM(2) (26-27)    [+2]
flags(2)   (26-27) → FLAGS(2) (16-17)     [-10] (MOVED before anix/aniy/w/h/palnum)
oset(4)    (28-31) → OSET(4) (28-31)      [same]
data(4)    (32-35) → DATA(4) (32-35)      [same]
lib(2)     (36-37) → LIB(2)  (36-37)      [same]
pword1(2)  (38-39) → ANIX2(2) (38-39)     [same]
pword2(2)  (40-41) → ANIY2(2) (40-41)     [same]
```
Total: 42 bytes (old) vs 50 bytes (new). The `flags` field moved from after palnum (old)
to before anix (new). New fields not in old format: `ANIZ2`, `FRM`, `PTTBLNUM`, `OPALS`.
Old format has no PTTBL entries (pttblnum defaults to -1).

Supported: `img_load()` allocates a clean `norm_images` buffer of converted 50-byte `IMG_REC`s,
patches `lib_hdr` (sets `temp=0xabcd`, adjusts `oset` so palette lookup lands correctly), and
sets `img->images` to point into `norm_images`. No PTTBL entries (`pttblnum=-1`, `opals=0xffff`).
Field mapping from `IT/itimg.asm convert_old_img` is authoritative.

### How to Generate LOADW Reference Output (DOSBox)

This procedure runs the original LOADW.EXE under DOSBox to generate reference `.IRW`, `.TBL`, `.GLO`, and `.ASM` files for comparison.

#### Prerequisites
- LOADW.EXE at `loadimg/binary/LOADW.EXE`
- DOSBox installed (`which dosbox`)
- All required `.IMG`, `.BIN`, `.BDB`, `.BDD` files accessible
- Our loadimg built at `loadimg/build/loadimg`

#### One-Time Setup: Copy Required Files
```bash
# Create a clean test directory with ALL needed files
mkdir -p /tmp/ref_test
cp /home/alex/Projects/midway-imgtool/loadimg/binary/LOADW.EXE /tmp/ref_test/
cp /home/alex/Projects/midway-imgtool/loadimg/work2/<LOD>.LOD /tmp/ref_test/
cp /home/alex/Projects/midway-imgtool/loadimg/work2/*.IMG /tmp/ref_test/
cp /home/alex/Projects/midway-imgtool/loadimg/work2/*.BIN /tmp/ref_test/
cp /home/alex/Projects/midway-imgtool/loadimg/work2/*.BDB /tmp/ref_test/
cp /home/alex/Projects/midway-imgtool/loadimg/work2/*.BDD /tmp/ref_test/
```

#### Run LOADW in DOSBox
```bash
cat > /tmp/dosbox_ref.conf << 'EOF'
[dosbox]
machine=svga_s3
memsize=16
[cpu]
core=auto
cputype=auto
cycles=max
cycleup=10
cycledown=20
[autoexec]
mount c /tmp/ref_test
c:
md TMP
LOADW <LOD_BASENAME> /P /F=C:\TMP /T=C:\TMP /V5 > C:\TMP\OUT.TXT
exit
EOF
timeout 120 dosbox -conf /tmp/dosbox_ref.conf 2>&1 | tail -3
```

Flags:
- `/P` — pad to 4-bit boundary (required for matching)
- `/F=C:\TMP` — IRW output directory
- `/T=C:\TMP` — Table file output directory
- `/V5 > C:\TMP\OUT.TXT` — verbose level 5 redirected to file for debug analysis
- **Important**: LOADW adds `.lod` extension automatically — pass ONLY the basename (e.g. `MK2MIL` not `MK2MIL.LOD`)

#### Copy Reference Files
```bash
mkdir -p /home/alex/Projects/midway-imgtool/loadimg/ref2
cp /tmp/ref_test/TMP/* /home/alex/Projects/midway-imgtool/loadimg/ref2/
```

#### Run Our loadimg and Compare
```bash
cd /home/alex/Projects/midway-imgtool/loadimg/work2
# Clean previous output
rm -f <LOD>.IRW *.TBL IMGTBL.ASM IMGTBL.GLO IMGPAL.ASM
# Run our loadimg
/home/alex/Projects/midway-imgtool/loadimg/build/loadimg <LOD>.LOD /P /T 2>/dev/null
# Compare TBL files
for f in <LOD>.TBL <OTHER_TBLS>.TBL; do
    diff /home/alex/Projects/midway-imgtool/loadimg/ref2/$f $f >/dev/null 2>&1 \
        && echo "$f: MATCH" || echo "$f: DIFFER"
done
```

#### Known Pitfalls
- **LOADW adds `.lod`**: Pass the basename WITHOUT extension. `LOADW MK2MIL` not `LOADW MK2MIL.LOD`.
- **TMP/TEMP vars**: The `md TMP` and output to `C:\TMP` are required — LOADW crashes without `C:\TMP`.
- **DOSBox statefulness**: Always use a fresh temp directory to avoid stale state.
- **.lod extension**: Some LOD files use `.LOD`, others `.lod`. DOSBox is case-sensitive; LOADW doesn't care.
- **`/F` not `/R`**: LOADW uses `/F` for the raw/IRW output directory, not `/R`.
- **8.3 filenames**: DOSBox requires uppercase 8.3 filenames. Our loadimg is case-insensitive.

#### Reference File Locations
| Directory | Content |
|-----------|---------|
| `loadimg/work3/` | MK7MIL reference (images + backgrounds) |
| `loadimg/ref2/` | MK2MIL reference (images only, no BBB) |
| `loadimg/binary/LOADW.EXE` | Original MS-DOS LOADW binary |

### Key Files
- `loadimg/DMA2.DOC` — Original DMA2 hardware specification (23KB)
- `binary/LOADWV.EXE` — Patched LOADW (verbose always enabled; `/V5` for full debug)
- `/tmp/dosbox_work/V5_BAM.TXT` — 477KB LOADW verbose output (full BAM dataset)
- `/tmp/ghidra_packbits_new.txt` — Full _packbits Ghidra decompilation (854 lines)
- `/tmp/ghidra_con_dedup.txt` — Checksum/dedup functions
- `/tmp/decomp_checksum_lead.txt` — FUN_1000_6f20 (LM/TM selector)
- `work/` — Working directory with test LODs and IMG files for MK2MIL/MKSMALL tests
- `/tmp/mk2mil/` — DOSBox test environment for MK2MIL/MKSMALL comparisons
