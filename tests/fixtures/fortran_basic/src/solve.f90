subroutine solve(n)
  implicit none
  integer, intent(in) :: n
  real :: x
  real, external :: norm2v
  x = norm2v(n)
  call report(x)
end subroutine solve

real function norm2v(n)
  implicit none
  integer, intent(in) :: n
  norm2v = real(n)
end function norm2v

subroutine report(x)
  real, intent(in) :: x
  print *, x
end subroutine report
