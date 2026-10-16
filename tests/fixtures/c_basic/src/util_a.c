#include "util.h"

static int helper(int x) { return x + 1; }

int util_a(int x) { return helper(x) + SQUARE(x); }
