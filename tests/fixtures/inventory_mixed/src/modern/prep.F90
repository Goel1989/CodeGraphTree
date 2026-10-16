subroutine prep()
#ifdef HAVE_MPI
  call mpi_init_wrapper()
#endif
end subroutine prep
