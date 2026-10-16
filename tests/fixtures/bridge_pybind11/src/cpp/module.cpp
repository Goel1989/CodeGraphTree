namespace fm {
double dot(int a, int b) { return a * b; }
double norm(int a) { return a; }
}

PYBIND11_MODULE(fastmath, m) {
    m.def("dot", &fm::dot);
    m.def("norm", &fm::norm, "Euclidean norm");
}
