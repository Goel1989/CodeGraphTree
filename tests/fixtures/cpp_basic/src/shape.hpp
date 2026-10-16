#pragma once
namespace geo {
class Shape {
public:
    virtual ~Shape() = default;
    virtual double area() const = 0;
    double scaled(double k) const;
};
class Square : public Shape {
public:
    explicit Square(double s) : side_(s) {}
    double area() const override { return side_ * side_; }
private:
    double side_;
};
}
