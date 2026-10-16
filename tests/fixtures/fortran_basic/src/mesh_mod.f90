module mesh_mod
  implicit none
contains
  subroutine build_mesh(n)
    integer, intent(in) :: n
    call refine(n)
  end subroutine build_mesh

  subroutine refine(n)
    integer, intent(in) :: n
    print *, n
  end subroutine refine
end module mesh_mod
