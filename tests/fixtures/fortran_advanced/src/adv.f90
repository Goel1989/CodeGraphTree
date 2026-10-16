module shapes
  implicit none
  type :: circle
    real :: r
  contains
    procedure :: area => circle_area
  end type circle
  interface scale
    module procedure scale_int, scale_real
  end interface scale
  procedure(op_iface), pointer :: op_ptr => null()
  abstract interface
    subroutine op_iface(x)
      real, intent(inout) :: x
    end subroutine op_iface
  end interface
contains
  real function circle_area(self)
    class(circle), intent(in) :: self
    circle_area = 3.14 * self%r**2
  end function circle_area
  subroutine scale_int(k)
    integer, intent(inout) :: k
    k = 2 * k
  end subroutine scale_int
  subroutine scale_real(x)
    real, intent(inout) :: x
    x = 2.0 * x
  end subroutine scale_real
  recursive subroutine walk(depth)
    integer, intent(in) :: depth
    real :: a
    type(circle) :: c
    if (depth > 0) call walk(depth - 1)
    call scale(a)
    a = c%area()
    call op_ptr(a)
  end subroutine walk
end module shapes
