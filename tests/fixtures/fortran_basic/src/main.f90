program main
  use mesh_mod
  implicit none
  integer :: n
  n = 10
  call build_mesh(n)
  call solve(n)
end program main
