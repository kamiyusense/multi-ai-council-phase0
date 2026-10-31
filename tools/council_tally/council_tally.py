#!/usr/bin/env python3
"""Deterministic tally of Council answer files.

Counts agreement (jury) and rankings (rank) by fixed rules. It never decides
which answer is right, never guesses a missing answer, uses only the Python
standard library, makes no network call and starts no process.

  python3 tools/council_tally/council_tally.py jury FILE...
  python3 tools/council_tally/council_tally.py rank [--key K] [--record R --topic T] FILE...
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERDICTS = ("○", "×", "UNKNOWN")
RESULT_SAME = "一致"
RESULT_SPLIT = "割れた"
RESULT_MISSING = "無回答あり"
GROUP_MANUAL = "手動"
GROUP_AUTO = "自動"
GROUP_UNKNOWN = "UNKNOWN"

_JURY_ROW = re.compile(r"^\|?\s*(\d+)\s*\|\s*(○|×|UNKNOWN)\s*\|(.*)$")
_RANK_LABEL = re.compile(r"^順位\s*[:：]\s*(.*)$")
_LETTER = re.compile(r"^[A-Z]$")
_KEY_LINE = re.compile(r"^([A-Z])\s*[=＝]\s*(.*?)\s*$")


def read_text(path) -> str:
    """Read a file as UTF-8; a leading BOM is allowed and dropped."""
    return Path(path).read_text(encoding="utf-8-sig")


def member_name(path) -> str:
    """Member name = part of the file stem after the first '_' (whole stem if none)."""
    stem = Path(path).stem
    _, sep, rest = stem.partition("_")
    return rest if sep and rest else stem


# ---------------------------------------------------------------- jury

def parse_jury(text: str) -> dict:
    """Return {row_number: verdict}. Non-matching lines are ignored; first row wins."""
    rows: dict = {}
    for line in text.splitlines():
        m = _JURY_ROW.match(line.strip())
        if not m:
            continue
        number = int(m.group(1))
        if number not in rows:
            rows[number] = m.group(2)
    return rows


def tally_jury(named_rows):
    """named_rows: list of (name, {row: verdict}). Returns (table_rows, counts, empty_names)."""
    numbers = sorted({n for _, rows in named_rows for n in rows})
    table = []
    counts = {RESULT_SAME: 0, RESULT_SPLIT: 0, RESULT_MISSING: 0}
    for n in numbers:
        verdicts = [rows.get(n) for _, rows in named_rows]
        if any(v is None for v in verdicts):
            result = RESULT_MISSING
        elif len(set(verdicts)) == 1:
            result = RESULT_SAME
        else:
            result = RESULT_SPLIT
        counts[result] += 1
        table.append((n, verdicts, result))
    empty = [name for name, rows in named_rows if not rows]
    return table, counts, empty


def render_jury_files(files) -> str:
    """Read jury files; columns use member names, the empty-file line uses file names."""
    named = [(member_name(f), parse_jury(read_text(f))) for f in files]
    empty_files = [Path(f).name for f, (_, rows) in zip(files, named) if not rows]
    return render_jury(named, empty_files)


def render_jury(named_rows, empty_files=None) -> str:
    table, counts, empty = tally_jury(named_rows)
    if empty_files is not None:
        empty = empty_files
    names = [name for name, _ in named_rows]
    out = [
        f"{RESULT_SAME}: {counts[RESULT_SAME]} / {RESULT_SPLIT}: {counts[RESULT_SPLIT]}"
        f" / {RESULT_MISSING}: {counts[RESULT_MISSING]}",
        "有効な行がないファイル: " + (", ".join(empty) if empty else "なし"),
        "",
        "| 番号 | " + " | ".join(names) + " | 結果 |",
        "|---|" + "---|" * len(names) + "---|",
    ]
    for n, verdicts, result in table:
        cells = [v if v is not None else "-" for v in verdicts]
        out.append(f"| {n} | " + " | ".join(cells) + f" | {result} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- rank

def _clean(line: str) -> str:
    return line.strip().replace("*", "").replace("`", "").strip()


def parse_rank(text: str):
    """Use the LAST `順位:` line. Return (letters, None) or (None, reason)."""
    last = None
    for line in text.splitlines():
        m = _RANK_LABEL.match(_clean(line))
        if m:
            last = m.group(1)
    if last is None:
        return None, "順位の行がない"
    parts = [p.strip() for p in re.split(r"[>＞]", last)]
    if not parts or any(not _LETTER.match(p) for p in parts):
        return None, "大文字1文字以外が含まれる"
    if len(set(parts)) != len(parts):
        return None, "同じ記号が2回以上ある"
    return parts, None


def parse_key(text: str) -> dict:
    """Lines like `A=Codex`; other lines ignored; the first entry for a letter wins."""
    key: dict = {}
    for line in text.splitlines():
        m = _KEY_LINE.match(line.strip())
        if m and m.group(2) and m.group(1) not in key:
            key[m.group(1)] = m.group(2)
    return key


def group_of(letter: str, key) -> str:
    if key is None or letter not in key:
        return GROUP_UNKNOWN
    return GROUP_MANUAL if key[letter].startswith(GROUP_MANUAL) else GROUP_AUTO


def tally_rank(rankings, key=None):
    """rankings: list of letter lists. Returns sorted list of dicts per letter."""
    places: dict = {}
    for letters in rankings:
        for index, letter in enumerate(letters, start=1):
            places.setdefault(letter, []).append(index)
    rows = []
    for letter, ps in places.items():
        rows.append({
            "letter": letter,
            "average_place": round(sum(ps) / len(ps), 2),
            "reviewers": len(ps),
            "who": (key.get(letter, GROUP_UNKNOWN) if key is not None else None),
            "group": (group_of(letter, key) if key is not None else None),
            "_places": ps,
        })
    rows.sort(key=lambda r: (sum(r["_places"]) / len(r["_places"]), r["letter"]))
    return rows


def group_averages(rows) -> dict:
    """Average place per group over every single placement of the group's letters."""
    acc: dict = {}
    for r in rows:
        acc.setdefault(r["group"], []).extend(r["_places"])
    order = [GROUP_MANUAL, GROUP_AUTO, GROUP_UNKNOWN]
    return {g: round(sum(acc[g]) / len(acc[g]), 2) for g in order if g in acc}


