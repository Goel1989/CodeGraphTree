import fastmath
from fastmath import norm


def use(v):
    return fastmath.dot(v, v) + norm(v)
