"""Well-known symbols defined outside the repository (libc, MPI, BLAS/LAPACK, HDF5...)."""

from __future__ import annotations

import re

LIBC = frozenset("""
printf fprintf sprintf snprintf vprintf vfprintf vsprintf vsnprintf puts fputs fgets gets fopen fclose freopen fread
fwrite fseek ftell fflush feof ferror rewind getc putc getchar putchar fgetc fputc ungetc scanf sscanf fscanf remove
rename tmpfile tmpnam perror malloc calloc realloc free aligned_alloc memcpy memmove memset memcmp memchr strlen
strnlen strcpy strncpy strcat strncat strcmp strncmp strchr strrchr strstr strtok strdup strndup strerror strspn
strcspn strpbrk strcoll atoi atof atol atoll strtol strtoll strtod strtof strtoul strtoull exit _exit abort atexit
getenv setenv unsetenv system qsort bsearch abs labs llabs div ldiv rand srand time clock difftime mktime localtime
gmtime strftime asctime ctime sqrt sqrtf pow powf exp expf log logf log10 log2 sin cos tan asin acos atan atan2
sinh cosh tanh fabs fabsf floor ceil round trunc fmod fmin fmax hypot cbrt erf erfc tgamma lgamma isnan isinf
isfinite assert isalpha isdigit isalnum isspace isupper islower toupper tolower signal raise setjmp longjmp
va_start va_end va_arg va_copy open close read write lseek stat fstat mkdir rmdir unlink access getcwd chdir sleep
usleep fork execv execvp waitpid getpid dlopen dlsym dlclose dlerror gettimeofday clock_gettime nanosleep
""".split())

_BLAS = re.compile(r"^(i?[sdcz](gemm|gemv|axpy|dot|dotc|dotu|scal|copy|nrm2|swap|trsm|trsv|trmm|trmv|ger|geru"
                   r"|gerc|syrk|syr2k|symm|symv|hemm|hemv|herk|asum|amax|rot|rotg|gbmv|sbmv|spmv|tbmv|tbsv"
                   r"|getrf|getrs|getri|gesv|gesvd|gesdd|geev|gels|gelsd|potrf|potrs|potri|posv|syev|syevd|heev"
                   r"|sygv|geqrf|orgqr|ormqr|trtrs|lacpy|lange|lamch|gbsv|gtsv|ptsv|sysv|hesv|stev|steqr))_?$")


def external_for(lang: str, name: str) -> str | None:
    """uid of a known external symbol called from ``lang``, or None."""
    low = name.lower().rstrip("_") if lang == "fortran" else name
    if lang in ("c", "cpp"):
        if re.match(r"^_?Py[A-Z_]\w*$", name) or name.startswith("NPY_"):
            return f"ext:python_capi:{name}"
        if lang == "cpp" and re.match(r"^(py|pybind11|boost|Eigen|mpi|MPI|petsc)::", name):
            return f"ext:{name.split('::', 1)[0].lower()}:{name}"
        if name in LIBC:
            return f"ext:libc:{name}"
        if name.startswith("MPI_") or name.startswith("PMPI_"):
            return f"ext:mpi:{name}"
        if name.startswith("pthread_"):
            return f"ext:pthread:{name}"
        if re.match(r"^H5[A-Z]", name):
            return f"ext:hdf5:{name}"
        if name.startswith("std::"):
            return f"ext:cpp:{name}"
        if _BLAS.match(name.lower().rstrip("_")) and name.endswith("_"):
            return f"ext:blas:{name.lower().rstrip('_')}"
        if name.startswith(("cblas_", "LAPACKE_")):
            return f"ext:blas:{name}"
    if lang == "fortran":
        if low.startswith("mpi_"):
            return f"ext:mpi:{low}"
        if _BLAS.match(low):
            return f"ext:blas:{low}"
        if re.match(r"^h5[a-z]+_f$", low):
            return f"ext:hdf5:{low}"
    return None
