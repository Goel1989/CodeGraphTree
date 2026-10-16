#include "util.h"

static int helper(int x) { return x * 2; }

int util_b(int x) {
    int y = helper(x);
    return util_a(y);
}
