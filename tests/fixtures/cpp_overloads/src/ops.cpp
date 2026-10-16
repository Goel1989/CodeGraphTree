namespace ops {
void scale(int v) { (void)v; }
void scale(double v) { (void)v; }
void scale(int a, int b) { (void)a; (void)b; }
}

template <typename T>
void apply(T value) {
    ops::scale(value);
}

void run(int n, double x) {
    ops::scale(n);
    ops::scale(x);
    ops::scale(1, 2);
    ops::scale(2.5);
    apply(n);
}
