subroutine compute(n)
  integer :: n
  interface
    subroutine c_named(k) bind(c, name="c_named_impl")
      integer :: k
    end subroutine c_named
  end interface
  call c_callback(n)
  call c_named(n)
end subroutine compute

subroutine compute2(n)
  integer :: n
end subroutine compute2

subroutine legacy_double(n)
  integer :: n
end subroutine legacy_double

subroutine exported(n) bind(c, name="fort_exported")
  integer :: n
end subroutine exported
