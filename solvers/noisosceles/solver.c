/*
 * Mendel seed solver for "subsets of the grid with no isosceles triangles" (problem pack: noisosceles).
 *
 *   ./solver --config CFG.json --instance INSTANCE.json --seed N (--time SECONDS | --iters N) --out OUT.json
 *
 * Method: tabu search at a fixed number of units, in exact integer arithmetic. The working set may contain
 * forbidden triples; V counts them. While V > 0 a step takes out one unit that is in a forbidden triple and
 * puts in the unit that creates the fewest new ones (recently removed units are tabu). When V reaches 0 the
 * set is recorded and one more unit is added. A unit is a point, or a mirror orbit when `symmetric` is on.
 *
 * Geometry. Three distinct grid points {g, x, y} are forbidden iff one of them is equidistant from the other
 * two. A grid triangle is never equilateral, so a forbidden triple has exactly one apex. For a pair of
 * members (q, a) the grid points g that complete a forbidden triple are therefore the disjoint union of
 *   - the lattice points on the perpendicular bisector of q and a          (apex g),
 *   - the lattice points on the circle around a through q, except q        (apex a),
 *   - the lattice points on the circle around q through a, except a        (apex q).
 * Circles are enumerated from a table of lattice vectors by squared length; the bisector is walked from
 * the midpoint in steps of the primitive vector perpendicular to a - q.
 *
 * Data structure.
 *   cnt[g]    for every grid point g: the number of forbidden triples {g, x, y} with x, y members
 *             (in the symmetric phase only at orbit representatives, see orbit_pairs).
 *             For a non-member it is the number of violations that adding g would create; for a member it
 *             is the number of violations g is part of. V = sum over members / 3.
 *   pc[h]     symmetric phase, per orbit representative h: the number of forbidden triples made of two
 *             points of the orbit of h and one member outside it (from a precomputed reverse index), so
 *             that the cost of adding an orbit, 4 * cnt[h] + pc[h], is exact (and 4 * cnt[h] - pc[h] is
 *             what removing a member orbit gains). Only four-point orbits are units; points on a mirror
 *             axis wait for the point-by-point phase.
 *   Adding or removing a member costs one pass over the other members (a few dozen counter updates each).
 *
 * Phases. With `symmetric` on, the first sym_fraction of the budget searches over orbits; then the best
 * symmetric set is reloaded with full counters and the same loop continues with single points as units.
 * A kick (after `patience` steps without a new best) returns to the best set and removes a random part.
 * Compile with -DDEBUG_CHECK to compare V with a brute-force count every 500 steps.
 *
 * Genes. All of them live in Config, read once in load_config(). A switch that is off must not change
 * behaviour or consume random numbers: guard new ideas with `if (cfg.<switch>) { ... }` and leave the
 * existing path untouched.
 *
 * Build: cc -O3 -o solver solver.c -lm
 */

#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef uint64_t u64;

#define MAXN 256 /* largest grid side; the tables take memory proportional to n^2 */

/* ------------------------------------------------------------------ genes */

typedef struct {
    /* idea switches (default off) */
    int symmetric;     /* search over mirror orbits (4 points), then polish without the constraint */
    int greedy_victim; /* take out the unit in the most forbidden triples instead of a random conflicted one */
    int hollow;        /* only use points near the border of the grid */
    /* numeric alleles */
    int tabu_tenure;          /* a removed unit stays out for tabu_tenure .. 2 * tabu_tenure steps */
    int patience;             /* iterations without a new best before a kick */
    double kick_fraction;     /* fraction of the best set removed by a kick */
    double sym_fraction;      /* share of the budget spent in the symmetric phase (of symmetric) */
    int axis_shift_x;         /* mirror x -> n - 1 + axis_shift_x - x (of symmetric) */
    int axis_shift_y;         /* mirror y -> n - 1 + axis_shift_y - y (of symmetric) */
    double band_frac;         /* hollow keeps points within band_frac * n of the border (of hollow) */
} Config;

