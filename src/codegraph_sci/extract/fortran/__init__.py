"""Fortran adapter: statement parser, with the pattern extractor as fallback."""

from __future__ import annotations

from codegraph_sci.core.facts import FileFacts, ParseError, SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.fortran.parser import ADAPTER, VERSION, HardParseError, extract_fortran
from codegraph_sci.extract.fortran.patterns import extract_patterns


class FortranAdapter:
    name = ADAPTER
    version = VERSION
    languages = ["fortran"]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
        try:
            return extract_fortran(file.path, file.text, file.encoding, file.variant, ctx)
        except (HardParseError, RecursionError, ValueError, IndexError) as exc:
            facts = extract_patterns(file.path, file.text, file.encoding, file.variant)
            facts.errors.insert(0, ParseError(f"statement parser failed: {exc}"))
            facts.adapter, facts.adapter_version = ADAPTER, VERSION
            return facts


__all__ = ["FortranAdapter", "extract_fortran", "extract_patterns"]
