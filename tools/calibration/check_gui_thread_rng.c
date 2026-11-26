#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { unsigned seed; int seed_worker; int values[8]; } Sample;
static unsigned __stdcall worker(void *arg) {
    Sample *s=(Sample *)arg;
    if(s->seed_worker)srand(s->seed);
    for(int i=0;i<8;++i)s->values[i]=rand();
    return 0;
}
static int run(Sample *s) {
    HANDLE h=(HANDLE)_beginthreadex(NULL,0,worker,s,0,NULL);
    if(!h)return 1;
    WaitForSingleObject(h,INFINITE);CloseHandle(h);return 0;
}
int main(void) {
    Sample a={0},b={0},c={12345,1,{0}},d={98765,1,{0}};
    srand(12345);if(run(&a))return 1;
    srand(98765);if(run(&b)||run(&c)||run(&d))return 2;
    printf("Main seed 12345, unseeded fresh worker:");for(int i=0;i<8;++i)printf(" %d",a.values[i]);puts("");
    printf("Main seed 98765, unseeded fresh worker:");for(int i=0;i<8;++i)printf(" %d",b.values[i]);puts("");
    printf("Worker seeded 12345:");for(int i=0;i<8;++i)printf(" %d",c.values[i]);puts("");
    printf("Worker seeded 98765:");for(int i=0;i<8;++i)printf(" %d",d.values[i]);puts("");
    if(memcmp(a.values,b.values,sizeof(a.values))!=0)return 3;
    if(memcmp(c.values,d.values,sizeof(c.values))==0)return 4;
    puts("Confirmed: main-thread srand does not seed new workers; unseeded workers restart the default stream.");
    return 0;
}
