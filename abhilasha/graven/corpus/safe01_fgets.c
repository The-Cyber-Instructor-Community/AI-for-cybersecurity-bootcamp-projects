#include <stdio.h>
int main(){char buf[64];if(fgets(buf,sizeof(buf),stdin))fputs(buf,stdout);return 0;}
