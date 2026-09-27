#!/usr/bin/env python3
"""csv_summary - split a CSV/text export into tables and describe each one.

Real exports are often not a clean single table: a report may stack several
header rows in one file, block-separated by blank lines, with a title line on
top. This reads that file, finds the tables, infers what each column holds,
and prints a summary a human can read.

Standard library only.

Usage:
    python3 csv_summary.py PATH [--header auto|always|never]
                                 [--markdown] [--json] [--max-top N]
                                 [--split-dir DIR]

PATH may be a file, or a directory (then every .csv/.tsv/.txt is processed).
"""

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys

NULLS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "?"}

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(:\d{2})?$"
)
_BOOL_RE = re.compile(r"^(true|false|yes|no|y|n)$", re.IGNORECASE)

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M",
                 "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                 "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")


def _is_null(value):
    return value.strip().lower() in NULLS


def _classify(value):
    """Return the type name for one raw string cell."""
    s = value.strip()
    if _is_null(s):
        return "empty"
    if _INT_RE.match(s):
        # keep leading-zero codes (zip, id, phone) as text, not numbers
        body = s.lstrip("+-")
        if len(body) > 1 and body[0] == "0":
            return "text"
        return "int"
    if _FLOAT_RE.match(s):
        return "float"
    if _DATE_RE.match(s):
        return "date"
    if _DATETIME_RE.match(s):
        return "datetime"
    if _BOOL_RE.match(s):
        return "bool"
    return "text"


def _parse_date(s):
    s = s.strip().replace("/", "-")
    if s.endswith("Z"):
        s = s[:-1]
    try:
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                return _dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _pick_delimiter(first_line):
    counts = {d: first_line.count(d) for d in ",\t;|"}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _parse_rows(block_lines, delimiter):
    reader = csv.reader(io.StringIO("\n".join(block_lines)), delimiter=delimiter)
    rows = [r for r in reader]
    # drop trailing fully-empty rows
    while rows and all(c == "" for c in rows[-1]):
        rows.pop()
    return rows


