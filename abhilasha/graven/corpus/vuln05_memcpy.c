#include <stdio.h>
#include <string.h>
void load(char *src){char buf[64];memcpy(buf,src,200);puts(buf);}
int main(int c,char**v){if(c>1)load(v[1]);return 0;}
