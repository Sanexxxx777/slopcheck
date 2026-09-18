# What changed in the parser

The parser now reads the header before the body. That fixes the case where a
truncated file produced a row count of zero instead of an error.

Two things still break. Files written by the old exporter carry a BOM, which the
header check treats as part of the first column name. And a file larger than
2 GB falls back to the slow path, because the mmap call refuses it on this
kernel.

I left the BOM case alone for now. Stripping it here would hide a real problem
in the exporter, and that is the thing worth fixing.
