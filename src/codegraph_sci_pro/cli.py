"""Commands of the Pro extension, added to ``cgs`` through the ``codegraph_sci.commands`` entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _ai_worker(args: argparse.Namespace) -> int:
    from codegraph_sci_pro.ai.models import load_model
    from codegraph_sci_pro.ai.worker import serve

    return serve(load_model(args.model))


def _complete(args: argparse.Namespace) -> int:
    from codegraph_sci.core.project import open_project
    from codegraph_sci_pro.ai.complete import Completion
    from codegraph_sci_pro.ai.worker import AIClient

    project = open_project(args.root, args.project)
    client = AIClient(args.model, in_process=args.in_process)
    try:
        proposals = Completion(project, client, auto=args.auto, document=Path(args.document) if args.document
                               else None, max_iterations=args.max_iterations).run()
    finally:
        client.close()
    for p in proposals:
        state = ("adopted" if args.auto else "proposed") if p.accepted else "rejected"
        print(f"[{state}] {p.kind} {p.target}: {p.reason}  {json.dumps(p.checks, default=str)}")
        if p.preview:
            print(f"    preview: +{p.preview['added']} link(s), -{p.preview['removed']}")
            for ex in p.preview["examples"][:5]:
                print(f"      {ex['file']}:{ex['line']} {ex['target']} -> {ex['dst']}")
    print(f"{client.calls} model call(s)")
    return 0


def _approve(args: argparse.Namespace) -> int:
    from codegraph_sci.core.project import open_project
    from codegraph_sci_pro.ai.complete import set_rule_status

    set_rule_status(open_project(args.root, args.project), args.id, "rejected" if args.reject else "approved")
    print(f"{args.id}: {'rejected' if args.reject else 'approved'} (run `cgs scan` to apply)")
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("ai-worker", help="local AI model process (JSON on stdin/stdout, no network)")
    p.add_argument("--model", required=True, help="model .gguf file, or fake:<responses.json>")
    p.set_defaults(func=_ai_worker)
    p = sub.add_parser("complete", help="AI: identify unknown languages and define missing keywords")
    p.add_argument("root")
    p.add_argument("--project")
    p.add_argument("--model", required=True, help="model .gguf file, or fake:<responses.json>")
    p.add_argument("--auto", action="store_true", help="adopt proposals that pass every check")
    p.add_argument("--document", help="technical document about the language (text, Markdown, PDF)")
    p.add_argument("--max-iterations", type=int, default=3)
    p.add_argument("--in-process", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=_complete)
    p = sub.add_parser("ai-approve", help="approve (or reject) a proposed rule or keyword profile")
    p.add_argument("root")
    p.add_argument("id", help="rule id (r-0001) or language name")
    p.add_argument("--project")
    p.add_argument("--reject", action="store_true")
    p.set_defaults(func=_approve)


__all__ = ["register", "sys"]
