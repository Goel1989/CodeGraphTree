"""Syntax colouring of the code inspector (one rule set per language) and call-line marking."""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

KEYWORDS = {
    "fortran": r"\b(subroutine|function|program|module|contains|end|call|use|implicit|none|integer|real|logical|"
               r"character|complex|double|precision|dimension|common|external|intrinsic|parameter|if|then|else|"
               r"elseif|endif|do|enddo|while|select|case|interface|type|class|procedure|intent|in|out|inout|"
               r"allocatable|pointer|target|return|stop|continue|cycle|exit|go|to|result|recursive|pure|elemental|"
               r"include|data|save|kind|len)\b",
    "python": r"\b(def|class|return|import|from|as|if|elif|else|for|while|try|except|finally|with|lambda|yield|"
              r"pass|break|continue|raise|global|nonlocal|in|is|not|and|or|None|True|False|self|async|await)\b",
    "c": r"\b(int|char|float|double|void|long|short|unsigned|signed|struct|union|enum|typedef|static|extern|const|"
         r"volatile|if|else|for|while|do|switch|case|default|return|break|continue|goto|sizeof)\b",
    "cpp": r"\b(int|char|float|double|void|long|short|unsigned|signed|struct|union|enum|typedef|static|extern|"
           r"const|volatile|if|else|for|while|do|switch|case|default|return|break|continue|goto|sizeof|class|"
           r"namespace|template|typename|public|private|protected|virtual|override|new|delete|this|using|auto|"
           r"bool|true|false|nullptr|std|const_cast|static_cast|dynamic_cast|reinterpret_cast)\b",
}
COMMENTS = {"fortran": r"!.*$", "python": r"#.*$", "c": r"//.*$", "cpp": r"//.*$"}
STRINGS = r"'[^'\n]*'|\"[^\"\n]*\""
PREPROC = r"^\s*#\s*\w+.*$"


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    f.setFontItalic(italic)
    return f


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, lang: str | None, extra_keywords: list[str] | None = None) -> None:
        super().__init__(document)
        self.rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        flags = re.IGNORECASE if lang == "fortran" else 0
        if lang in KEYWORDS:
            self.rules.append((re.compile(KEYWORDS[lang], flags), _fmt("#1f4e9c", bold=True)))
        if extra_keywords:
            words = "|".join(re.escape(w) for w in extra_keywords)
            self.rules.append((re.compile(rf"\b({words})\b", re.IGNORECASE), _fmt("#1f4e9c", bold=True)))
        if lang in ("c", "cpp", "fortran"):
            self.rules.append((re.compile(PREPROC), _fmt("#8a5a00")))
        self.rules.append((re.compile(STRINGS), _fmt("#2e7d32")))
        if lang in COMMENTS:
            self.rules.append((re.compile(COMMENTS[lang]), _fmt("#7a7a7a", italic=True)))
        if lang == "fortran":
            self.rules.append((re.compile(r"^[cC*].*$"), _fmt("#7a7a7a", italic=True)))
        self.fixed_form = False

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for rx, fmt in self.rules:
            if rx.pattern == r"^[cC*].*$" and not self.fixed_form:
                continue
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
