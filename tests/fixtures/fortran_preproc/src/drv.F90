#include "config.inc"
subroutine driver(n)
  integer, intent(in) :: n
#ifdef HAVE_MPI
  call par_solve(n)
#else
  call seq_solve(n)
#endif
#if defined(USE_GPU) && USE_GPU > 1
  call gpu_kernel(n)
#endif
end subroutine driver
