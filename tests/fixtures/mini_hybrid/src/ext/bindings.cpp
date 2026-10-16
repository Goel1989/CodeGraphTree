#include "solver_api.h"

namespace hybrid {
double solve(int n) {
    return c_solve(n);
}
}

PYBIND11_MODULE(hybrid_ext, m) {
    m.def("solve", &hybrid::solve);
}
