#!/usr/bin/env python3
"""
hexdump_img.py FILE [options]

Display pixel values from a raw binary image file.

Options:
  --bpw  N          bytes per word: 1, 2, 3 or 4  (default: 1)
  --endian  ENDIAN  le (little-endian) or be (big-endian)  (default: le)
  --resolution WxH  image resolution, e.g. 640x480
                    If given, display uses [row,col] coordinates.
                    If omitted, display uses a flat [offset] index.
  --per-line N      words per output line  (default: 16)
  -                 print to stdout instead of writing a file

Examples:
  hexdump_img.py frame.y16 --bpw 2 --endian be --resolution 640x480 -
  hexdump_img.py frame.y14 --bpw 2 --endian le --resolution 1024x128 -
  hexdump_img.py frame.raw --bpw 1
"""
import sys, struct, os, argparse

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Hex dump of a raw pixel image file.",
    add_help=True,
)
parser.add_argument("file",
    help="input binary file")
parser.add_argument("--bpw", type=int, default=1, choices=[1, 2, 3, 4],
    metavar="N",
    help="bytes per word: 1, 2, 3 or 4  (default: 1)")
parser.add_argument("--endian", default="le", choices=["le", "be"],
    metavar="ENDIAN",
    help="le or be  (default: le)")
parser.add_argument("--resolution", default=None,
    metavar="WxH",
    help="image resolution, e.g. 640x480  (enables row/col display)")
parser.add_argument("--per-line", type=int, default=16,
    metavar="N",
    help="words per output line  (default: 16)")
parser.add_argument("-", dest="to_stdout", action="store_true",
    help="write to stdout instead of a file")

# Accept legacy positional syntax: FILE BPW ENDIAN [-]
# i.e. if argv[2] is a digit and argv[3] is le/be, rewrite as named args.
args_in = sys.argv[1:]
if (len(args_in) >= 3
        and not args_in[1].startswith("-")
        and args_in[1].isdigit()
        and args_in[2].lower() in ("le", "be")):
    rewritten = [args_in[0],
                 "--bpw",    args_in[1],
                 "--endian", args_in[2]]
    for a in args_in[3:]:
        if a == "-":
            rewritten.append("-")
        else:
            rewritten.append(a)
    args_in = rewritten

args = parser.parse_args(args_in)

filename  = args.file
bpw       = args.bpw
endian    = args.endian.lower()
per_line  = args.per_line
to_stdout = args.to_stdout
hex_w     = bpw * 2

# ---------------------------------------------------------------------------
# Parse resolution
# ---------------------------------------------------------------------------
width = height = None
if args.resolution:
    try:
        w_s, h_s = args.resolution.lower().split("x")
        width, height = int(w_s), int(h_s)
    except (ValueError, AttributeError):
        sys.exit(f"--resolution must be WxH (e.g. 640x480), got: {args.resolution!r}")

# ---------------------------------------------------------------------------
# Read and decode words
# ---------------------------------------------------------------------------
data  = open(filename, "rb").read()
total = len(data)
n     = total // bpw

if bpw == 3:
    words = []
    for i in range(n):
        b = data[i*3 : i*3+3]
        if endian == "be":
            words.append(b[0] << 16 | b[1] << 8 | b[2])
        else:
            words.append(b[2] << 16 | b[1] << 8 | b[0])
else:
    fmt_char = {1: "B", 2: "H", 4: "I"}[bpw]
    fmt_end  = "<" if endian == "le" else ">"
    words = list(struct.unpack(fmt_end + fmt_char * n, data[:n * bpw]))

# ---------------------------------------------------------------------------
# Determine layout
# ---------------------------------------------------------------------------
if width is not None:
    # Resolution known: 2-D display with [row,col]
    cols  = width
    rows  = height if height is not None else (n // cols)
    if n < cols * rows:
        sys.exit(f"File too small: {n} words < {cols}x{rows} = {cols*rows} words")
    mode = "2d"
else:
    # No resolution: flat 1-D display
    cols  = n
    rows  = 1
    mode  = "1d"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
dst = f"{filename}_{bpw}B_{endian.upper()}_hex.txt"
out = sys.stdout if to_stdout else open(dst, "w")

def write(s):
    try:
        out.write(s)
    except BrokenPipeError:
        sys.exit(0)

# Header line
if mode == "2d":
    write(f"{os.path.basename(filename)}  {bpw}B/word  {endian.upper()}  "
          f"{cols}x{rows} px  ({total} bytes)\n")
else:
    write(f"{os.path.basename(filename)}  {bpw}B/word  {endian.upper()}  "
          f"{n} words  ({total} bytes)\n")

# Column header
def col_hdr(i, w):
    h = f"+{i}"
    return h.rjust(w) if len(h) <= w else str(i).rjust(w)

if mode == "2d":
    data_label = f"[{0:04d},{0:04d}]"   # e.g. "[0000,0000]"
    hdr_label  = "[row, col]"
else:
    data_label = f"[{0:08d}]"            # e.g. "[00000000]"
    hdr_label  = "[offset]"
pfx_w = len(data_label) + 2             # data label + 2 spaces separator
hdr_pad = " " * (pfx_w - len(hdr_label))
write(hdr_label + hdr_pad + "  ".join(col_hdr(i, hex_w) for i in range(per_line)) + "\n")
write("-" * (pfx_w + per_line * (hex_w + 2)) + "\n")

# Data
if mode == "2d":
    for row in range(rows):
        for col in range(0, cols, per_line):
            chunk = words[row * cols + col : row * cols + col + per_line]
            write(f"[{row:04d},{col:04d}]  "
                  + "  ".join(f"{v:0{hex_w}X}" for v in chunk) + "\n")
        write("\n")
else:
    for offset in range(0, n, per_line):
        chunk = words[offset : offset + per_line]
        write(f"[{offset:08d}]  "
              + "  ".join(f"{v:0{hex_w}X}" for v in chunk) + "\n")

if not to_stdout:
    out.close()
    print(f"Written {rows} rows x {cols} words -> {dst}")
