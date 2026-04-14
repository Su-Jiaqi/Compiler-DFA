l0:
MOV Xx, #10;
MOV Xy, #3;
ADD Xz, Xx, Xy;
CMP Xz, Xy;
B.LT l2;
l1:
MUL Xz, Xz, Xy;
MOV X0, Xz;
RET;
l2:
MOV X0, #0;
RET;