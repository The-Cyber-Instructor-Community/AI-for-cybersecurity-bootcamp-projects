#include <stdio.h>
void render(char *a,char *b){char s[50];sprintf(s,"%s:%s",a,b);puts(s);}
int main(int c,char**v){if(c>2)render(v[1],v[2]);return 0;}
