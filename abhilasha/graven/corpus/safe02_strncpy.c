#include <string.h>
#include <stdio.h>
void greet(char *n){char buf[64];strncpy(buf,n,sizeof(buf)-1);buf[63]='\0';printf("%s\n",buf);}
int main(int c,char**v){if(c>1)greet(v[1]);return 0;}
