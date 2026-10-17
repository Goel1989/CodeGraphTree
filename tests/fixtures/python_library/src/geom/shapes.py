"""Shapes."""
import math


class Shape:
    def area(self):
        return 0.0


class Circle(Shape):
    def __init__(self, r):
        self.r = r

    def area(self):
        return math.pi * self.r * self.r


def area_of(shape):
    return shape.area()
