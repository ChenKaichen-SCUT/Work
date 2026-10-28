/* Our C11 transcription of Moir--Anderson (1995), Figures 2 and 4.
 * DOI: 10.1016/0167-6423(95)00009-H. Original: atomic/SC registers.
 * Default: deliberate all-release/acquire port, NOT a correct renaming claim.
 * Define SPLITTER_SC for a sequentially consistent reference implementation.
 * There are no auxiliary competing writes. Each fresh grid is used once.
 * The Python extractor preserves branch reads, not this program's local work.
 */
#include <stdatomic.h>
#include <stdbool.h>

typedef struct { atomic_int x; atomic_bool y; } splitter;
typedef enum { MOVE_STOP, MOVE_RIGHT, MOVE_DOWN } direction;

#ifdef SPLITTER_SC
#define STORE_ORDER memory_order_seq_cst
#define LOAD_ORDER memory_order_seq_cst
#else
#define STORE_ORDER memory_order_release
#define LOAD_ORDER memory_order_acquire
#endif

/* Initialize every grid cell before starting its participating threads. */
void splitter_init(splitter *s) {
    atomic_init(&s->x, 0); /* bottom; callers use positive, distinct identifiers */
    atomic_init(&s->y, false);
}

direction splitter_visit(splitter *s, int id) {
    atomic_store_explicit(&s->x, id, STORE_ORDER);        /* wx, Figure 4: 0 */
    if (atomic_load_explicit(&s->y, LOAD_ORDER))         /* ry, Figure 4: 1 */
        return MOVE_RIGHT;
    atomic_store_explicit(&s->y, true, STORE_ORDER);     /* wy, Figure 4: 2 */
    int observed = atomic_load_explicit(&s->x, LOAD_ORDER); /* rx, Figure 4: 3 */
    return observed == id ? MOVE_STOP : MOVE_DOWN;
}

/* grid holds (participants-1)^2 cells, with only the triangle accessed.
 * A name can also be returned at the triangle boundary without another visit.
 * This is one call on one fresh grid; it does not implement Figure 5 reuse.
 */
int splitter_rename(splitter *grid, int participants, int id) {
    int row = 0, col = 0;
    while (row + col < participants-1) {
        direction d = splitter_visit(&grid[row*(participants-1)+col], id);
        if (d == MOVE_STOP) break;
        if (d == MOVE_RIGHT) ++col;
        else ++row;
    }
    return row*participants - row*(row-1)/2 + col;
}
