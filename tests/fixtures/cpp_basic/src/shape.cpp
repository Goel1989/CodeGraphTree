#include "shape.hpp"
#define LOG_CALL(f) log_call(#f)

static void log_call(const char *name) { (void)name; }

namespace geo {
double Shape::scaled(double k) const {
    LOG_CALL(scaled);
    return k * area();
}
}

double total(const geo::Square &sq) {
    return sq.scaled(2.0) + sq.area();
}
