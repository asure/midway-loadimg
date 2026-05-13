# IRW File Format — Header Specification

## Overview

IRW files are binary image/resource files used by the Midway/Williams arcade toolchain.
Each file begins with a fixed 0x44-byte header, followed immediately by the data payload.

## Header Layout

| Offset | Size | Field         | Description |
|--------|------|---------------|-------------|
| `0x00` | 8    | Date string   | ASCII date, NUL-padded. Valid files contain `"03/14/95"`. |
| `0x08` | 24   | Reserved      | Zero-filled. |
| `0x20` | 4    | Magic         | Always `0x00640194` (little-endian). Constant across all known files. |
| `0x24` | 4    | Reserved      | Always `0x00000000`. |
| `0x28` | 4    | Reserved      | Always `0x00000000`. |
| `0x2C` | 4    | ROM address   | Target address where this data maps in ROM (e.g. `0xFFF93000`). Little-endian. |
| `0x30` | 4    | Data size     | Byte count of the payload (everything after the 0x44 header). Little-endian. |
| `0x34` | 4    | Checksum      | Sum of all 16-bit little-endian words in the payload, truncated to 32 bits. See below. |
| `0x38` | 4    | Constant      | Always `0x00000004`. |
| `0x3C` | 4    | Type/flags    | Observed values: `0x0000`, `0x0001`, `0x0002`, `0xFFFF`. Meaning TBD. |
| `0x40` | 4    | Reserved      | Always `0x00000000`. |

All multi-byte integers are **little-endian**.

## Checksum Algorithm

`field_34` is computed over the data payload only (bytes `[0x44 .. end_of_file]`).

```python
import struct

def irw_checksum(data: bytes) -> int:
    n = len(data) // 2          # number of complete 16-bit words; trailing odd byte is ignored
    words = struct.unpack_from(f"<{n}H", data)
    return sum(words) & 0xFFFFFFFF
```

Steps:
1. Read all bytes after the 0x44 header.
2. Interpret them as a sequence of 16-bit little-endian unsigned integers.
3. If the payload has an odd length, discard the final byte.
4. Sum all words as a plain integer, then mask to the low 32 bits.
5. Store the result at offset `0x34` as a 32-bit little-endian unsigned integer.

## Validation Checklist

When reading an IRW file, the following checks should pass:

1. `file_size >= 0x44` — file is at least as large as the header.
2. `field_30 == file_size - 0x44` — declared data size matches the actual payload length.
3. `irw_checksum(payload) == field_34` — checksum matches the payload.
4. `field_20 == 0x00640194` — magic constant is present.

The date string at `0x00` is informational and should not be used for validation.

## Fixing a Corrupt Header (BAD.IRW Case Study)

`BAD.IRW` has two header anomalies compared to valid files:

**1. Wrong date string (offset `0x00`)**

- Stored: `"4.50 4/2"` (a linker version string)
- Expected: `"03/14/95"`
- This field is not load-critical in known tooling, but should be corrected for conformance.

**2. Wrong checksum (offset `0x34`)**

- Stored: `0x26525D8A`
- Correct: `0x26525CDE`
- Difference: `0xAC` (172)
- The payload data was modified after the header was written, so the stored checksum is stale.
- The data size at `0x30` (`54189`) is correct.

**Fix procedure (Python):**

```python
import struct

with open("BAD.IRW", "rb") as f:
    raw = bytearray(f.read())

payload = raw[0x44:]
checksum = sum(struct.unpack_from(f"<{len(payload)//2}H", payload)) & 0xFFFFFFFF

struct.pack_into("<I", raw, 0x34, checksum)

# Optionally fix the date string:
raw[0x00:0x08] = b"03/14/95"

with open("FIXED.IRW", "wb") as f:
    f.write(raw)
```

## Notes

- The `0x3C` type/flags field correlates loosely with file content category
  (`0xFFFF` appears on smaller/palette-type files; `0x0001`/`0x0002` on larger image banks).
  Its exact semantics are not yet fully understood.
- The ROM address at `0x2C` can be in high address space (`0xFFF93000`, `0xFFF6BA30`)
  for files that map near the top of the MIPS address space.

---

