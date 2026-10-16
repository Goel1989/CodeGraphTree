module mesh
  implicit none
contains
  subroutine build_mesh(n)
    integer, intent(in) :: n
    call refine(n)
  end subroutine build_mesh
end module mesh
