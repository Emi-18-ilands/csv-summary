# csv_summary

Split a CSV/text export into its tables and print a summary a human can read.

Many real exports are not one clean table. A report can stack several header
rows in a single file, separated by blank lines, with a title line on top.
This tool reads that file, finds the tables, infers what each column holds, and
describes it.

Standard library only. No dependencies.

## Run

```bash
python3 csv_summary.py orders.csv
python3 csv_summary.py ./exports/            # every .csv/.tsv/.txt in a folder
python3 csv_summary.py orders.csv --markdown
python3 csv_summary.py orders.csv --json
python3 csv_summary.py orders.csv --split-dir out/   # write each table out
```

## What it detects

- **Tables**: blocks of rows separated by blank lines. A single-cell line above
  a table is kept as the table's title.
- **Header row**: a first row that is all text, non-empty, and unique. Column
  names like `n` or `no` are accepted (not mistaken for data). One-column
  tables count too: a text label over date/number/bool data is a header.
  Override with `--header always|never` when the guess is wrong.
- **Column types**: `int`, `float`, `date`, `datetime`, `bool`, `text`, `empty`.
- **Per column**: non-null count, null count, unique count, and a type-specific
  summary (min/max/mean; date range; true/false split; top values).
- **Ragged rows**: rows with the wrong number of cells are padded or trimmed and
  counted, never dropped.
- **Quoted fields**: handled via `csv.reader` over the whole text, so a quoted
  cell may contain commas or newlines and still count as one cell.
- **Delimiters**: `,`, tab, `;`, `|` (picked from the first non-empty line).
- **Leading-zero codes**: values like `00123` stay text, so zip/postal codes,
  IDs, and phone numbers are not silently turned into numbers.

## Output

Text (default):

```
File: orders.csv
Tables found: 2

Table 1  "Sales Export"
  lines 1-8, 4 columns, 6 rows
  column  type   non-null   nulls  unique  summary
  date    date          6       0       6  2024-01-05 .. 2024-03-22
  units   int           6       0       6  min 2, max 40, mean 18.83
  sku     text          6       0       4  top: 00123 (3), 00450 (1)
```

Also: `--markdown` (a table per detected table) and `--json` (everything except
the raw rows).

## Known limits (real, not hypothetical)

- **Header guessing is a heuristic.** A headerless table whose every cell is
  text can be read as having a header. Use `--header never` when you know.
- **One delimiter per file.** A file mixing a comma table and a tab table will
  parse the second one wrong. Split those files first.
- **Dates**: ISO-style only (`YYYY-MM-DD`, `YYYY/MM/DD`, and the same with a
  time). `03/04/2024` is ambiguous so it stays text rather than guess the
  month.
- **Thousands separators**: `1,234` is text unless the file is quoted and
  parsed as one cell; no localization is inferred.

## Tests

```bash
python3 tests/test_csv_summary.py
```

Builds real fixtures (multi-table files, ragged rows, quoted newlines, leading
zeros, booleans, tab-delimited) and runs the actual reader, plus the CLI for
text/markdown/json/split output. Runs in CI on every push.

MIT.
