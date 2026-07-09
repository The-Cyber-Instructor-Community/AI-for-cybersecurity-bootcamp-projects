#include <stdio.h>
void fmt(char *u){char out[40];snprintf(out,sizeof(out),"user=%s",u);puts(out);}
int main(int c,char**v){if(c>1)fmt(v[1]);return 0;}
