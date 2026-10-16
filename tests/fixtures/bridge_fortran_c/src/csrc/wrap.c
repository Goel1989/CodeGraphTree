void compute_(int *n);
void COMPUTE2(int *n);

void c_entry(int n) {
    compute_(&n);
    COMPUTE2(&n);
    legacy_double__(&n);
}

void c_callback_(int *n) {
    (void)n;
}
