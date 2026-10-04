/* Seed solver for the ring loading problem (problems/ringloading). Written from scratch.

   Representation: u_i = a_i / D, v_i = b_i / D with integers a_i, b_i >= 0 and a_i + b_i <= D, so every
   prefix sum is an integer and the objective is evaluated exactly in int64:

       A = min over sign choices z_i in {b_i, -a_i} of max_k |2 P_k - T|      (score = A / D)

   The minimum is found by depth-first search over the sign choices with the bound
   value >= (max prefix - min prefix), started from the previous minimiser, which usually gives a
   tight bound at once.

   Search: simulated annealing on single coordinates (a_i or b_i moves by 1..step_max grid units),
   in cycles of `cycle` iterations with a linearly falling temperature; each cycle restarts from the
   best state seen with a small random kick.

   Ideas (all off by default; see genes.json):
     tiebreak_critical  among equal A, prefer fewer sign choices that attain the minimum
     ascent_moves       sometimes move all coordinates along a direction that raises every tight
                        sign choice's active term at once (perceptron on their gradients)
     refine_grid        after a cycle without a new best, double the grid denominator D

   Command line (PROTOCOL.md):
     ./solver --config CFG.json --instance INSTANCE.json --seed N (--time S | --iters N) --out OUT.json
   --time is CPU seconds measured here; --iters is deterministic. The output is always a valid solution. */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAXM 24
#define MAX_TRACE 4000

