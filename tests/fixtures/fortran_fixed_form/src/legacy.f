C     Fixed-form legacy code
      SUBROUTINE ASSEMB(N, K)
      INTEGER N
      DOUBLE PRECISION K(N,N)
* comment line with CALL FAKE1(N)
      CALL ELEMK(N,
     &           K)
c     CALL FAKE2(N)
      CALL BOUND(N, K)                                                  CALL FAKE3
      RETURN
      END

      SUBROUTINE ELEMK(N, K)
      INTEGER N
      DOUBLE PRECISION K(N,N)
      K(1,1) = 1.0D0
      END

      SUBROUTINE BOUND(N, K)
      INTEGER N
      DOUBLE PRECISION K(N,N)
      CALL ELEMK(N, K)
      END
