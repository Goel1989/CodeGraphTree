module state
  implicit none
  real :: temperature
  integer :: nsteps = 0
end module state

subroutine advance(dt)
  use state
  implicit none
  real, intent(in) :: dt
  common /counters/ icount
  integer :: icount
  temperature = temperature + dt
  nsteps = nsteps + 1
  icount = icount + 1
end subroutine advance

subroutine report_state(out)
  use state, only: temperature
  implicit none
  real, intent(out) :: out
  out = temperature
end subroutine report_state