static Config cfg;

static void die(const char *msg) {
    fprintf(stderr, "solver: %s\n", msg);
    exit(2);
}

/* ------------------------------------------------------------------ flat JSON reader */

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char *)malloc((size_t)len + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t got = fread(buf, 1, (size_t)len, f);
    buf[got] = 0;
    fclose(f);
    return buf;
}

/* Value of "key" in a flat JSON object: numbers as is, true/false as 1/0. Returns dflt if absent. */
static double json_num(const char *text, const char *key, double dflt) {
    char pat[96];
    if (!text) return dflt;
    snprintf(pat, sizeof pat, "\"%s\"", key);
    const char *s = text;
    size_t plen = strlen(pat);
    while ((s = strstr(s, pat)) != NULL) {
        const char *t = s + plen;
        while (*t == ' ' || *t == '\t' || *t == '\n' || *t == '\r') t++;
        if (*t != ':') { s += plen; continue; } /* the pattern was a value, not a key */
        t++;
        while (*t == ' ' || *t == '\t' || *t == '\n' || *t == '\r') t++;
        if (!strncmp(t, "true", 4)) return 1.0;
        if (!strncmp(t, "false", 5)) return 0.0;
        char *end;
        double v = strtod(t, &end);
        return end == t ? dflt : v;
    }
    return dflt;
}

static void load_config(const char *path) {
    char *text = path ? slurp(path) : NULL;
    if (path && !text) die("cannot read config");
    cfg.symmetric = json_num(text, "symmetric", 0) != 0;
    cfg.greedy_victim = json_num(text, "greedy_victim", 0) != 0;
    cfg.hollow = json_num(text, "hollow", 0) != 0;
    cfg.tabu_tenure = (int)json_num(text, "tabu_tenure", 3);
    cfg.patience = (int)json_num(text, "patience", 20000);
    cfg.kick_fraction = json_num(text, "kick_fraction", 0.15);
    cfg.sym_fraction = json_num(text, "sym_fraction", 0.8);
    cfg.axis_shift_x = (int)json_num(text, "axis_shift_x", 0);
    cfg.axis_shift_y = (int)json_num(text, "axis_shift_y", 0);
    cfg.band_frac = json_num(text, "band_frac", 0.3);
    if (cfg.tabu_tenure < 0) cfg.tabu_tenure = 0;
    if (cfg.patience < 1) cfg.patience = 1;
    if (cfg.kick_fraction < 0) cfg.kick_fraction = 0;
    if (cfg.kick_fraction > 1) cfg.kick_fraction = 1;
    if (cfg.sym_fraction < 0) cfg.sym_fraction = 0;
    if (cfg.sym_fraction > 1) cfg.sym_fraction = 1;
    free(text);
}

/* ------------------------------------------------------------------ RNG: xoshiro256** seeded by splitmix64 */

static u64 rng_s[4];
static u64 splitmix64(u64 *x) {
    u64 z = (*x += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static void rng_seed(u64 seed) {
    for (int i = 0; i < 4; i++) rng_s[i] = splitmix64(&seed);
}
static inline u64 rotl(u64 x, int k) { return (x << k) | (x >> (64 - k)); }
static u64 rng_next(void) {
    u64 r = rotl(rng_s[1] * 5, 7) * 9, t = rng_s[1] << 17;
    rng_s[2] ^= rng_s[0];
    rng_s[3] ^= rng_s[1];
    rng_s[1] ^= rng_s[2];
    rng_s[0] ^= rng_s[3];
    rng_s[2] ^= t;
    rng_s[3] = rotl(rng_s[3], 45);
    return r;
}
static int rng_below(int bound) { /* uniform in 0..bound-1 (multiply-shift) */
    return (int)(((rng_next() >> 32) * (u64)bound) >> 32);
}
__attribute__((unused)) static double rng_unit(void) { return (double)(rng_next() >> 11) * (1.0 / 9007199254740992.0); }

/* ------------------------------------------------------------------ state */

static int n, G;            /* grid side, number of grid points; id g = x * n + y */
static int *gx, *gy;
static int32_t *cnt;        /* forbidden triples {g, member, member} */
static int32_t *pc;         /* symmetric phase: forbidden triples {two points of the orbit of g, member} */
static uint8_t *is_mem;
static uint8_t *allowed;    /* points the search may use (all, or the border band when hollow) */
static uint8_t *orb_ok;     /* the mirror orbit of g exists, is allowed and has no forbidden triple itself */
static uint8_t *msize;      /* orbit size of g */
static int *rep_of;         /* representative of the unit of g: smallest id of its orbit, or g itself */
static int *S, *posS, k;    /* member points; posS = index + 1 */
static int *U, *posU, nU;   /* member units, by representative */
static int *units, nunits;  /* candidate units, by representative */
static long long *tabu_until;
static int *off_start;      /* lattice vectors by squared length: off_start[d] .. off_start[d + 1] */
static int16_t *off_dx, *off_dy;
static int16_t *gcdtab;     /* gcd(|vx|, |vy|) at index |vx| * n + |vy| */
static int *rb_start, *rb_rep; /* reverse index: point z -> orbits with an internal pair that forbids z */
static int *pbuf;           /* scratch for enum_pair */
static int cxm, cym;        /* mirror: x -> cxm - x, y -> cym - y */
static int sym_active;      /* the symmetric phase is running */
static int internal_error;  /* set if an invariant is ever violated; output is re-verified regardless */
static long long V;         /* forbidden triples inside the working set */

static u64 n_iters, n_point_ops, n_kicks, n_valid_hits;

/* All grid points g such that {g, q, a} is a forbidden triple. Returns how many were written to buf. */
static int enum_pair(int q, int a, int *buf) {
    const int qx = gx[q], qy = gy[q], ax = gx[a], ay = gy[a];
    const int vx = ax - qx, vy = ay - qy;
    const int d = vx * vx + vy * vy;
    const unsigned un = (unsigned)n;
    int m = 0;
    for (int i = off_start[d]; i < off_start[d + 1]; i++) {
        const int dx = off_dx[i], dy = off_dy[i];
        int x = ax + dx, y = ay + dy; /* circle around a through q */
        if ((unsigned)x < un && (unsigned)y < un) {
            const int g = x * n + y;
            if (g != q) buf[m++] = g;
        }
        x = qx + dx; y = qy + dy; /* circle around q through a */
        if ((unsigned)x < un && (unsigned)y < un) {
            const int g = x * n + y;
            if (g != a) buf[m++] = g;
        }
    }
    /* perpendicular bisector: g = (q + a) / 2 + (j / 2) * u with u primitive, perpendicular to a - q */
    const int gg = gcdtab[abs(vx) * n + abs(vy)];
    const int ux = -vy / gg, uy = vx / gg;
    const int sx = qx + ax, sy = qy + ay;
    int px, py;
    if (!(sx & 1) && !(sy & 1)) { px = sx; py = sy; }
    else if (!((sx ^ ux) & 1) && !((sy ^ uy) & 1)) { px = sx + ux; py = sy + uy; }
    else return m; /* the bisector misses the lattice */
    const int x0 = px / 2, y0 = py / 2; /* px, py are even, so this is exact */
    for (int x = x0, y = y0; (unsigned)x < un && (unsigned)y < un; x += ux, y += uy) buf[m++] = x * n + y;
    for (int x = x0 - ux, y = y0 - uy; (unsigned)x < un && (unsigned)y < un; x -= ux, y -= uy) buf[m++] = x * n + y;
    return m;
}

static inline void apply_pair(int q, int a, int delta) {
    const int m = enum_pair(q, a, pbuf);
    for (int i = 0; i < m; i++) {
        const int g = pbuf[i];
        if (allowed[g]) cnt[g] += delta;
    }
}

static void add_point(int q) {
    n_point_ops++;
    V += cnt[q]; /* the pairs below never touch q itself */
    for (int i = 0; i < k; i++) apply_pair(q, S[i], +1);
    S[k] = q;
    posS[q] = ++k;
    is_mem[q] = 1;
}

static void remove_point(int q) {
    n_point_ops++;
    const int i = posS[q] - 1;
    const int last = S[--k];
    S[i] = last;
    posS[last] = i + 1;
    posS[q] = 0;
    is_mem[q] = 0;
    for (int j = 0; j < k; j++) apply_pair(q, S[j], -1);
    V -= cnt[q];
}

/* The mirror orbit of p (1, 2 or 4 distinct points); 0 if a mirror image leaves the grid. */
static int orbit(int p, int *o) {
    const int x = gx[p], y = gy[p], mx = cxm - x, my = cym - y;
    if (mx < 0 || mx >= n || my < 0 || my >= n) return 0;
    int m = 0;
    o[m++] = p;
    if (mx != x) o[m++] = mx * n + y;
    if (my != y) {
        o[m++] = x * n + my;
        if (mx != x) o[m++] = mx * n + my;
    }
    return m;
}

static int dist2(int a, int b) {
    const int dx = gx[a] - gx[b], dy = gy[a] - gy[b];
    return dx * dx + dy * dy;
}

/*
 * Symmetric phase. The member set is a union of four-point orbits, so cnt is the same at the four images of
 * a point and is kept only at orbit representatives. For the pairs (image of h, member a), mirroring both
 * points shows that their combined effect on a representative r equals the number of points of the orbit
 * of r on the forbidden set of the single pair (h, a'), summed over all members a': one folded pass over
 * the members instead of four. The six pairs inside the new orbit are applied directly.
 */
static void orbit_pairs(int h, const int *o, int delta) {
    for (int i = 0; i < k; i++) {
        const int m = enum_pair(h, S[i], pbuf);
        for (int t = 0; t < m; t++) cnt[rep_of[pbuf[t]]] += delta;
    }
    for (int i = 0; i < 4; i++)
        for (int j = i + 1; j < 4; j++) {
            const int m = enum_pair(o[i], o[j], pbuf);
            for (int t = 0; t < m; t++) {
                const int g = pbuf[t];
                if (rep_of[g] == g) cnt[g] += delta;
            }
        }
    for (int e = rb_start[h]; e < rb_start[h + 1]; e++) pc[rb_rep[e]] += 4 * delta;
}

static void add_orbit(int h) { /* h is the representative of a four-point orbit outside the set */
    int o[4];
    orbit(h, o);
    n_point_ops++;
    V += 4LL * cnt[h] + pc[h];
    orbit_pairs(h, o, +1);
    for (int i = 0; i < 4; i++) {
        S[k] = o[i];
        posS[o[i]] = ++k;
        is_mem[o[i]] = 1;
    }
}

static void remove_orbit(int h) {
    int o[4];
    orbit(h, o);
    n_point_ops++;
    for (int i = 0; i < 4; i++) {
        const int q = o[i], at = posS[q] - 1, last = S[--k];
        S[at] = last;
        posS[last] = at + 1;
        posS[q] = 0;
        is_mem[q] = 0;
    }
    orbit_pairs(h, o, -1);
    V -= 4LL * cnt[h] + pc[h];
}

static void add_unit(int h) {
    if (sym_active) add_orbit(h);
    else add_point(h);
    U[nU] = h;
    posU[h] = ++nU;
}

static void remove_unit(int h) {
    if (sym_active) remove_orbit(h);
    else remove_point(h);
    const int i = posU[h] - 1;
    const int last = U[--nU];
    U[i] = last;
    posU[last] = i + 1;
    posU[h] = 0;
}

/* New forbidden triples if the non-member unit h were added (exact). */
static inline long long unit_cost(int h) {
    return sym_active ? 4LL * cnt[h] + pc[h] : (long long)cnt[h];
}
/* Forbidden triples that would disappear if the member unit h were removed (exact). */
static inline long long unit_gain(int h) {
    return sym_active ? 4LL * cnt[h] - pc[h] : (long long)cnt[h];
}

/* The cheapest unit to add that is not tabu (a tabu unit is allowed if it makes the set valid). */
static int pick_entering(void) {
    int bestu = -1, ties = 0;
    long long bestc = LLONG_MAX;
    for (int i = 0; i < nunits; i++) {
        const int h = units[i];
        if (posU[h]) continue;
        const long long c = unit_cost(h);
        if (c > bestc) continue;
        if (tabu_until[h] > (long long)n_iters && V + c != 0) continue;
        if (c < bestc) { bestc = c; bestu = h; ties = 1; }
        else if (rng_below(++ties) == 0) bestu = h;
    }
    return bestu;
}

/* A member unit that is part of a forbidden triple: a random one, or the worst when greedy_victim. */
static int pick_victim(int avoid) {
    int pick = -1, ties = 0;
    long long bestg = -1;
    for (int i = 0; i < nU; i++) {
        const int h = U[i];
        if (cnt[h] <= 0 || h == avoid) continue;
        if (cfg.greedy_victim) {
            const long long g = unit_gain(h);
            if (g < bestg) continue;
            if (g > bestg) { bestg = g; pick = h; ties = 1; }
            else if (rng_below(++ties) == 0) pick = h;
        } else if (rng_below(++ties) == 0) {
            pick = h;
        }
    }
    if (pick < 0 && avoid >= 0 && posU[avoid] && cnt[avoid] > 0) pick = avoid;
    return pick;
}

/* Exact brute-force validity of a point list: every apex must see pairwise different distances. */
static int set_is_valid(const int *ids, int m, int *stamp) {
    const int maxd = 2 * (n - 1) * (n - 1);
    for (int d = 0; d <= maxd; d++) stamp[d] = -1;
    for (int b = 0; b < m; b++)
        for (int a = 0; a < m; a++) {
            if (a == b) continue;
            const int d = dist2(ids[a], ids[b]);
            if (d == 0 || stamp[d] == b) return 0;
            stamp[d] = b;
        }
    return 1;
}

/* ------------------------------------------------------------------ search */

static int *best, nbest;
static double trace_t[4096];
static int trace_v[4096], ntrace;

static double cpu_now(void) { return (double)clock() / (double)CLOCKS_PER_SEC; }

static void note_best(void) {
    nbest = k;
    memcpy(best, S, (size_t)k * sizeof(int));
    if (ntrace < 4096) {
        trace_t[ntrace] = cpu_now();
        trace_v[ntrace++] = nbest;
    }
}

static void load_best(void) { /* make the best set the working set */
    while (nU > 0) remove_unit(U[nU - 1]);
    for (int i = 0; i < nbest; i++)
        if (rep_of[best[i]] == best[i]) add_unit(best[i]);
}

/* End of the symmetric phase: continue from the best symmetric set with single points as units. */
static void enter_point_mode(void) {
    sym_active = 0;
    k = nU = nunits = 0;
    V = 0;
    for (int g = 0; g < G; g++) {
        cnt[g] = 0;
        is_mem[g] = 0;
        posS[g] = posU[g] = 0;
        rep_of[g] = g;
        tabu_until[g] = 0;
        if (allowed[g]) units[nunits++] = g;
    }
    for (int i = 0; i < nbest; i++) add_unit(best[i]); /* counters are rebuilt at every allowed point */
    if (V != 0) internal_error = 1;
}

int main(int argc, char **argv) {
    const char *cfg_path = NULL, *inst_path = NULL, *out_path = NULL;
    u64 seed = 1;
    double time_budget = -1;
    long long iter_budget = -1;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--config")) cfg_path = argv[i + 1];
        else if (!strcmp(argv[i], "--instance")) inst_path = argv[i + 1];
        else if (!strcmp(argv[i], "--seed")) seed = strtoull(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--time")) time_budget = atof(argv[i + 1]);
        else if (!strcmp(argv[i], "--iters")) iter_budget = atoll(argv[i + 1]);
        else if (!strcmp(argv[i], "--out")) out_path = argv[i + 1];
        else die("unknown argument");
    }
    if (!inst_path || !out_path) die("usage: solver --config CFG.json --instance INSTANCE.json --seed N (--time S | --iters N) --out OUT.json");
    if (time_budget < 0 && iter_budget < 0) die("need --time or --iters");
    load_config(cfg_path);
    char *inst = slurp(inst_path);
    if (!inst) die("cannot read instance");
    n = (int)json_num(inst, "n", 0);
    free(inst);
    if (n < 1 || n > MAXN) die("instance n must be in 1..256");
    G = n * n;
    const int maxd = 2 * (n - 1) * (n - 1);

    gx = (int *)malloc(sizeof(int) * (size_t)G);
    gy = (int *)malloc(sizeof(int) * (size_t)G);
    cnt = (int32_t *)calloc((size_t)G, sizeof(int32_t));
    pc = (int32_t *)calloc((size_t)G, sizeof(int32_t));
    is_mem = (uint8_t *)calloc((size_t)G, 1);
    allowed = (uint8_t *)calloc((size_t)G, 1);
    orb_ok = (uint8_t *)calloc((size_t)G, 1);
    msize = (uint8_t *)calloc((size_t)G, 1);
    rep_of = (int *)malloc(sizeof(int) * (size_t)G);
    S = (int *)malloc(sizeof(int) * (size_t)(G + 8));
    posS = (int *)calloc((size_t)G, sizeof(int));
    U = (int *)malloc(sizeof(int) * (size_t)(G + 8));
    posU = (int *)calloc((size_t)G, sizeof(int));
    units = (int *)malloc(sizeof(int) * (size_t)(G + 8));
    tabu_until = (long long *)calloc((size_t)G, sizeof(long long));
    best = (int *)malloc(sizeof(int) * (size_t)(G + 8));
    off_start = (int *)calloc((size_t)maxd + 2, sizeof(int));
    off_dx = (int16_t *)malloc(sizeof(int16_t) * (size_t)(2 * n) * (size_t)(2 * n));
    off_dy = (int16_t *)malloc(sizeof(int16_t) * (size_t)(2 * n) * (size_t)(2 * n));
    gcdtab = (int16_t *)malloc(sizeof(int16_t) * (size_t)G);
    rb_start = (int *)calloc((size_t)G + 2, sizeof(int));
    int *stamp = (int *)malloc(sizeof(int) * ((size_t)maxd + 2));
    if (!gx || !gy || !cnt || !pc || !is_mem || !allowed || !orb_ok || !msize || !rep_of || !S || !posS || !U || !posU ||
        !units || !tabu_until || !best || !off_start || !off_dx || !off_dy || !gcdtab || !rb_start || !stamp)
        die("out of memory");

    for (int g = 0; g < G; g++) { gx[g] = g / n; gy[g] = g % n; rep_of[g] = g; }
    /* lattice vectors grouped by squared length (counting sort) */
    for (int dx = -(n - 1); dx <= n - 1; dx++)
        for (int dy = -(n - 1); dy <= n - 1; dy++) off_start[dx * dx + dy * dy + 1]++;
    int widest = 0;
    for (int d = 0; d <= maxd; d++) {
        if (off_start[d + 1] > widest) widest = off_start[d + 1];
        off_start[d + 1] += off_start[d];
    }
    {
        int *fill = (int *)malloc(sizeof(int) * ((size_t)maxd + 2));
        if (!fill) die("out of memory");
        memcpy(fill, off_start, sizeof(int) * ((size_t)maxd + 2));
        for (int dx = -(n - 1); dx <= n - 1; dx++)
            for (int dy = -(n - 1); dy <= n - 1; dy++) {
                const int d = dx * dx + dy * dy;
                off_dx[fill[d]] = (int16_t)dx;
                off_dy[fill[d]] = (int16_t)dy;
                fill[d]++;
            }
        free(fill);
    }
    pbuf = (int *)malloc(sizeof(int) * ((size_t)2 * (size_t)widest + (size_t)2 * (size_t)n + 16));
    if (!pbuf) die("out of memory");
    for (int a = 0; a < n; a++)
        for (int b = 0; b < n; b++) {
            int x = a, y = b;
            while (y) { const int t = x % y; x = y; y = t; }
            gcdtab[a * n + b] = (int16_t)x;
        }

    /* candidate points */
    int band = n; /* depth below which points are allowed */
    if (cfg.hollow) {
        band = (int)ceil(cfg.band_frac * n);
        if (band < 1) band = 1;
    }
    for (int g = 0; g < G; g++) {
        int depth = gx[g];
        if (gy[g] < depth) depth = gy[g];
        if (n - 1 - gx[g] < depth) depth = n - 1 - gx[g];
        if (n - 1 - gy[g] < depth) depth = n - 1 - gy[g];
        allowed[g] = depth < band;
    }
    cxm = n - 1;
    cym = n - 1;
    sym_active = cfg.symmetric;
    if (cfg.symmetric) {
        cxm += cfg.axis_shift_x;
        cym += cfg.axis_shift_y;
        for (int g = 0; g < G; g++) {
            int o[4];
            const int m = orbit(g, o);
            int ok = m == 4; /* points on a mirror axis wait for the polish phase */
            for (int i = 0; i < m && ok; i++) ok = allowed[o[i]];
            for (int b = 0; b < m && ok; b++) /* no forbidden triple inside the orbit (it would be a square) */
                for (int a = 0; a < m && ok; a++)
                    for (int c = a + 1; c < m && ok; c++)
                        if (a != b && c != b && dist2(o[a], o[b]) == dist2(o[c], o[b])) ok = 0;
            orb_ok[g] = (uint8_t)ok;
            msize[g] = (uint8_t)m;
            int rep = g;
            for (int i = 1; i < m; i++) if (o[i] < rep) rep = o[i];
            rep_of[g] = rep;
        }
        for (int g = 0; g < G; g++)
            if (orb_ok[g] && rep_of[g] == g) units[nunits++] = g;
        /* reverse index: which orbits have an internal pair that forbids point z */
        for (int pass = 0; pass < 2; pass++) {
            int *fill = NULL;
            if (pass == 1) {
                for (int g = 0; g < G; g++) rb_start[g + 1] += rb_start[g];
                rb_rep = (int *)malloc(sizeof(int) * ((size_t)rb_start[G] + 1));
                fill = (int *)malloc(sizeof(int) * ((size_t)G + 1));
                if (!rb_rep || !fill) die("out of memory");
                memcpy(fill, rb_start, sizeof(int) * (size_t)G);
            }
            for (int u = 0; u < nunits; u++) {
                int o[4];
                const int h = units[u], m = orbit(h, o);
                for (int i = 0; i < m; i++)
                    for (int j = i + 1; j < m; j++) {
                        const int c = enum_pair(o[i], o[j], pbuf);
                        for (int t = 0; t < c; t++) {
                            const int z = pbuf[t];
                            if (!allowed[z]) continue;
                            if (pass == 0) rb_start[z + 1]++;
                            else rb_rep[fill[z]++] = h;
                        }
                    }
            }
            free(fill);
        }
    } else {
        for (int g = 0; g < G; g++)
            if (allowed[g]) units[nunits++] = g;
    }
    rng_seed(seed);

    const long long sym_iters = (cfg.symmetric && iter_budget >= 0) ? (long long)(cfg.sym_fraction * (double)iter_budget) : -1;
    const double sym_time = (cfg.symmetric && time_budget >= 0) ? cfg.sym_fraction * time_budget : -1;
    long long since_best = 0;
    int last_added = -1;
    while (1) {
        if (iter_budget >= 0 && (long long)n_iters >= iter_budget) break;
        if (time_budget >= 0 && (n_iters & 15) == 0) {
            const double now = cpu_now();
            if (now >= time_budget) break;
            if (sym_active && iter_budget < 0 && now >= sym_time) { enter_point_mode(); since_best = 0; last_added = -1; }
        }
        if (sym_active && sym_iters >= 0 && (long long)n_iters >= sym_iters) { enter_point_mode(); since_best = 0; last_added = -1; }
        n_iters++;
#ifdef DEBUG_CHECK
        if (n_iters % 500 == 0) { /* compare V with a brute-force count of forbidden triples */
            long long bv = 0;
            for (int b = 0; b < k; b++)
                for (int a = 0; a < k; a++)
                    for (int c = a + 1; c < k; c++)
                        if (a != b && c != b && dist2(S[a], S[b]) == dist2(S[c], S[b])) bv++;
            if (bv != V) { fprintf(stderr, "DEBUG_CHECK: iter %llu V=%lld brute=%lld sym=%d k=%d\n", (unsigned long long)n_iters, V, bv, sym_active, k); exit(3); }
        }
#endif
        if (V == 0 && k > nbest) { note_best(); since_best = 0; n_valid_hits++; }
        if (since_best >= cfg.patience) { /* kick: back to the best set, minus a random part of it */
            since_best = 0;
            n_kicks++;
            load_best();
            int out = (int)ceil(cfg.kick_fraction * (double)nU);
            if (out < 1) out = 1;
            for (int u = 0; u < out && nU > 0; u++) remove_unit(U[rng_below(nU)]);
            last_added = -1;
            continue;
        }
        since_best++;
        if (V > 0) { /* take out a unit that is in a forbidden triple */
            const int v = pick_victim(last_added);
            if (v < 0) { internal_error = 1; break; }
            remove_unit(v);
            tabu_until[v] = (long long)n_iters + cfg.tabu_tenure + (cfg.tabu_tenure > 0 ? rng_below(cfg.tabu_tenure + 1) : 0);
        }
        /* put in the cheapest unit: this restores the size after a removal, or grows a valid set by one */
        const int h = pick_entering();
        if (h >= 0) { add_unit(h); last_added = h; }
    }
    if (V == 0 && k > nbest) note_best();

    /* the output is re-verified from scratch; if that ever failed, fall back to a valid subset */
    int *out = (int *)malloc(sizeof(int) * (size_t)(G + 8));
    if (!out) die("out of memory");
    int nout = 0;
    const int ok = set_is_valid(best, nbest, stamp);
    if (ok) {
        nout = nbest;
        memcpy(out, best, (size_t)nbest * sizeof(int));
    } else {
        fprintf(stderr, "solver: internal error, best set failed the self-check; repairing\n");
        for (int i = 0; i < nbest; i++) {
            out[nout++] = best[i];
            if (!set_is_valid(out, nout, stamp)) nout--;
        }
    }
    for (int i = 1; i < nout; i++) { /* canonical order */
        int v = out[i], j = i - 1;
        while (j >= 0 && out[j] > v) { out[j + 1] = out[j]; j--; }
        out[j + 1] = v;
    }
    FILE *f = fopen(out_path, "w");
    if (!f) die("cannot write output");
    fprintf(f, "{\"solution\": [");
    for (int i = 0; i < nout; i++) fprintf(f, "%s[%d, %d]", i ? ", " : "", gx[out[i]], gy[out[i]]);
    fprintf(f, "], \"stats\": {\"iters\": %llu, \"trace\": [", (unsigned long long)n_iters);
    for (int i = 0; i < ntrace; i++) fprintf(f, "%s[%.4f, %d]", i ? ", " : "", trace_t[i], trace_v[i]);
    fprintf(f, "], \"cpu_seconds\": %.4f, \"point_ops\": %llu, \"kicks\": %llu, \"final_violations\": %lld, \"self_check\": %s}}\n",
            cpu_now(), (unsigned long long)n_point_ops, (unsigned long long)n_kicks, V,
            (ok && !internal_error) ? "true" : "false");
    fclose(f);
    return 0;
}
