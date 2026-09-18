# slopcheck

**Find the tells of AI writing in a file. No model, no network, no rewriting.**

Every other tool in this space is a prompt: it asks a language model to rewrite
your text. That costs a call, changes your words, needs a key, and cannot run in
CI. `slopcheck` only reads. It tells you the line, the rule, and why, and exits
non-zero when it finds something that should never ship.

```bash
python3 slopcheck.py POST.md
```

```
POST.md:5: hard: chatbot-residue: chat wrapper left in text meant to stand alone
    Great question
POST.md:7: hard: antithesis: not-X-but-Y adds weight, not a claim: state the point directly
    It's not just a tool, it's
POST.md:7: hard: em-dash: English text: replace with a period, comma, colon or parentheses
    ...modern teams can achieve — and it...
POST.md: needs work (en, 3 hard, 14 soft)
```

Python 3.9+, standard library only. One file. Exit 0 clean, 1 when hard findings
remain, so `slopcheck.py drafts/ --quiet` works as a pre-commit or CI gate.

## Hard and soft

A single dash proves nothing. Nine dashes on a page is a machine. A tool that
reports both the same way teaches people to ignore it, so findings come in two
strengths:

- **hard**: one sighting is enough. A chat wrapper left in the text, a
  knowledge-cutoff disclaimer, a not-X-but-Y contrast, an em dash in English, a
  list where every item wears a bold label, a first line that restates its own
  heading.
- **soft**: a habit a person may have on purpose. Model-favoured vocabulary,
  hyphenated pairs, curly quotes. Reported only when three or more land in the
  same paragraph.

`--quiet` shows hard findings only. That is the setting for a gate.

## What it refuses to judge

The fastest way to make a linter useless is to flag a style guide for quoting the
patterns it teaches. So by default `slopcheck` skips:

- blockquotes and Markdown table rows, where before-and-after examples live
- fenced code blocks, inline code, and URLs
- bold list labels that are version numbers or dates, which is a changelog

Pass `--quotes` to judge quoted material too.

Sanity check that shaped these exclusions: run it against the README of
[`blader/humanizer`](https://github.com/blader/humanizer), a well-written
document that quotes dozens of AI tells on purpose. Before the exclusions it
scored 17 hard findings, every one of them a quotation. Now it scores zero, which
is the correct answer.

## Two languages, two rulebooks

The language is detected per file from its share of Cyrillic characters.

English gets zero tolerance for em and en dashes: it is the single most
recognisable trace a model leaves, and a human writer reaches for it rarely.
Russian gets a budget instead, one dash per 1000 characters, because there the
dash does grammatical work that a comma cannot.

Vocabulary lists are per language and are deliberately short. Word habits change
with every model release; the structural tells do not, which is why the hard
rules are all structural and the word lists are all soft.

## Rules

| Rule | Strength | What it catches |
|---|---|---|
| `chatbot-residue` | hard | "Great question", "I hope this helps", "Let me know if" |
| `cutoff-disclaimer` | hard | "as of my last training update", "not publicly available" |
| `antithesis` | hard | not just X but Y, it's not X it's Y, and the Russian forms |
| `em-dash` | hard | em and en dashes in English prose |
| `em-dash-rate` | hard | Russian text over its dash budget |
| `bold-label-list` | hard | three or more list items with bold labels |
| `heading-echo` | hard | a first line that restates the heading above it |
| `vocab` | soft | model-favoured wording, three to a paragraph |
| `hyphen-pair` | soft | data-driven, end-to-end, cross-functional |
| `title-case-heading` | soft | Headings With Every Word Capitalised |
| `emoji-decoration` | soft | emoji used as a bullet |
| `curly-quotes` | soft | curly quotes where straight ones were typed |

## Tests

```bash
python3 tests/test_slopcheck.py
```

21 cases covering each rule, plus a clean-file check, across both languages, and the exclusions. They are written
to fail: break the quote-skipping and two of them go red.

## What this is not

It does not rewrite, score writing quality, or decide whether a text was
generated. Human writing keeps absorbing these habits, and people judging by feel
do little better than chance. A finding means a pattern is present, and the
patterns are worth removing whoever wrote them.

## Credit

Pattern catalogue adapted from
[`blader/humanizer`](https://github.com/blader/humanizer) (MIT) and, through it,
from Wikipedia's [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
maintained by WikiProject AI Cleanup.

Those describe how to rewrite. This one only measures, which is the part you can
put in a pipeline.

## License

MIT. See [LICENSE](LICENSE).

Built by Aleksandr Shulgin ([@Aleksandr_NFA](https://x.com/Aleksandr_NFA)).
