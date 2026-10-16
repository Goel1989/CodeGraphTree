int FORT_CALL_LOCAL(int n) { return n; }

void run_all(int n) {
    FORT_CALL_ASSEMBLE(n);
    FORT_CALL_SOLVE(n);
    FORT_CALL_SOLVE(n + 1);
    FORT_CALL_EXPORT(n);
    FORT_CALL_LOCAL(n);
}