/* ---------------- random numbers: splitmix64 ---------------- */
static uint64_t rng_state;
static uint64_t rnext(void) {
    uint64_t z = (rng_state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static double runif(void) { return (rnext() >> 11) * (1.0 / 9007199254740992.0); }
static int rint_below(int n) { return (int)(rnext() % (uint64_t)n); }

/* ---------------- tiny flat-JSON reader ---------------- */
static char *read_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(n + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t got = fread(buf, 1, n, f);
    buf[got] = 0;
    fclose(f);
    return buf;
}

static double json_num(const char *buf, const char *key, double dflt) {
    char pat[128];
    snprintf(pat, sizeof pat, "\"%s\"", key);
    const char *p = buf ? strstr(buf, pat) : NULL;
    if (!p) return dflt;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p != ':') return dflt;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (!strncmp(p, "true", 4)) return 1.0;
    if (!strncmp(p, "false", 5)) return 0.0;
    char *end;
    double v = strtod(p, &end);
    return end == p ? dflt : v;
}

/* ---------------- the objective ---------------- */
static int M;
static int64_t A[MAXM], B[MAXM];   /* u_i = A[i] / D, v_i = B[i] / D */
static int hint[MAXM];             /* a minimising sign choice of the current state (1: z = -u) */

#define MAX_TIGHT 256
static int64_t g_best, g_count;
static int g_counting, g_collect, g_ntight;
static int g_choice[MAXM], g_arg[MAXM];
static unsigned char g_tight[MAX_TIGHT][MAXM];   /* sign choices attaining the minimum (when collecting) */

static int64_t pattern_value(const int *c) {
    int64_t p = 0, hi = INT64_MIN, lo = INT64_MAX;
    for (int i = 0; i < M; i++) {
        p += c[i] ? -A[i] : B[i];
        if (p > hi) hi = p;
        if (p < lo) lo = p;
    }
    int64_t x = 2 * hi - p, y = p - 2 * lo;
    return x > y ? x : y;
}

static void dfs(int depth, int64_t p, int64_t hi, int64_t lo) {
    for (int k = 0; k < 2; k++) {
        int opt = k ^ hint[depth];   /* the hinted branch first */
        int64_t q = opt ? p - A[depth] : p + B[depth];
        int64_t h = q > hi ? q : hi, l = q < lo ? q : lo;
        int64_t spread = h - l;
        if (g_counting ? spread > g_best : spread >= g_best) continue;
        g_choice[depth] = opt;
        if (depth + 1 == M) {
            int64_t x = 2 * h - q, y = q - 2 * l, v = x > y ? x : y;
            if (v < g_best) {
                g_best = v;
                g_count = 1;
                g_ntight = 0;
                memcpy(g_arg, g_choice, sizeof(int) * M);
            } else if (v == g_best) {
                g_count++;
            }
            if (g_collect && v == g_best && g_ntight < MAX_TIGHT) {
                for (int i = 0; i < M; i++) g_tight[g_ntight][i] = (unsigned char)g_choice[i];
                g_ntight++;
            }
        } else {
            dfs(depth + 1, q, h, l);
        }
    }
}

/* Exact minimum over sign choices (in units of 1/D). If counting, *count is the number of sign
   choices that attain it. The minimiser goes to argmin. */
static int64_t ring_eval(int counting, int64_t *count, int *argmin) {
    g_counting = counting;
    g_best = pattern_value(hint);
    memcpy(g_arg, hint, sizeof(int) * M);
    g_count = 0;
    g_ntight = 0;
    dfs(0, 0, INT64_MIN / 4, INT64_MAX / 4);
    if (!counting) g_count = 1;
    if (count) *count = g_count;
    memcpy(argmin, g_arg, sizeof(int) * M);
    return g_best;
}

/* Ascent direction for the current state: every tight sign choice z has value max_k s (2 P_k - T)
   with an active (k, s); its gradient in (a, b) has entries in {-1, 0, 1}. A perceptron pass finds a
   direction that raises all of the active pieces at once when one exists (or its best attempt).
   dir[i] is the change of a_i, dir[M + i] that of b_i. Returns the number of tight choices used. */
static int ascent_direction(double *dir) {
    int arg[MAXM];
    g_collect = 1;
    ring_eval(1, NULL, arg);
    g_collect = 0;
    int n = g_ntight;
    static signed char grad[MAX_TIGHT][2 * MAXM];
    for (int t = 0; t < n; t++) {
        const unsigned char *c = g_tight[t];
        int64_t p = 0, T = 0, best = -1;
        int bk = 0, bs = 1;
        for (int i = 0; i < M; i++) T += c[i] ? -A[i] : B[i];
        for (int k = 0; k < M; k++) {
            p += c[k] ? -A[k] : B[k];
            int64_t x = 2 * p - T;
            if (x > best) { best = x; bk = k; bs = 1; }
            if (-x > best) { best = -x; bk = k; bs = -1; }
        }
        for (int i = 0; i < M; i++) {
            int side = i <= bk ? 1 : -1;
            grad[t][i] = (signed char)(c[i] ? -side * bs : 0);       /* d / d a_i */
            grad[t][M + i] = (signed char)(c[i] ? 0 : side * bs);    /* d / d b_i */
        }
    }
    for (int j = 0; j < 2 * M; j++) dir[j] = 0;
    for (int pass = 0; pass < 30; pass++) {
        int clean = 1;
        for (int t = 0; t < n; t++) {
            double dot = 0;
            for (int j = 0; j < 2 * M; j++) dot += grad[t][j] * dir[j];
            if (dot <= 0) {
                clean = 0;
                for (int j = 0; j < 2 * M; j++) dir[j] += grad[t][j];
            }
        }
        if (clean) break;
    }
    return n;
}

/* ---------------- helpers ---------------- */
static double cpu_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static int64_t gcd64(int64_t a, int64_t b) {
    while (b) { int64_t t = a % b; a = b; b = t; }
    return a;
}

static void write_fraction(FILE *f, int64_t num, int64_t den) {
    if (num == 0) { fprintf(f, "\"0\""); return; }
    int64_t g = gcd64(num, den);
    num /= g; den /= g;
    if (den == 1) fprintf(f, "\"%lld\"", (long long)num);
    else fprintf(f, "\"%lld/%lld\"", (long long)num, (long long)den);
}

/* a random feasible move of one coordinate by 1..step grid units; 0 if it would leave the simplex */
static int coordinate_move(int64_t D, int step, int *idx) {
    int i = rint_below(M), which = rint_below(2);
    int64_t delta = 1 + rint_below(step);
    if (rint_below(2)) delta = -delta;
    int64_t *x = which ? &B[i] : &A[i];
    int64_t nx = *x + delta;
    *idx = i;
    if (nx < 0 || nx + (which ? A[i] : B[i]) > D) return 0;
    *x = nx;
    return 1;
}

int main(int argc, char **argv) {
    const char *cfg_path = NULL, *inst_path = NULL, *out_path = NULL;
    long long seed = 0, max_iters = -1;
    double budget = -1;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--config")) cfg_path = argv[i + 1];
        else if (!strcmp(argv[i], "--instance")) inst_path = argv[i + 1];
        else if (!strcmp(argv[i], "--seed")) seed = atoll(argv[i + 1]);
        else if (!strcmp(argv[i], "--time")) budget = atof(argv[i + 1]);
        else if (!strcmp(argv[i], "--iters")) max_iters = atoll(argv[i + 1]);
        else if (!strcmp(argv[i], "--out")) out_path = argv[i + 1];
    }
    if (!inst_path || !out_path || (budget < 0 && max_iters < 0)) {
        fprintf(stderr, "usage: solver --config C --instance I --seed N (--time S | --iters N) --out O\n");
        return 2;
    }
    char *cfg = cfg_path ? read_file(cfg_path) : NULL;
    char *inst = read_file(inst_path);
    M = (int)json_num(inst, "m", 15);
    if (M < 1 || M > MAXM) { fprintf(stderr, "m must be between 1 and %d\n", MAXM); return 2; }

    const int tiebreak = json_num(cfg, "tiebreak_critical", 0) != 0;
    const int refine = json_num(cfg, "refine_grid", 0) != 0;
    const int grid_den = (int)json_num(cfg, "grid_den", 24);
    const int step = (int)json_num(cfg, "step_max", 2);
    const double t0 = json_num(cfg, "t0", 0.02);
    const long long cycle = (long long)json_num(cfg, "cycle", 5000);
    const int kick = (int)json_num(cfg, "kick", 3);
    const int refine_max = (int)json_num(cfg, "refine_max", 3);
    const double tie_accept = json_num(cfg, "tie_accept", 0.2);
    const int ascent = json_num(cfg, "ascent_moves", 0) != 0;
    const double ascent_prob = json_num(cfg, "ascent_prob", 0.05);

    rng_state = 0x5DEECE66DULL ^ ((uint64_t)seed * 0x9E3779B97F4A7C15ULL) ^ ((uint64_t)M << 48);
    int64_t D = grid_den < 1 ? 1 : grid_den;
    const int64_t D_cap = D << (refine_max < 0 ? 0 : refine_max > 20 ? 20 : refine_max);

    for (int i = 0; i < M; i++) {
        A[i] = rint_below((int)D + 1);
        B[i] = rint_below((int)(D - A[i]) + 1);
        hint[i] = 0;
    }
    int arg[MAXM];
    int64_t cnt, cur_cnt;
    int64_t cur = ring_eval(tiebreak, &cur_cnt, arg);
    memcpy(hint, arg, sizeof hint);

    int64_t bestA[MAXM], bestB[MAXM], best = cur, bestD = D;
    memcpy(bestA, A, sizeof A);
    memcpy(bestB, B, sizeof B);

    static double trace_t[MAX_TRACE], trace_s[MAX_TRACE];
    int ntrace = 0;
    const double start = cpu_seconds();
    trace_t[ntrace] = 0.0; trace_s[ntrace++] = (double)best / (double)bestD;

    long long it = 0, in_cycle = 0;
    int improved_in_cycle = 0;
    for (;;) {
        if (max_iters >= 0) { if (it >= max_iters) break; }
        else if ((it & 15) == 0 && cpu_seconds() - start >= budget) break;
        it++;

        double temp = t0 * (1.0 - (double)in_cycle / (double)(cycle < 1 ? 1 : cycle));
        int64_t oldA[MAXM], oldB[MAXM];
        memcpy(oldA, A, sizeof A);
        memcpy(oldB, B, sizeof B);
        int moved;
        if (ascent && runif() < ascent_prob) {
            double dir[2 * MAXM], mx = 0;
            ascent_direction(dir);
            for (int j = 0; j < 2 * M; j++) if (fabs(dir[j]) > mx) mx = fabs(dir[j]);
            moved = 0;
            if (mx > 0) {
                int len = 1 + rint_below(step < 1 ? 1 : step);
                for (int i = 0; i < M; i++) {
                    int64_t na = A[i] + llround(dir[i] / mx * len), nb = B[i] + llround(dir[M + i] / mx * len);
                    na = na < 0 ? 0 : na > D ? D : na;
                    nb = nb < 0 ? 0 : nb > D - na ? D - na : nb;
                    if (na != A[i] || nb != B[i]) moved = 1;
                    A[i] = na;
                    B[i] = nb;
                }
            }
        } else {
            int idx;
            moved = coordinate_move(D, step < 1 ? 1 : step, &idx);
        }
        if (moved) {
            int64_t val = ring_eval(tiebreak, &cnt, arg);
            int accept;
            if (val > cur) accept = 1;
            else if (val == cur) accept = !tiebreak || cnt <= cur_cnt || runif() < tie_accept;
            else accept = temp > 0 && runif() < exp(((double)(val - cur) / (double)D) / temp);
            if (accept) {
                cur = val;
                cur_cnt = cnt;
                memcpy(hint, arg, sizeof hint);
                if ((__int128)cur * bestD > (__int128)best * D) {
                    best = cur; bestD = D;
                    memcpy(bestA, A, sizeof A);
                    memcpy(bestB, B, sizeof B);
                    improved_in_cycle = 1;
                    if (ntrace < MAX_TRACE) {
                        trace_t[ntrace] = cpu_seconds() - start;
                        trace_s[ntrace++] = (double)best / (double)bestD;
                    }
                }
            } else {
                memcpy(A, oldA, sizeof A);
                memcpy(B, oldB, sizeof B);
            }
        }

        if (++in_cycle >= cycle) {   /* restart from the best state, possibly on a finer grid */
            in_cycle = 0;
            if (refine && !improved_in_cycle && D < D_cap) D *= 2;
            improved_in_cycle = 0;
            int64_t scale = D / bestD;
            for (int i = 0; i < M; i++) { A[i] = bestA[i] * scale; B[i] = bestB[i] * scale; }
            for (int k = 0; k < kick; k++) { int idx; coordinate_move(D, step < 1 ? 1 : step, &idx); }
            cur = ring_eval(tiebreak, &cur_cnt, arg);
            memcpy(hint, arg, sizeof hint);
        }
    }

    FILE *f = fopen(out_path, "w");
    if (!f) { perror(out_path); return 1; }
    fprintf(f, "{\"solution\": {\"pairs\": [");
    for (int i = 0; i < M; i++) {
        fprintf(f, i ? ", [" : "[");
        write_fraction(f, bestA[i], bestD);
        fprintf(f, ", ");
        write_fraction(f, bestB[i], bestD);
        fprintf(f, "]");
    }
    fprintf(f, "]}, \"stats\": {\"iters\": %lld, \"score\": %.17g, \"exact\": \"%lld/%lld\", \"grid\": %lld, "
               "\"cpu_seconds\": %.3f, \"trace\": [", it, (double)best / (double)bestD, (long long)best,
            (long long)bestD, (long long)D, cpu_seconds() - start);
    for (int i = 0; i < ntrace; i++) fprintf(f, "%s[%.6f, %.17g]", i ? ", " : "", trace_t[i], trace_s[i]);
    fprintf(f, "]}}\n");
    fclose(f);
    free(cfg);
    free(inst);
    return 0;
}
