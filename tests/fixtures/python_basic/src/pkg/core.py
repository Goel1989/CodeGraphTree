"""Core helpers."""
import functools


def tracer(fn):
    @functools.wraps(fn)
    def wrapper(*args):
        return fn(*args)
    return wrapper


class Base:
    def setup(self):
        return self.check()

    def check(self):
        return True


class Solver(Base):
    @tracer
    def run(self, n):
        self.setup()
        return compute(n)


def compute(n):
    return n * 2
