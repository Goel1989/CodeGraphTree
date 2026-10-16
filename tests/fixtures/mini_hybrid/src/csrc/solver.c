#include "solver_api.h"

void kernel_(int *n, double *r);

double c_solve(int n) {
    double r = 0.0;
    kernel_(&n, &r);
    return r;
}
