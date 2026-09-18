#!/usr/bin/env python3
"""Tests for slopcheck. Run: python3 tests/test_slopcheck.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from slopcheck import scan  # noqa: E402

FAILED = []


def check(name: str, text: str, rule: str, expected: bool, **kw) -> None:
    findings, _ = scan(text, **kw)
    got = any(f.rule == rule for f in findings)
    if got != expected:
        FAILED.append(f"{name}: expected {rule}={expected}, got {got} "
                      f"(rules seen: {sorted({f.rule for f in findings})})")


# --- hard rules fire -------------------------------------------------------
check("chat wrapper", "Great question! The cache is warm.\n", "chatbot-residue", True)
check("cutoff", "As of my last training update, pricing is unclear here.\n",
      "cutoff-disclaimer", True)
check("antithesis en", "It's not just a tool, it's a platform for teams.\n",
      "antithesis", True)
check("antithesis ru", "Это не просто скрипт, а целая система сборки.\n",
      "antithesis", True)
check("em dash en", "The policy, announced late — affects everyone here.\n",
      "em-dash", True)

# --- language routing ------------------------------------------------------
check("ru text is not judged by en dash rule",
      "Отчёт готов. Внутри — три цифры и один вывод по делу.\n", "em-dash", False)
check("ru dash budget",
      ("Строка с тире — раз. Ещё одна — два. Третья — три. Четвёртая — четыре.\n" * 2),
      "em-dash-rate", True)

# --- quoting and code are not judged --------------------------------------
check("blockquote skipped", "> It's not just a tool, it's a platform for teams.\n",
      "antithesis", False)
check("table row skipped", "| 8 | dashes | \"institutions—not the people\" |\n",
      "em-dash", False)
check("quotes can be forced on", "> Great question! Here it is.\n",
      "chatbot-residue", True, quotes=True)
check("fenced code skipped", "```\nx = a — b  # not prose\n```\n", "em-dash", False)
check("inline code skipped", "Run `a — b` to see the flag in action here.\n",
      "em-dash", False)
check("url skipped", "See https://example.com/a—b for the full write-up now.\n",
      "em-dash", False)

# --- structural ------------------------------------------------------------
check("bold label list",
      "- **Speed:** fast\n- **Safety:** solid\n- **Scale:** big\n",
      "bold-label-list", True)
check("changelog is not a label list",
      "- **2.1.0** - added a flag\n- **2.0.1** - fixed a bug\n- **2.0.0** - first cut\n",
      "bold-label-list", False)
check("title case heading", "## Unlocking The Future Of Developer Work\n",
      "title-case-heading", True)
check("sentence case heading is fine", "## What changed in the parser\n",
      "title-case-heading", False)
check("heading echo",
      "## Performance tuning\n\nPerformance tuning is the subject of this section here.\n",
      "heading-echo", True)
check("link line under heading is not an echo",
      "## Performance tuning\n\n[performance tuning notes](./tuning.md)\n",
      "heading-echo", False)

# --- soft rules cluster ----------------------------------------------------
check("one buzzword is not a finding", "The API is robust and documented.\n",
      "vocab", False)
check("three buzzwords in one paragraph are",
      "A robust, seamless, vibrant platform for teams.\n", "vocab", True)

# --- clean text stays clean ------------------------------------------------
clean = Path(__file__).parent / "sample_good_en.md"
if clean.exists():
    findings, stats = scan(clean.read_text(encoding="utf-8"))
    if stats["hard"] or stats["soft"]:
        FAILED.append(f"sample_good_en.md should be clean, got {stats}")

if FAILED:
    print(f"FAILED {len(FAILED)}")
    for line in FAILED:
        print("  -", line)
    raise SystemExit(1)
print("all tests passed")
