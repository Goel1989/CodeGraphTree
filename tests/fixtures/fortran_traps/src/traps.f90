! Commentaire accentué : élément (Latin-1)
SUBROUTINE Traps(N)
  INTEGER N
  CHARACTER(LEN=40) :: msg
  ! call fake_in_comment(n)
  msg = 'call fake_in_string(n)'
  msg = "it's call fake2(n)" ! call fake3(n)
  Call Mixed_Case(N); call second_on_line(n)
  CALL &
    continued(n)
END SUBROUTINE Traps

subroutine MIXED_CASE(n)
  integer n
end subroutine mixed_case

subroutine Second_On_Line(n)
  integer n
end subroutine

subroutine continued(n)
  integer n
end subroutine continued
