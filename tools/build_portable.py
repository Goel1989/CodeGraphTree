"""Build the portable folder (PyInstaller onedir), its archive and SHA-256.

Usage: python tools/build_portable.py [--with-model]
Network is only used to install build dependencies; the produced folder never accesses it.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def platform_tag() -> str:
    if sys.platform == "win32":
        return "windows-x64"
    return f"linux-{platform.machine()}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-model", action="store_true",
                        help="name the folder for the variant with a bundled model (same software, same features)")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    from codegraph_sci.core.versions import APP_VERSION

    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                           "--distpath", str(DIST / "build"), "--workpath", str(DIST / "work"),
                           str(ROOT / "packaging" / "codegraph_sci.spec")])
    built = DIST / "build" / "CodeGraph-Sci"
    name = f"CodeGraph-Sci-{APP_VERSION}-{platform_tag()}" + ("-with-model" if args.with_model else "")
    target = DIST / name
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(built), str(target))
    for sub in ("packs", "models", "data"):
        (target / sub).mkdir(exist_ok=True)
    shutil.copytree(ROOT / "packs", target / "packs", dirs_exist_ok=True)  # domain packs shipped with the product
    shutil.copytree(ROOT / "packaging" / "licenses", target / "licenses", dirs_exist_ok=True)
    shutil.copy(ROOT / "packaging" / "README.txt", target / "README.txt")
    archive = shutil.make_archive(str(target), "zip" if sys.platform == "win32" else "gztar",
                                  root_dir=DIST, base_dir=name)
    digest = sha256(Path(archive))
    Path(archive + ".sha256").write_text(f"{digest}  {Path(archive).name}\n", encoding="ascii")
    print(f"folder:  {target} ({folder_size(target) / 1e6:.0f} MB)")
    print(f"archive: {archive}\nsha256:  {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
