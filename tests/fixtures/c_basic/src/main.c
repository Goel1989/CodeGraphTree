#include <stdio.h>
#include "util.h"

int main(void) {
    int r = util_b(2) + CALL_A(3);
    printf("%d\n", r);
    return 0;
}
