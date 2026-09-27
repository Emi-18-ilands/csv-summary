"""Tests for csv_summary. Builds real fixtures and runs the actual reader."""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import csv_summary as cs  # noqa: E402


def write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def tables(text, **kw):
    opts = {"header": "auto", "max_top": 3}
    opts.update(kw)
    return cs._extract_tables(text, opts["header"], opts["max_top"])


def col(t, name):
    return next(c for c in t["columns"] if c["name"] == name)


def test_multi_table_and_title():
    text = ("Sales Export\n"
            "date,region,units\n"
            "2024-01-05,North,12\n"
            "2024-02-02,South,7\n"
            "\n"
            "refunds\n"
            "date,amount\n"
            "2024-03-01,4.99\n")
    ts = tables(text)
    assert len(ts) == 2, ts
    assert ts[0]["title"] == "Sales Export"
    assert ts[0]["rows"] == 2
    assert ts[1]["title"] == "refunds"


def test_leading_zero_is_text_not_int():
    ts = tables("id,n\n00123,3\n00450,9\n")
    assert col(ts[0], "id")["type"] == "text", col(ts[0], "id")
    assert col(ts[0], "n")["type"] == "int"


def test_nulls_counted():
    ts = tables("a,b\n1,x\n2,\n3,n/a\n")
    b = col(ts[0], "b")
    assert b["nulls"] == 2, b
    assert b["non_null"] == 1


def test_ragged_rows_padded_and_flagged():
    ts = tables("a,b,c\n1,2,3\n4,5\n6,7,8,9\n")
    assert ts[0]["ragged_rows"] == 2, ts[0]["ragged_rows"]
    assert all(len(r) == 3 for r in ts[0]["data"])
    # the too-long row must be truncated, not dropped
    assert ts[0]["rows"] == 3


def test_header_never_param():
    ts = tables("Alice,30\nBob,41\n", header="never")
    assert ts[0]["header"] == ["col1", "col2"], ts[0]["header"]
    assert ts[0]["rows"] == 2


def test_bool_column():
    ts = tables("name,active\nA,true\nB,false\nC,yes\n")
    a = col(ts[0], "active")
    assert a["type"] == "bool", a
    assert a["summary"] == "2 true, 1 false", a["summary"]


def test_date_range():
    ts = tables("d\n2023-12-31\n2024-06-01\n2024-01-15\n")
    assert ts[0]["columns"][0]["type"] == "date"
    assert ts[0]["columns"][0]["summary"] == "2023-12-31 .. 2024-06-01"


def test_tab_delimited():
    ts = tables("a\tb\n1\t2\n")
    assert ts[0]["delimiter"] == "\t"
    assert ts[0]["columns"][0]["name"] == "a"


def test_cli_text_markdown_json_and_split():
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "d.csv", "a,b\n1,x\n2,y\n")
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "csv_summary.py"), path],
            capture_output=True, text=True, check=True).stdout
        assert "Tables found: 1" in out
        assert "columns" in out

        md = subprocess.run(
            [sys.executable, os.path.join(ROOT, "csv_summary.py"), path,
             "--markdown"], capture_output=True, text=True, check=True).stdout
        assert "| column | type |" in md

        js = subprocess.run(
            [sys.executable, os.path.join(ROOT, "csv_summary.py"), path,
             "--json"], capture_output=True, text=True, check=True).stdout
        parsed = json.loads(js)
        assert parsed["tables"][0]["rows"] == 2
        assert "data" not in parsed["tables"][0]

        split = os.path.join(tmp, "out")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "csv_summary.py"), path,
             "--split-dir", split], capture_output=True, text=True, check=True)
        written = sorted(os.listdir(split))
        assert written == ["d_table1.csv"], written
        body = open(os.path.join(split, "d_table1.csv")).read()
        assert body.splitlines()[0] == "a,b"
        assert len(body.splitlines()) == 3


def test_quoted_newline_stays_one_cell():
    text = 'note,n\n"line one\n\nline two",5\n'
    ts = tables(text)
    assert len(ts) == 1, ts
    assert ts[0]["rows"] == 1, ts[0]["rows"]
    assert ts[0]["data"][0][0] == "line one\n\nline two"
    assert col(ts[0], "n")["type"] == "int"


def test_all_null_column_labeled():
    ts = tables("a,b\n1,\n2,\n")
    assert col(ts[0], "b")["summary"] == "(all null)", col(ts[0], "b")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok  %s" % fn.__name__)
    print("\n%d tests passed" % len(fns))
