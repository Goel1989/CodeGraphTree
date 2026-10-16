from .core import Solver, compute
from . import core
import os.path


def main():
    s = Solver()
    s.run(3)
    core.compute(1)
    handler = getattr(core, "compute")
    handler(2)
    return os.path.join("a", "b")


if __name__ == "__main__":
    main()
