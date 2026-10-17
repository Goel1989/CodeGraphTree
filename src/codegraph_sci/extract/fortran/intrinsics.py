"""Fixed list of Fortran intrinsic procedures (standard up to F2018 + common legacy specific names)."""

INTRINSICS = frozenset("""
abs achar acos acosd acosh adjustl adjustr aimag aint all allocated anint any asin asind asinh associated
atan atan2 atan2d atand atanh atomic_add atomic_and atomic_cas atomic_define atomic_fetch_add atomic_ref
bessel_j0 bessel_j1 bessel_jn bessel_y0 bessel_y1 bessel_yn bge bgt bit_size ble blt btest ceiling char
cmplx co_broadcast co_max co_min co_reduce co_sum command_argument_count conjg cos cosd cosh count
cpu_time cshift date_and_time dble digits dim dot_product dprod dshiftl dshiftr eoshift epsilon erf erfc
erfc_scaled event_query execute_command_line exp exponent extends_type_of findloc floor fraction gamma
get_command get_command_argument get_environment_variable huge hypot iachar iall iand iany ibclr ibits
ibset ichar ieor image_index index int ior iparity ishft ishftc is_contiguous is_iostat_end is_iostat_eor
kind lbound lcobound leadz len len_trim lge lgt lle llt log log10 log_gamma logical maskl maskr matmul
max maxexponent maxloc maxval merge merge_bits mvbits min minexponent minloc minval mod modulo move_alloc
nearest new_line nint norm2 not null num_images out_of_range pack parity popcnt poppar precision present
product radix random_init random_number random_seed range rank real reduce repeat reshape rrspacing
same_type_as scale scan selected_char_kind selected_int_kind selected_real_kind set_exponent shape shifta
shiftl shiftr sign sin sind sinh size sizeof spacing spread sqrt storage_size sum system_clock tan tand
tanh this_image tiny trailz transfer transpose trim ubound ucobound unpack verify c_loc c_funloc
c_f_pointer c_f_procpointer c_associated c_sizeof loc
alog alog10 amax0 amax1 amin0 amin1 amod cabs ccos cexp clog csin csqrt dabs dacos dasin datan datan2
dcmplx dconjg dcos dcosh ddim dexp dfloat dimag dint dlog dlog10 dmax1 dmin1 dmod dnint dsign dsin dsinh
dsqrt dtan dtanh float iabs idim idint idnint ifix isign max0 max1 min0 min1 sngl zabs zexp zlog zsqrt
zcos zsin dreal flush exit getenv iargc getarg etime dtime second rand srand irand system
""".split())

# Intrinsic modules: a USE of these is external, never unresolved.
INTRINSIC_MODULES = frozenset({
    "iso_c_binding", "iso_fortran_env", "ieee_arithmetic", "ieee_exceptions", "ieee_features",
    "omp_lib", "omp_lib_kinds", "openacc", "mpi", "mpi_f08",
})
