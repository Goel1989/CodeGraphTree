"""C adapter (tree-sitter-c)."""

from __future__ import annotations

from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.cfamily import CFamilyExtractor

ADAPTER = "c"
VERSION = "1.1"


class CAdapter:
    name = ADAPTER
    version = VERSION
    languages = ["c"]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
        facts = CFamilyExtractor("c", file.path, file.text, file.encoding, ctx, ADAPTER, VERSION).run()
        facts.variant = file.variant
        return facts
