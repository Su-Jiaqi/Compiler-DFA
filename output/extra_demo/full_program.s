.global _start
.section .text

_start:
    MOV X10, #0
    MOV X11, #0
    MOV X9, #0
    BL my_func

    // Linux AArch64 sys_exit(status = X0)
    MOV X8, #93
    SVC #0

my_func:
l0:
    MOV X9, #10;
    MOV X10, #3;
    ADD X11, X9, X10;
    CMP X11, X10;
    B.LT l2;
l1:
    MUL X11, X11, X10;
    MOV X0, X11;
    RET;
l2:
    MOV X0, #0;
    RET;
