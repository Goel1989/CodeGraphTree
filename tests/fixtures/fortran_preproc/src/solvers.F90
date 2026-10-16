#ifdef HAVE_MPI
subroutine par_solve(n)
  integer, intent(in) :: n
  call kernel(n)
end subroutine par_solve
#endif
subroutine seq_solve(n)
  integer, intent(in) :: n
  call kernel(n)
end subroutine seq_solve

#ifdef DOUBLE
subroutine kernel(n)
  integer, intent(in) :: n
end subroutine kernel
#else
subroutine kernel(n)
  integer, intent(in) :: n
  call legacy_kernel(n)
end subroutine kernel
#endif
