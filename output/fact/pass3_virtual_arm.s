l0:
MOV Xt1, #2;
CMP Xn, Xt1;
B.GE l2;
l1:
MOV X0, Xa;
RET;
B l3;
l2:
SUB Xt2, Xn, #1;
MUL Xt3, Xn, Xa;
MOV Xn, Xt2;
MOV Xa, Xt3;
B l0;
l3: