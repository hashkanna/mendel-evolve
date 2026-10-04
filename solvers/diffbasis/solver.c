/* Seed solver for difference bases (problems/diffbasis): n marks, maximise v, the largest integer
 * such that every 1..v is a difference of two marks; the score is n^2 / v (lower is better).
 *
 * Search: fixed-temperature annealing on U = number of d in 1..T that are not a difference, where T
 * is the target (one more than the best v so far). A move relocates one mark to a free position in
 * 0..W, W = width_factor * T; the difference counts are updated in O(n). When U reaches 0 the set
 * covers 1..T, its true v is read off, it becomes the best set, and the target moves to v + 1.
 *
 *   ./solver --config CFG.json --instance INST.json --seed N (--time S | --iters N) --out OUT.json
 *
 * --iters counts move proposals and is fully deterministic; --time is CPU seconds (clock()).
 * Every random draw comes from one splitmix64 stream seeded by (seed, n). The output is always the
 * best valid set seen, shifted so that its smallest element is 0.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---- random numbers ---------------------------------------------------------------------- */
static uint64_t rng_state;
static uint64_t rnd64(void) {
    uint64_t z = (rng_state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static long rndint(long k) { return (long)(rnd64() % (uint64_t)k); }            /* 0..k-1 */
static double rnd01(void) { return (double)(rnd64() >> 11) * (1.0 / 9007199254740992.0); }

/* ---- tiny readers for the flat JSON files the harness writes ------------------------------ */
static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)len + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t got = fread(buf, 1, (size_t)len, f);
    buf[got] = 0;
    fclose(f);
    return buf;
}
static double json_value(const char *buf, const char *key, double fallback) {
    if (!buf) return fallback;
    char pat[128];
    snprintf(pat, sizeof pat, "\"%s\"", key);
    const char *p = strstr(buf, pat);
    if (!p) return fallback;
    p = strchr(p + strlen(pat), ':');
    if (!p) return fallback;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (!strncmp(p, "true", 4)) return 1.0;
    if (!strncmp(p, "false", 5)) return 0.0;
    char *end;
    double v = strtod(p, &end);
    return end == p ? fallback : v;
}

/* ---- state -------------------------------------------------------------------------------- */
static int n;
static long *x;              /* positions of the marks */
static unsigned char *occ;   /* occ[p] = 1 if a mark sits at p */
static int *cnt;             /* cnt[d] = number of pairs at distance d */
static long cap;             /* positions and distances are < cap; cnt[cap] stays 0 as a sentinel */
static long T, W;            /* target and window */
static long U;               /* uncovered distances in 1..T */

static void take_out(int i) {
    long xi = x[i];
    for (int j = 0; j < n; j++) {
        if (j == i) continue;
        long d = xi > x[j] ? xi - x[j] : x[j] - xi;
        if (--cnt[d] == 0 && d <= T) U++;
    }
    occ[xi] = 0;
}
static void put_in(int i, long p) {
    x[i] = p;
    occ[p] = 1;
    for (int j = 0; j < n; j++) {
        if (j == i) continue;
        long d = p > x[j] ? p - x[j] : x[j] - p;
        if (cnt[d]++ == 0 && d <= T) U--;
    }
}
static void rebuild(void) {
    memset(cnt, 0, sizeof(int) * (size_t)(cap + 1));
    memset(occ, 0, (size_t)cap);
    for (int i = 0; i < n; i++) occ[x[i]] = 1;
    for (int i = 0; i < n; i++)
        for (int j = i + 1; j < n; j++) cnt[x[i] > x[j] ? x[i] - x[j] : x[j] - x[i]]++;
}
static long prefix_v(void) {
    long v = 0;
    while (v + 1 < cap && cnt[v + 1] > 0) v++;
    return v;
}
static void set_target(long t, double width_factor) {
    T = t;
    long w = (long)(width_factor * (double)T);
    if (w > cap - 1) w = cap - 1;
    if (w > W) W = w;                 /* the window only grows */
    U = 0;
    for (long d = 1; d <= T; d++) U += cnt[d] == 0;
}

