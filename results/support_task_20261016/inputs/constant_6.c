#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#include <stddef.h>
int result[24];
atomic_int x0;
atomic_int x1;
atomic_int x2;
atomic_int x3;
void *worker0(void *unused) {
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
result[0] = atomic_load_explicit(&x1, memory_order_acquire);
result[1] = atomic_load_explicit(&x2, memory_order_acquire);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
result[2] = atomic_load_explicit(&x1, memory_order_acquire);
result[3] = atomic_load_explicit(&x2, memory_order_acquire);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
result[4] = atomic_load_explicit(&x1, memory_order_acquire);
result[5] = atomic_load_explicit(&x2, memory_order_acquire);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
result[6] = atomic_load_explicit(&x1, memory_order_acquire);
result[7] = atomic_load_explicit(&x2, memory_order_acquire);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 1, memory_order_release);
result[8] = atomic_load_explicit(&x1, memory_order_acquire);
result[9] = atomic_load_explicit(&x2, memory_order_acquire);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x0, 0, memory_order_release);
result[10] = atomic_load_explicit(&x1, memory_order_acquire);
result[11] = atomic_load_explicit(&x2, memory_order_acquire);
return NULL;
}
void *worker1(void *unused) {
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
result[12] = atomic_load_explicit(&x0, memory_order_acquire);
result[13] = atomic_load_explicit(&x3, memory_order_acquire);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
result[14] = atomic_load_explicit(&x0, memory_order_acquire);
result[15] = atomic_load_explicit(&x3, memory_order_acquire);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
result[16] = atomic_load_explicit(&x0, memory_order_acquire);
result[17] = atomic_load_explicit(&x3, memory_order_acquire);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
result[18] = atomic_load_explicit(&x0, memory_order_acquire);
result[19] = atomic_load_explicit(&x3, memory_order_acquire);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 1, memory_order_release);
result[20] = atomic_load_explicit(&x0, memory_order_acquire);
result[21] = atomic_load_explicit(&x3, memory_order_acquire);
atomic_store_explicit(&x3, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
atomic_store_explicit(&x2, 1, memory_order_release);
atomic_store_explicit(&x1, 0, memory_order_release);
result[22] = atomic_load_explicit(&x0, memory_order_acquire);
result[23] = atomic_load_explicit(&x3, memory_order_acquire);
return NULL;
}
int main(void) {
atomic_init(&x2, 0);
atomic_init(&x3, 0);
atomic_init(&x0, 0);
atomic_init(&x1, 0);
pthread_t t0; pthread_create(&t0, NULL, worker0, NULL);
pthread_t t1; pthread_create(&t1, NULL, worker1, NULL);
pthread_join(t0, NULL);
pthread_join(t1, NULL);
assert(!(result[0] == 0 && result[1] == 1 && result[2] == 1 && result[3] == 1 && result[4] == 0 && result[5] == 1 && result[6] == 1 && result[7] == 1 && result[8] == 0 && result[9] == 1 && result[10] == 1 && result[11] == 1 && result[12] == 0 && result[13] == 1 && result[14] == 1 && result[15] == 1 && result[16] == 0 && result[17] == 1 && result[18] == 1 && result[19] == 1 && result[20] == 0 && result[21] == 1 && result[22] == 1 && result[23] == 1));
return 0;
}
