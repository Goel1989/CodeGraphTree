subroutine update_state(name, n)
  character(len=*), intent(in) :: name
  integer, intent(in) :: n
  character(len=24) :: vals
  integer :: jv
  vals = name//'.VALUES'
  call mem_get('solver.state.VALUES', 'R', jv)
  call mem_get(vals, 'W', jv)
  call mem_get('TMP_WORK', 'W', jv)
  call mem_new('solver.state.FLAGS')
  call mem_free('TMP_WORK')
  call elem_dispatch(n)
end subroutine update_state

subroutine elem_dispatch(itype)
  integer, intent(in) :: itype
  select case (itype)
  case (1)
    call elem_001()
  case (2)
    call elem_002()
  case (3)
    call elem_003()
  end select
end subroutine elem_dispatch

subroutine elem_001()
end subroutine elem_001

subroutine elem_002()
end subroutine elem_002

subroutine mem_get(n, m, j)
  character(len=*) :: n, m
  integer :: j
end subroutine mem_get

subroutine mem_new(n)
  character(len=*) :: n
end subroutine mem_new

subroutine mem_free(n)
  character(len=*) :: n
end subroutine mem_free

subroutine run_static()
end subroutine run_static
