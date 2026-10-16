"""C++ adapter (tree-sitter-cpp)."""

from __future__ import annotations

from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.cfamily import CFamilyExtractor

ADAPTER = "cpp"
VERSION = "1.1"


class CppAdapter:
    name = ADAPTER
    version = VERSION
    languages = ["cpp"]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
        facts = CFamilyExtractor("cpp", file.path, file.text, file.encoding, ctx, ADAPTER, VERSION).run()
        facts.variant = file.variant
        return facts