/* Wichmann's complete ruler W(r, s): 4r + s + 3 marks, length 4r(r + s + 2) + 3(s + 1). */
static int wichmann(long *out) {
    int best_r = -1;
    long best_len = -1;
    for (int r = 0; 4 * r + 3 <= n; r++) {
        int s = n - 3 - 4 * r;
        long len = 4L * r * (r + s + 2) + 3L * (s + 1);
        if (len > best_len) { best_len = len; best_r = r; }
    }
    if (best_r < 0) return 0;
    int r = best_r, s = n - 3 - 4 * r, k = 0;
    long pos = 0;
    out[k++] = 0;
    struct { int count; long gap; } seg[6] = {{r, 1}, {1, r + 1}, {r, 2 * r + 1}, {s, 4 * r + 3}, {r + 1, 2 * r + 2}, {r, 1}};
    for (int g = 0; g < 6; g++)
        for (int c = 0; c < seg[g].count; c++) out[k++] = (pos += seg[g].gap);
    return k == n;
}

int main(int argc, char **argv) {
    const char *cfg_path = NULL, *inst_path = NULL, *out_path = NULL;
    long seed = 0, iters_budget = -1;
    double time_budget = -1;
    for (int a = 1; a + 1 < argc; a += 2) {
        if (!strcmp(argv[a], "--config")) cfg_path = argv[a + 1];
        else if (!strcmp(argv[a], "--instance")) inst_path = argv[a + 1];
        else if (!strcmp(argv[a], "--seed")) seed = atol(argv[a + 1]);
        else if (!strcmp(argv[a], "--iters")) iters_budget = atol(argv[a + 1]);
        else if (!strcmp(argv[a], "--time")) time_budget = atof(argv[a + 1]);
        else if (!strcmp(argv[a], "--out")) out_path = argv[a + 1];
    }
    if (!out_path) { fprintf(stderr, "--out is required\n"); return 2; }
    if (iters_budget < 0 && time_budget < 0) time_budget = 1.0;
    char *cfg = cfg_path ? slurp(cfg_path) : NULL, *inst = inst_path ? slurp(inst_path) : NULL;
    n = (int)json_value(inst, "n", 2);
    if (n < 1) n = 1;
    if (n > 2000) n = 2000;

    int wichmann_init = json_value(cfg, "wichmann_init", 0) != 0;
    int hole_directed = json_value(cfg, "hole_directed", 0) != 0;
    int restart_from_best = json_value(cfg, "restart_from_best", 0) != 0;
    double temp = json_value(cfg, "temp", 0.5);
    double width_factor = json_value(cfg, "width_factor", 1.25);
    double hole_prob = json_value(cfg, "hole_prob", 0.5);
    long stall_iters = (long)json_value(cfg, "stall_iters", 200000);
    int kick_size = (int)json_value(cfg, "kick_size", 2);
    if (temp < 1e-6) temp = 1e-6;
    if (width_factor < 1.0) width_factor = 1.0;
    if (stall_iters < 1) stall_iters = 1;
    if (kick_size < 1) kick_size = 1;

    rng_state = (uint64_t)seed * 0x2545F4914F6CDD1DULL + (uint64_t)n * 0x9E3779B97F4A7C15ULL + 12345;
    cap = (long)(width_factor * ((double)n * (n - 1) / 2.0 + 2.0)) + 4;
    x = calloc((size_t)n, sizeof(long));
    long *best = calloc((size_t)n, sizeof(long));
    occ = calloc((size_t)cap + 1, 1);
    cnt = calloc((size_t)cap + 1, sizeof(int));
    if (!x || !best || !occ || !cnt) { fprintf(stderr, "out of memory\n"); return 1; }

    /* start: a block 0..a-1 and the multiples a, 2a, ..., ba (covers 1..ab), or a Wichmann ruler */
    if (!(wichmann_init && n >= 3 && wichmann(x))) {
        int a = n / 2 > 0 ? n / 2 : 1, b = n - a;
        for (int i = 0; i < a; i++) x[i] = i;
        for (int j = 1; j <= b; j++) x[a + j - 1] = (long)a * j;
    }
    W = 0;
    for (int i = 0; i < n; i++) if (x[i] > W) W = x[i];
    rebuild();
    long best_v = prefix_v();
    memcpy(best, x, sizeof(long) * (size_t)n);
    set_target(best_v + 1, width_factor);

    double accept[65];
    for (int d = 0; d <= 64; d++) accept[d] = exp(-(double)d / temp);

    size_t trace_cap = 4096, trace_len = 0;
    double *trace = malloc(sizeof(double) * 2 * trace_cap);
    clock_t start = clock();
    long it = 0, since_best = 0;
    if (n >= 2) {
        while (1) {
            if (iters_budget >= 0) {
                if (it >= iters_budget) break;
            } else if ((it & 255) == 0 && (double)(clock() - start) / CLOCKS_PER_SEC >= time_budget) {
                break;
            }
            it++;
            since_best++;
            if (restart_from_best && since_best >= stall_iters) {
                memcpy(x, best, sizeof(long) * (size_t)n);
                rebuild();
                set_target(best_v + 1, width_factor);
                for (int k = 0; k < kick_size; k++) {
                    int i = (int)rndint(n);
                    long p = rndint(W + 1);
                    if (occ[p]) continue;
                    take_out(i);
                    put_in(i, p);
                }
                since_best = 0;
                continue;
            }
            int i = (int)rndint(n);
            long p = -1;
            if (hole_directed && rnd01() < hole_prob) {
                long d = 1 + rndint(T);            /* a missing distance: the first one at or after d */
                for (long scanned = 0; scanned < T && cnt[d] != 0; scanned++) d = d < T ? d + 1 : 1;
                int j = (int)rndint(n);
                long q = (rnd64() & 1) ? x[j] + d : x[j] - d;
                if (j != i && q >= 0 && q <= W) p = q;
            }
            if (p < 0) p = rndint(W + 1);
            if (occ[p]) continue;
            long old = x[i], before = U;
            take_out(i);
            put_in(i, p);
            long delta = U - before;
            if (delta > 0 && rnd01() >= accept[delta > 64 ? 64 : delta]) {
                take_out(i);
                put_in(i, old);
                continue;
            }
            if (U == 0) {
                best_v = prefix_v();
                memcpy(best, x, sizeof(long) * (size_t)n);
                set_target(best_v + 1, width_factor);
                since_best = 0;
                if (trace_len == trace_cap) {
                    trace_cap *= 2;
                    trace = realloc(trace, sizeof(double) * 2 * trace_cap);
                }
                trace[2 * trace_len] = (double)(clock() - start) / CLOCKS_PER_SEC;
                trace[2 * trace_len + 1] = (double)n * n / (double)best_v;
                trace_len++;
            }
        }
    }

    long lo = best[0];
    for (int i = 1; i < n; i++) if (best[i] < lo) lo = best[i];
    FILE *f = fopen(out_path, "w");
    if (!f) { fprintf(stderr, "cannot write %s\n", out_path); return 1; }
    fprintf(f, "{\"solution\": [");
    for (int i = 0; i < n; i++) fprintf(f, "%s%ld", i ? ", " : "", best[i] - lo);
    fprintf(f, "], \"stats\": {\"iters\": %ld, \"v\": %ld, \"window\": %ld, \"trace\": [", it, best_v, W);
    size_t step = trace_len > 2000 ? trace_len / 2000 + 1 : 1;   /* keep the file small at large n */
    int first = 1;
    for (size_t k = 0; k < trace_len; k++) {
        if (k % step && k + 1 != trace_len) continue;
        fprintf(f, "%s[%.6f, %.17g]", first ? "" : ", ", trace[2 * k], trace[2 * k + 1]);
        first = 0;
    }
    fprintf(f, "]}}\n");
    fclose(f);
    return 0;
}
