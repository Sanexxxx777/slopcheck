#!/usr/bin/env python3
"""slopcheck: find the tells of AI writing in a file. No model, no network.

Most tools that clean AI prose are prompts: they ask a model to rewrite your text,
which costs a call, changes your words, and cannot run in CI. This one only reads.
It reports file:line, what it found, and why, then exits non-zero when it found
something that should never ship.

    python3 slopcheck.py POST.md
    python3 slopcheck.py README.md --json
    python3 slopcheck.py drafts/ --quiet

Exit codes: 0 clean, 1 hard findings, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# Severity
#
#   hard    one sighting is enough; these never survive a careful writer
#   soft    a habit a person may have on purpose; only reported in clusters
#
# The split matters. A single dash proves nothing. Nine dashes on a page is a
# machine. Reporting both the same way trains people to ignore the tool.
# --------------------------------------------------------------------------

HARD, SOFT = "hard", "soft"
CLUSTER_MIN = 3  # soft hits needed inside one paragraph before it is reported


@dataclass
class Finding:
    line: int
    rule: str
    severity: str
    message: str
    excerpt: str


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

CHATBOT_RESIDUE = [
    r"\bI hope this helps\b", r"\bGreat question\b", r"\bGreat catch\b",
    r"\bCertainly!", r"\bOf course!", r"\bYou'?re absolutely right\b",
    r"\bLet me know if\b", r"\bFeel free to reach out\b",
    r"\bI'?d be happy to\b", r"\bWould you like me to\b", r"\bShould I continue\b",
    r"Надеюсь,? это помож", r"Отличный вопрос", r"Дайте знать, если",
    r"Буду рад помочь", r"Если у вас остались вопросы",
]

CUTOFF_DISCLAIMER = [
    r"as of my (last|knowledge)", r"my (training|knowledge) (data|cutoff)",
    r"while specific details (are|remain) limited",
    r"based on (the )?available information",
    r"not (widely )?(publicly )?(documented|available|disclosed)",
    r"по состоянию на момент(у)? (моих|обучения)", r"в доступных источниках нет",
]

ANTITHESIS = [
    r"\bnot just\b[^.!?\n]{1,80}?,?\s+but\b",
    r"\bnot only\b[^.!?\n]{1,80}?,?\s+but\b",
    r"\bnot merely\b[^.!?\n]{1,80}?,?\s+but\b",
    r"\bit'?s not\b[^.!?\n]{1,60}?,\s*it'?s\b",
    r"\bне просто\b[^.!?\n]{1,80}?,\s*а\b",
    r"\bэто не\b[^.!?\n]{1,60}?,\s*это\b",
    r"\bне столько\b[^.!?\n]{1,80}?,\s*сколько\b",
]

EN_VOCAB = [
    "delve", "tapestry", "testament", "underscore", "underscores", "foster",
    "fostering", "harness", "navigate", "resonate", "elevate", "embrace",
    "transcend", "unravel", "intricate", "intricacies", "vibrant", "palpable",
    "profound", "pivotal", "crucial", "seamless", "robust", "transformative",
    "multifaceted", "bustling", "showcase", "showcasing", "leverage",
    "streamline", "streamlining", "unlock", "realm", "landscape", "journey",
    "beacon", "myriad", "meticulous", "meticulously", "garner", "bolstered",
    "interplay", "cutting-edge", "game-changer", "deep dive", "paving the way",
    "in a world where", "at the end of the day",
]

RU_VOCAB = [
    "в современном мире", "в наше время", "давайте разберёмся", "давайте разберемся",
    "не секрет, что", "как известно", "стоит отметить", "важно понимать",
    "поистине", "крайне важно", "безусловно", "однозначно", "ключевой фактор",
    "инновационный", "уникальный", "эффективный", "играет важную роль",
    "неотъемлемой частью", "открывает новые возможности", "в заключение",
]

# Hyphenated pairs that models hyphenate in every position (soft).
HYPHEN_PAIRS = [
    "third-party", "cross-functional", "client-facing", "data-driven",
    "decision-making", "high-quality", "real-time", "long-term", "end-to-end",
]

DASH_RE = re.compile(r"[—–]")
CURLY_RE = re.compile(r"[“”‘’]")
BOLD_LABEL_RE = re.compile(r"^\s*[-*+]\s+\*\*([^*]{1,60})\*\*\s*[:：-]?")
# A version number or a date in bold is a changelog, not decoration.
BOLD_NOT_LABEL_RE = re.compile(r"^\s*(v?\d+(\.\d+)*|\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?)\s*$")
EMOJI_BULLET_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?[\U0001F300-\U0001FAFF☀-➿]"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
URL_RE = re.compile(r"https?://\S+|`[^`]*`")
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def around(line: str, needle: str, width: int = 80) -> str:
    """Excerpt centred on the match, so the reader sees what was flagged."""
    pos = line.find(needle)
    if pos < 0:
        return line.strip()[:width]
    start = max(0, pos - width // 3)
    end = min(len(line), pos + len(needle) + width // 2)
    piece = line[start:end].strip()
    return ("..." if start else "") + piece + ("..." if end < len(line) else "")


def strip_protected(text: str) -> str:
    """Blank out inline code and URLs so their punctuation is not judged."""
    return URL_RE.sub(lambda m: " " * len(m.group(0)), text)


def detect_language(text: str) -> str:
    letters = re.findall(r"[a-zA-Zа-яёА-ЯЁ]", text)
    if not letters:
        return "en"
    cyr = len(CYRILLIC_RE.findall(text))
    return "ru" if cyr / len(letters) > 0.2 else "en"


def title_case_words(heading: str) -> int:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", heading) if len(w) > 3]
    if len(words) < 3:
        return 0
    return sum(1 for w in words if w[0].isupper())


def scan(text: str, path: str = "", quotes: bool = False) -> tuple[list[Finding], dict]:
    lang = detect_language(text)
    lines = text.splitlines()
    findings: list[Finding] = []
    soft_by_para: dict[int, list[Finding]] = {}

    in_code = False
    para_id = 0
    bold_label_run = 0
    dash_total = 0
    prev_heading: str | None = None

    for i, raw in enumerate(lines, start=1):
        if CODE_FENCE_RE.match(raw):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not raw.strip():
            para_id += 1
            bold_label_run = 0
            continue

        # A passage that quotes a pattern is discussing it, not committing it.
        # Blockquotes and table rows are where before/after examples live, and
        # judging them turns every style guide into a pile of false positives.
        if not quotes and re.match(r"^\s*(>|\|)", raw):
            continue

        line = strip_protected(raw)
        low = line.lower()

        def hard(rule: str, msg: str, frag: str) -> None:
            findings.append(Finding(i, rule, HARD, msg, frag.strip()[:90]))

        def soft(rule: str, msg: str, frag: str) -> None:
            f = Finding(i, rule, SOFT, msg, frag.strip()[:90])
            soft_by_para.setdefault(para_id, []).append(f)

        def structural(rule: str, msg: str, frag: str) -> None:
            # Formatting applied by rule is a choice, not a word habit, so one
            # sighting is already informative. Reported without clustering.
            findings.append(Finding(i, rule, SOFT, msg, frag.strip()[:90]))

        # --- hard rules -------------------------------------------------
        for pat in CHATBOT_RESIDUE:
            m = re.search(pat, line, re.I)
            if m:
                hard("chatbot-residue",
                     "chat wrapper left in text meant to stand alone", m.group(0))

        for pat in CUTOFF_DISCLAIMER:
            m = re.search(pat, line, re.I)
            if m:
                hard("cutoff-disclaimer",
                     "the model's knowledge limit is not the reader's business", m.group(0))

        for pat in ANTITHESIS:
            m = re.search(pat, line, re.I)
            if m:
                hard("antithesis",
                     "not-X-but-Y adds weight, not a claim: state the point directly",
                     m.group(0))

        dashes = DASH_RE.findall(line)
        if dashes:
            dash_total += len(dashes)
            if lang == "en":
                hard("em-dash",
                     "English text: replace with a period, comma, colon or parentheses",
                     around(line, dashes[0]))

        # --- soft rules -------------------------------------------------
        vocab = EN_VOCAB if lang == "en" else RU_VOCAB
        for word in vocab:
            if re.search(r"\b" + re.escape(word) + r"\b", low):
                soft("vocab", f"model-favoured wording: {word}", word)

        for pair in HYPHEN_PAIRS:
            if pair in low:
                soft("hyphen-pair", f"hyphenated in every position: {pair}", pair)

        curly = CURLY_RE.search(line)
        if curly:
            soft("curly-quotes", "curly quotes where straight quotes were typed",
                 around(line, curly.group(0)))

        bold_label = BOLD_LABEL_RE.match(raw)
        if bold_label and not BOLD_NOT_LABEL_RE.match(bold_label.group(1)):
            bold_label_run += 1
            if bold_label_run >= CLUSTER_MIN:
                findings.append(Finding(
                    i, "bold-label-list", HARD,
                    "every list item carries a bold label: turn it into prose",
                    raw.strip()[:90]))
                bold_label_run = 0
        else:
            bold_label_run = 0

        if EMOJI_BULLET_RE.match(raw):
            structural("emoji-decoration", "emoji used as decoration on a list item", raw)

        h = HEADING_RE.match(raw)
        if h:
            heading_text = h.group(2)
            if lang == "en" and title_case_words(heading_text) >= 3:
                structural("title-case-heading",
                           "headings in Title Case: sentence case reads as written by a person",
                           heading_text)
            prev_heading = heading_text
            continue

        if prev_heading:
            head_words = {w.lower() for w in re.findall(r"\w{4,}", prev_heading)}
            line_words = {w.lower() for w in re.findall(r"\w{4,}", line)}
            # Only judge real prose. A link line, a bold lead-in, a table row or a
            # one-clause boilerplate answer under "## License" is not an echo.
            is_prose = (len(re.findall(r"\w+", line)) >= 5
                        and not re.match(r"^\s*(\*\*|\[|!|\||>|[-*+]\s)", raw))
            if (is_prose and len(head_words) >= 2
                    and len(head_words & line_words) / len(head_words) >= 0.6):
                findings.append(Finding(
                    i, "heading-echo", HARD,
                    "the first line restates the heading instead of continuing it",
                    line))
            prev_heading = None

    # Russian tolerates a rare dash; English does not.
    if lang == "ru" and dash_total:
        allowed = max(1, len(text) // 1000)
        if dash_total > allowed:
            findings.append(Finding(
                0, "em-dash-rate", HARD,
                f"{dash_total} dashes for {len(text)} characters, budget is {allowed}",
                ""))

    # Soft findings only count when several share a paragraph.
    for hits in soft_by_para.values():
        if len(hits) >= CLUSTER_MIN:
            findings.extend(hits)

    findings.sort(key=lambda f: (f.line, f.rule))
    stats = {
        "path": path,
        "language": lang,
        "characters": len(text),
        "hard": sum(1 for f in findings if f.severity == HARD),
        "soft": sum(1 for f in findings if f.severity == SOFT),
    }
    return findings, stats


def render(findings: list[Finding], stats: dict, quiet: bool) -> str:
    out = []
    name = stats["path"] or "<stdin>"
    for f in findings:
        if quiet and f.severity == SOFT:
            continue
        where = f"{name}:{f.line}" if f.line else name
        out.append(f"{where}: {f.severity}: {f.rule}: {f.message}")
        if f.excerpt:
            out.append(f"    {f.excerpt}")
    verdict = "clean" if stats["hard"] == 0 else "needs work"
    out.append(
        f"{name}: {verdict} ({stats['language']}, "
        f"{stats['hard']} hard, {stats['soft']} soft)"
    )
    return "\n".join(out)


def gather(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(
        p for p in target.rglob("*")
        if p.is_file() and p.suffix.lower() in {".md", ".markdown", ".txt"}
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="file or directory")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="hard findings only")
    ap.add_argument("--quotes", action="store_true",
                    help="also judge blockquotes and table rows (off by default: "
                         "that is where before/after examples live)")
    args = ap.parse_args()

    target = args.target.expanduser()
    if not target.exists():
        print(f"no such path: {target}", file=sys.stderr)
        return 2

    paths = gather(target)
    if not paths:
        print(f"nothing to check in {target}", file=sys.stderr)
        return 2

    worst = 0
    payload = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: skipped ({exc})", file=sys.stderr)
            continue
        findings, stats = scan(text, str(path), quotes=args.quotes)
        if stats["hard"]:
            worst = 1
        if args.json:
            payload.append({"stats": stats,
                            "findings": [asdict(f) for f in findings]})
        else:
            print(render(findings, stats, args.quiet))

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