def render_rank(rows, invalid, key=None) -> str:
    out = []
    if invalid:
        out.append("有効な順位行がないファイル: " + ", ".join(f"{n}（{why}）" for n, why in invalid))
    else:
        out.append("有効な順位行がないファイル: なし")
    out.append("")
    if key is None:
        out += ["| 順位 | 記号 | 平均順位 | 評価者数 |", "|---|---|---|---|"]
        for i, r in enumerate(rows, start=1):
            out.append(f"| {i} | {r['letter']} | {r['average_place']:.2f} | {r['reviewers']} |")
    else:
        out += ["| 順位 | 記号 | 誰 | グループ | 平均順位 | 評価者数 |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(rows, start=1):
            out.append(f"| {i} | {r['letter']} | {r['who']} | {r['group']} | "
                       f"{r['average_place']:.2f} | {r['reviewers']} |")
        out.append("")
        out.append("グループ別の平均順位:")
        for g, avg in group_averages(rows).items():
            out.append(f"- {g}: {avg:.2f}")
    return "\n".join(out) + "\n"


def record_lines(rows, topic: str):
    for r in rows:
        yield json.dumps({
            "topic": topic,
            "letter": r["letter"],
            "who": r["who"],
            "group": r["group"],
            "average_place": r["average_place"],
            "reviewers": r["reviewers"],
        }, ensure_ascii=False)


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="council_tally", description="Council answer tally (no AI, no network).")
    sub = p.add_subparsers(dest="mode", required=True)
    j = sub.add_parser("jury", help="count ○/×/UNKNOWN agreement per row")
    j.add_argument("files", nargs="+")
    r = sub.add_parser("rank", help="average the last 順位: line of each review")
    r.add_argument("--key")
    r.add_argument("--record")
    r.add_argument("--topic")
    r.add_argument("files", nargs="+")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "jury":
            sys.stdout.write(render_jury_files(args.files))
            return 0
        if (args.record or args.topic) and not args.key:
            print("error: --record and --topic require --key", file=sys.stderr)
            return 2
        if args.record and not args.topic:
            print("error: --record requires --topic", file=sys.stderr)
            return 2
        key = parse_key(read_text(args.key)) if args.key else None
        rankings, invalid = [], []
        for f in args.files:
            letters, why = parse_rank(read_text(f))
            if letters is None:
                invalid.append((Path(f).name, why))
            else:
                rankings.append(letters)
        rows = tally_rank(rankings, key)
        sys.stdout.write(render_rank(rows, invalid, key))
        if args.record:
            with open(args.record, "a", encoding="utf-8") as fh:
                for line in record_lines(rows, args.topic):
                    fh.write(line + "\n")
        return 0
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
