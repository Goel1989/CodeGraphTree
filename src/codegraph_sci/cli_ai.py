"""AI commands of ``cgs`` (local model only): ``ai-worker``, ``complete``, ``ai-proposals``, ``ai-approve``,
``ai-policy``, ``ai-diagnose``.

The analysis itself (``cgs scan``) never imports this module nor ``codegraph_sci.ai``. Proposals follow one
lifecycle (draft -> validated -> approved, or rejected); only ``ai-approve`` activates one (phase 9).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _ai_worker(args: argparse.Namespace) -> int:
    from codegraph_sci.ai.models import load_model
    from codegraph_sci.ai.worker import serve

    return serve(load_model(args.model))


def _complete(args: argparse.Namespace) -> int:
    from codegraph_sci.ai.complete import Completion
    from codegraph_sci.ai.proposals import ProposalError
    from codegraph_sci.ai.worker import AIClient
    from codegraph_sci.core.project import open_project

    project = open_project(args.root, args.project)
    client = AIClient(args.model, in_process=args.in_process)
    try:
        completion = Completion(project, client, auto=args.auto,
                                document=Path(args.document) if args.document else None,
                                expected=Path(args.expected) if args.expected else None,
                                max_iterations=args.max_iterations)
        if completion.doc.status not in ("none", "read"):
            print(f"warning: document {completion.doc.path} not used ({completion.doc.status}: {completion.doc.error})",
                  file=sys.stderr)
        proposals = completion.run()
    except ProposalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()
    for p in proposals:
        print(f"[{p.status}] {p.id} {p.kind} {p.target}: {p.reason}  {json.dumps(p.checks, default=str)}")
        if p.preview:
            print(f"    preview: +{p.preview['added']} link(s), -{p.preview['removed']}")
            for ex in p.preview["examples"][:5]:
                print(f"      {ex['file']}:{ex['line']} {ex['target']} -> {ex['dst']}")
    pending = [p.id for p in proposals if p.status == "validated"]
    if pending:
        print(f"Nothing is active yet: review, then `cgs ai-approve {args.root} <id>` ({', '.join(map(str, pending))}) "
              "and `cgs scan`.")
    print(f"{client.calls} model call(s)")
    return 0


def _proposals(args: argparse.Namespace) -> int:
    from codegraph_sci.ai.proposals import list_proposals
    from codegraph_sci.core.project import open_project

    items = list_proposals(open_project(args.root, args.project))
    if args.json:
        print(json.dumps([p.to_dict() for p in items], indent=1, ensure_ascii=False, default=str))
        return 0
    for p in items:
        print(f"{p.id}  {p.status:<9} {p.kind:<11} {p.target}: {p.validation.get('reason', '')}")
    if not items:
        print("no proposal")
    return 0


def _approve(args: argparse.Namespace) -> int:
    from codegraph_sci.ai.complete import set_rule_status
    from codegraph_sci.ai.proposals import ProposalError, approve, reject
    from codegraph_sci.core.project import open_project

    project = open_project(args.root, args.project)
    if re.fullmatch(r"p-\d{4,}", args.id):
        try:
            if args.reject:
                reject(project, args.id, args.reason or "rejected by the user")
                print(f"{args.id}: rejected (nothing changed in the analysis)")
            else:
                proposal = approve(project, args.id)
                print(f"{args.id}: approved — {proposal.activation.get('summary', '')} (run `cgs scan` to apply)")
        except ProposalError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    set_rule_status(project, args.id, "rejected" if args.reject else "approved")  # rules of earlier versions
    print(f"{args.id}: {'rejected' if args.reject else 'approved'} (run `cgs scan` to apply)")
    return 0


def _policy(args: argparse.Namespace) -> int:
    from codegraph_sci.ai.proposals import auto_approval_enabled, set_auto_approval
    from codegraph_sci.core.project import open_project

    project = open_project(args.root, args.project)
    if args.auto_approve is not None:
        set_auto_approval(project, args.auto_approve == "on")
    print(f"automatic approval of validated AI proposals: {'on' if auto_approval_enabled(project) else 'off'}")
    return 0


def _diagnose(args: argparse.Namespace) -> int:
    import dataclasses

    from codegraph_sci.ai.diagnose import diagnose
    from codegraph_sci.core.project import open_project

    found = diagnose(open_project(args.root, args.project))
    if args.json:
        print(json.dumps([dataclasses.asdict(d) for d in found], indent=1, ensure_ascii=False))
        return 0
    for d in found:
        print(f"{d.kind:<20} {d.target:<24} {d.count:>5}  {d.detail}" + (f"  e.g. {', '.join(d.examples[:3])}"
                                                                        if d.examples else ""))
    if not found:
        print("nothing to report: every file is read by an installed package")
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("ai-worker", help="local AI model process (JSON on stdin/stdout, no network)")
    p.add_argument("--model", required=True, help="model .gguf file, or fake:<responses.json>")
    p.set_defaults(func=_ai_worker)
    p = sub.add_parser("complete", help="AI: propose language overrides, language packages and bridge rules")
    p.add_argument("root")
    p.add_argument("--project")
    p.add_argument("--model", required=True, help="model .gguf file, or fake:<responses.json>")
    p.add_argument("--auto", action="store_true",
                   help="approve validated proposals through the project policy (cgs ai-policy)")
    p.add_argument("--document", help="technical document about the language (text, Markdown, PDF)")
    p.add_argument("--expected", help="folder of <case>.<ext> + <case>.expected.json written by hand: the "
                                      "independent results a language proposal is validated against")
    p.add_argument("--max-iterations", type=int, default=3)
    p.add_argument("--in-process", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=_complete)
    p = sub.add_parser("ai-proposals", help="list AI proposals and their status")
    p.add_argument("root")
    p.add_argument("--project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_proposals)
    p = sub.add_parser("ai-approve", help="approve (activate) or reject a validated AI proposal")
    p.add_argument("root")
    p.add_argument("id", help="proposal id (p-0001); rule ids of earlier versions (r-0001, language) also work")
    p.add_argument("--project")
    p.add_argument("--reject", action="store_true")
    p.add_argument("--reason", help="reason of a rejection")
    p.set_defaults(func=_approve)
    p = sub.add_parser("ai-policy", help="show or set the automatic approval policy of a project")
    p.add_argument("root")
    p.add_argument("--project")
    p.add_argument("--auto-approve", choices=["on", "off"])
    p.set_defaults(func=_policy)
    p = sub.add_parser("ai-diagnose", help="what is not covered and why (deterministic, no model)")
    p.add_argument("root")
    p.add_argument("--project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_diagnose)


__all__ = ["register", "sys"]
