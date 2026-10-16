      SUBROUTINE UPDATE(N)
      INTEGER N, I
      INCLUDE 'vars.inc'
      COMMON /WORK/ RBUF(100), IBUF
      DO 10 I = 1, N
         TBL(I) = RBUF(I) + SQRT(TBL(I))
         VAL = MAX(IBUF, I) + ABS(XGLOB(I)) + ZR(I)
         CALL FLUSHB(RBUF(1))
   10 CONTINUE
      END
