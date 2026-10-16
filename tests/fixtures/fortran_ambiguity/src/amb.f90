subroutine compute(n, v, fn)
  integer, intent(in) :: n
  real, intent(inout) :: v(n)
  real, external :: fn
  real :: w(10), s
  real :: ext_f
  external :: ext_f
  interface
    real function shape_fn(x)
      real, intent(in) :: x
    end function shape_fn
  end interface
  s = w(2) + v(1)
  s = s + fn(1.0)
  s = s + ext_f(2.0)
  s = s + shape_fn(0.5)
  s = s + helper(3)
  s = s + mystery(4)
  w(3) = s
  call apply(fn)
end subroutine compute

real function helper(k)
  integer, intent(in) :: k
  helper = k * 2.0
end function helper

real function shape_fn(x)
  real, intent(in) :: x
  shape_fn = x
end function shape_fn
