FDECL(solve, SOLVE);
FDECL(assemble, ASSEMBLE);

int FCALL_LOCAL_HELPER(int n) { return n; }

void driver(int n) {
    FCALL_ASSEMBLE(n);
    FCALL_LOCAL_HELPER(n);
    FCALLX(n);
    MYFCALL_SOLVE(n);
    FCALL_UNKNOWN(n);
    FCALL_X_SOLVE(n);
}
