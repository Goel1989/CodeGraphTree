subroutine kernel(n, r)
  integer, intent(in) :: n
  double precision, intent(out) :: r
  r = dble(n)
end subroutine kernel
