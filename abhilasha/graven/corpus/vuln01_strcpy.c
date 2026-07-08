#include <string.h>
#include <stdio.h>
void greet(char *name){char buf[64];strcpy(buf,name);printf("%s\n",buf);}
int main(int c,char**v){if(c>1)greet(v[1]);return 0;}
