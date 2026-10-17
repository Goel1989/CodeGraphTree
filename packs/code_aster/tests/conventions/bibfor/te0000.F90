subroutine te0000(numc)
    integer :: numc
    select case (numc)
    case (1)
        call te0001()
    end select
end subroutine te0000