def _split_into_blocks(text, delimiter):
    """Return (start_line, end_line, rows) blocks split on blank rows.

    csv.reader over the whole text (not line-by-line) so a quoted field may
    contain commas or newlines and still belong to one cell.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    blocks = []
    current = []
    start = 1
    prev_end = 0
    for row in reader:
        end = reader.line_num
        if all(c.strip() == "" for c in row):
            if current:
                blocks.append((start, prev_end, current))
                current = []
        else:
            if not current:
                start = end
            current.append(row)
        prev_end = end
    if current:
        blocks.append((start, prev_end, current))
    return blocks


def _modal_length(rows):
    counts = {}
    for r in rows:
        counts[len(r)] = counts.get(len(r), 0) + 1
    return max(counts, key=counts.get)


def _looks_like_header(row, ncols, data_rows):
    if len(row) != ncols or ncols < 1:
        return False
    cells = [c.strip() for c in row]
    if any(c == "" for c in cells):
        return False
    if len(set(cells)) != len(cells):
        return False
    for c in cells:
        if _classify(c) in ("int", "float", "date", "datetime"):
            return False
    if ncols == 1:
        # one column: a text label over date/number/bool data is a header
        kinds = {_classify(r[0]) for r in data_rows
                 if r and r[0].strip() != ""}
        return bool(kinds) and kinds <= {
            "int", "float", "date", "datetime", "bool"}
    return True


def _column_type(values):
    seen = [v for v in values if _classify(v) != "empty"]
    if not seen:
        return "empty"
    kinds = {_classify(v) for v in seen}
    if kinds <= {"int"}:
        return "int"
    if kinds <= {"int", "float"}:
        return "float"
    if kinds <= {"bool"}:
        return "bool"
    if kinds <= {"date"}:
        return "date"
    if kinds <= {"datetime"}:
        return "datetime"
    if kinds <= {"date", "datetime"}:
        return "datetime"
    return "text"


def _profile_column(name, raw_values, max_top):
    non_nulls = [v.strip() for v in raw_values if _classify(v) != "empty"]
    total = len(raw_values)
    nulls = total - len(non_nulls)
    uniques = {}
    for v in non_nulls:
        uniques[v] = uniques.get(v, 0) + 1
    ctype = _column_type(raw_values)

    summary = ""
    if ctype in ("int", "float"):
        nums = []
        for v in non_nulls:
            try:
                nums.append(float(v))
            except ValueError:
                pass
        if nums:
            lo, hi = min(nums), max(nums)
            mean = sum(nums) / len(nums)
            if ctype == "int":
                summary = "min %d, max %d, mean %.2f" % (lo, hi, mean)
            else:
                summary = "min %g, max %g, mean %.3g" % (lo, hi, mean)
    elif ctype in ("date", "datetime"):
        parsed = [p for p in (_parse_date(v) for v in non_nulls) if p]
        if parsed:
            summary = "%s .. %s" % (
                min(parsed).strftime("%Y-%m-%d"),
                max(parsed).strftime("%Y-%m-%d"),
            )
    elif ctype == "bool":
        trues = sum(1 for v in non_nulls if v.lower() in ("true", "yes", "y"))
        summary = "%d true, %d false" % (trues, len(non_nulls) - trues)
    elif ctype == "empty":
        summary = "(all null)"
    else:
        top = sorted(uniques.items(), key=lambda kv: (-kv[1], kv[0]))[:max_top]
        shown = []
        for val, count in top:
            label = val if len(val) <= 24 else val[:21] + "..."
            shown.append("%s (%d)" % (label, count))
        summary = "top: " + ", ".join(shown)

    return {
        "name": name,
        "type": ctype,
        "non_null": len(non_nulls),
        "nulls": nulls,
        "unique": len(uniques),
        "summary": summary,
    }


def _extract_tables(text, header_mode, max_top):
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = _pick_delimiter(first_line)
    blocks = _split_into_blocks(text, delimiter)

    tables = []
    for first_line_no, last_line_no, rows in blocks:
        rows = [r for r in rows if any(c.strip() != "" for c in r)]
        if not rows:
            continue
        ncols = _modal_length(rows)

        title = None
        if len(rows[0]) == 1 and ncols > 1:
            title = rows[0][0].strip()
            rows = rows[1:]
        if not rows:
            continue

        header = None
        want_header = {}
        if header_mode in ("auto", "always"):
            if _looks_like_header(rows[0], ncols, rows[1:]):
                header = [c.strip() for c in rows[0]]
                rows = rows[1:]
            elif header_mode == "always":
                header = ["col%d" % (i + 1) for i in range(ncols)]
        if header is None:
            header = ["col%d" % (i + 1) for i in range(ncols)]

        ragged = 0
        data = []
        for r in rows:
            if len(r) != len(header):
                ragged += 1
                r = (r + [""] * len(header))[: len(header)]
            data.append(r)

        columns = []
        for i, name in enumerate(header):
            values = [row[i] for row in data]
            columns.append(_profile_column(name, values, max_top))

        tables.append({
            "title": title,
            "start_line": first_line_no,
            "end_line": last_line_no,
            "delimiter": delimiter,
            "columns": columns,
            "rows": len(data),
            "ragged_rows": ragged,
            "data": data,
            "header": header,
        })
    return tables


def _render_text(path, tables, max_top):
    out = []
    out.append("File: %s" % path)
    out.append("Tables found: %d" % len(tables))
    for n, t in enumerate(tables, 1):
        head = "Table %d" % n
        if t["title"]:
            head += '  "%s"' % t["title"]
        out.append("")
        out.append(head)
        out.append("  lines %d-%d, %d columns, %d rows%s"
                   % (t["start_line"], t["end_line"], len(t["columns"]),
                      t["rows"],
                      "  (%d ragged)" % t["ragged_rows"]
                      if t["ragged_rows"] else ""))
        widths = [max(len(c["name"]), 6) for c in t["columns"]]
        namew = max(widths) if widths else 6
        head_fmt = "  %-*s  %-8s %8s %7s %7s  %s" % (
            namew, "column", "type", "non-null", "nulls", "unique", "summary")
        out.append(head_fmt)
        for c in t["columns"]:
            out.append("  %-*s  %-8s %8d %7d %7d  %s" % (
                namew, c["name"], c["type"], c["non_null"], c["nulls"],
                c["unique"], c["summary"]))
    return "\n".join(out)


def _render_markdown(path, tables, max_top):
    out = ["# %s" % path, "", "**Tables found:** %d" % len(tables)]
    for n, t in enumerate(tables, 1):
        title = ' "%s"' % t["title"] if t["title"] else ""
        out.append("")
        out.append("## Table %d%s" % (n, title))
        out.append("")
        out.append("%d columns, %d rows (lines %d-%d)."
                   % (len(t["columns"]), t["rows"],
                      t["start_line"], t["end_line"]))
        out.append("")
        out.append("| column | type | non-null | nulls | unique | summary |")
        out.append("|---|---|---:|---:|---:|---|")
        for c in t["columns"]:
            out.append("| %s | %s | %d | %d | %d | %s |" % (
                c["name"], c["type"], c["non_null"], c["nulls"],
                c["unique"], c["summary"].replace("|", "\\|")))
    return "\n".join(out)


def _to_json(path, tables):
    return json.dumps({
        "file": path,
        "tables": [
            {k: v for k, v in t.items() if k != "data"}
            for t in tables
        ],
    }, indent=2)


def _process(path, args):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    tables = _extract_tables(text, args.header, args.max_top)

    if args.split_dir:
        os.makedirs(args.split_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        for n, t in enumerate(tables, 1):
            target = os.path.join(args.split_dir, "%s_table%d.csv" % (base, n))
            with open(target, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(t["header"])
                w.writerows(t["data"])

    if args.json:
        return _to_json(path, tables)
    if args.markdown:
        return _render_markdown(path, tables, args.max_top)
    return _render_text(path, tables, args.max_top)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Split a CSV/export into tables and describe them.")
    p.add_argument("path", help="file or directory to read")
    p.add_argument("--header", choices=("auto", "always", "never"),
                   default="auto",
                   help="header detection (default: auto)")
    p.add_argument("--markdown", action="store_true", help="Markdown output")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--max-top", type=int, default=3,
                   help="top values to show per text column")
    p.add_argument("--split-dir",
                   help="also write each detected table as its own CSV here")
    args = p.parse_args(argv)

    targets = []
    if os.path.isdir(args.path):
        for name in sorted(os.listdir(args.path)):
            if os.path.splitext(name)[1].lower() in (".csv", ".tsv", ".txt"):
                targets.append(os.path.join(args.path, name))
        if not targets:
            print("No .csv/.tsv/.txt files in %s" % args.path, file=sys.stderr)
            return 1
    else:
        targets = [args.path]

    chunks = []
    for path in targets:
        if args.json:
            chunks.append(_process(path, args))
        else:
            chunks.append(_process(path, args))
    print("\n\n".join(chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
