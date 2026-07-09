#include <string.h>
#include <stdio.h>
void build(char *e){char buf[48]="prefix-";strcat(buf,e);puts(buf);}
int main(int c,char**v){if(c>1)build(v[1]);return 0;}
