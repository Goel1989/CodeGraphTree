C     Legacy fixed-form solver
      SUBROUTINE SOLVE(N, A)
      INTEGER N
      DOUBLE PRECISION A(N)
      INCLUDE 'consts.inc'
      CALL SCALE(N, A)
      END
