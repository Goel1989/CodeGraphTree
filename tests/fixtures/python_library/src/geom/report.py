from geom import area_of
from geom.shapes import Circle


def describe(r):
    c = Circle(r)
    return round(area_of(c), 2)
