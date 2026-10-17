"""Prepare a real-code corpus locally from its manifest (corrective audit §10).

The sources of an analysed code base are never stored in this repository. This script fetches them at the exact
revision named by ``tests/corpus/<code>/manifest.yaml``:

    source:
      path: "<local folder>"          # where the sources go (or --dest)
      revision: "<tag or commit>"
      repository: "<Git URL or path>"
      sparse: [<folders>]             # optional sparse checkout (cone mode)

Usage:
    python tools/prepare_corpus.py tests/corpus/code_aster_start/manifest.yaml [--dest FOLDER]

It needs Git, and network access when the repository is remote; the analysis itself never does. The result is
checked: the checkout must be the requested tag or commit.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def _git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def prepare(manifest_path: Path, dest: Path | None = None) -> Path:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    source = manifest.get("source") or {}
    repository, revision = source.get("repository"), str(source.get("revision", ""))
    if not repository or not revision or revision.lower() == "none":
        raise SystemExit(f"error: {manifest_path} needs source.repository and an exact source.revision")
    target = dest or Path(str(source["path"]))
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"error: {target} is not empty")
    sparse = [str(s).strip("/") for s in source.get("sparse") or []]
    _git("clone", "--filter=blob:none", "--no-checkout", str(repository), str(target))
    if sparse:
        _git("sparse-checkout", "set", "--cone", *sparse, cwd=target)
    _git("checkout", "--quiet", revision, cwd=target)
    commit = _git("rev-parse", "HEAD", cwd=target)
    tags = _git("tag", "--points-at", "HEAD", cwd=target).split()
    if revision not in tags and not commit.startswith(revision):
        raise SystemExit(f"error: checkout {commit[:12]} is not revision {revision}")
    print(f"{manifest.get('corpus')}: {repository} @ {revision} ({commit[:12]}) in {target}"
          + (f", sparse: {', '.join(sparse)}" if sparse else ""))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifest")
    parser.add_argument("--dest", help="folder for the sources (default: source.path of the manifest)")
    args = parser.parse_args()
    prepare(Path(args.manifest), Path(args.dest) if args.dest else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
