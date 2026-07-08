#include <string.h>
#include <stdio.h>
void copy(char *in){char dst[24];strcpy(dst,in);puts(dst);}
int main(int c,char**v){if(c>1)copy(v[1]);return 0;}
