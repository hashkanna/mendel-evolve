/*
 * Mendel seed solver for flat +-1 polynomials (problem pack: flatpoly).
 *
 *   ./solver --config CFG.json --instance INSTANCE.json --seed N (--time SECONDS | --iters N) --out OUT.json
 *
 * Objective. For coefficients s[e] in {+1, -1} (s[e] multiplies z^e) minimise max_{|z|=1} |g(z)| / sqrt(n + 1).
 *
 * Method: tabu search over single sign flips.
 *   - g is kept at M = grid_mult * n equally spaced points of the circle, P[m] = g(w^m), w = exp(2 pi i / M).
 *     Flipping s[e] changes P[m] by -2 s[e] w^(e m), so every one of the n moves is scored in O(M), with an
 *     early exit as soon as the move is worse than the best one seen in this step.
 *   - The surrogate is the grid maximum of |g|^2 (or, with `lp_surrogate`, the L_2q norm on the grid).
 *   - A step takes the best non-tabu move (a tabu move only if it beats the best surrogate of this restart);
 *     the flipped coefficient is tabu for tenure + U{0..tenure_rand} steps.
 *   - After stall_limit steps without a new best surrogate in this restart, the search restarts from a fresh
 *     random sequence (or, with `kick_restart`, from the best sequence with kick_flips random flips).
 *   - Whenever the grid maximum of the current sequence is below the best score, the true supremum is
 *     computed (golden-section search on T(t) = |g(e^{it})|^2 = a_0 + 2 sum a_k cos kt, from the exact
 *     autocorrelations, around every grid peak that can hide the maximum); only that number is used to
 *     decide what the best solution is.
 *
 * Budget. One iteration is one tabu step (n moves scored). --iters never looks at the clock, so it is
 * deterministic; --time is CPU seconds of this process (clock()).
 *
 * Genes. All of them live in Config, read once in load_config(). A switch that is off must not change
 * behaviour or consume random numbers from the main stream: guard new ideas with `if (cfg.<switch>)` and
 * give them a private stream (idea_rng) if they need randomness.
 *
 * Build: cc -O3 -o solver solver.c -lm
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef uint64_t u64;

#define MAXN 4096
#define MAX_TRACE 4096
#define RESYNC 4096      /* recompute P from scratch this often (removes floating-point drift) */

/* ------------------------------------------------------------------ genes */

typedef struct {
    int fekete_start;  /* idea: start (and restart) from cyclic shifts of the Legendre sequence */
    int kick_restart;  /* idea: restart by perturbing the best sequence instead of a random one */
    int lp_surrogate;  /* idea: steer the tabu walk by the L_2q norm on the grid instead of the max */
    int grid_mult;
    int tenure;
    int tenure_rand;
    int stall_limit;
    int kick_flips;
    int lp_q;
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
        if (*t != ':') { s += plen; continue; }
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

static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

static void load_config(const char *path) {
    char *text = path ? slurp(path) : NULL;
    if (path && !text) die("cannot read config");
    cfg.fekete_start = json_num(text, "fekete_start", 0) != 0;
    cfg.kick_restart = json_num(text, "kick_restart", 0) != 0;
    cfg.lp_surrogate = json_num(text, "lp_surrogate", 0) != 0;
    cfg.grid_mult = clampi((int)json_num(text, "grid_mult", 8), 2, 64);
    cfg.tenure = clampi((int)json_num(text, "tenure", 7), 0, MAXN);
    cfg.tenure_rand = clampi((int)json_num(text, "tenure_rand", 5), 0, MAXN);
    cfg.stall_limit = clampi((int)json_num(text, "stall_limit", 500), 1, 100000000);
    cfg.kick_flips = clampi((int)json_num(text, "kick_flips", 6), 1, MAXN);
    cfg.lp_q = clampi((int)json_num(text, "lp_q", 8), 1, 64);
    free(text);
}

/* ------------------------------------------------------------------ RNG: xoshiro256** seeded by splitmix64 */

typedef struct { u64 s[4]; } Rng;

static u64 splitmix64(u64 *x) {
    u64 z = (*x += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static void rng_seed(Rng *r, u64 seed) {
    for (int i = 0; i < 4; i++) r->s[i] = splitmix64(&seed);
}
static inline u64 rotl(u64 x, int k) { return (x << k) | (x >> (64 - k)); }
static u64 rng_next(Rng *r) {
    u64 *s = r->s;
    u64 out = rotl(s[1] * 5, 7) * 9, t = s[1] << 17;
    s[2] ^= s[0];
    s[3] ^= s[1];
    s[1] ^= s[2];
    s[0] ^= s[3];
    s[2] ^= t;
    s[3] = rotl(s[3], 45);
    return out;
}
static int rng_below(Rng *r, int bound) { /* uniform in 0..bound-1 (multiply-shift) */
    return (int)(((rng_next(r) >> 32) * (u64)bound) >> 32);
}
/* A private stream for one idea: the main stream is untouched when the idea is off. */
static void idea_rng(Rng *r, u64 seed, const char *name) {
    u64 h = 1469598103934665603ULL; /* FNV-1a of the idea name */
    for (const char *p = name; *p; p++) h = (h ^ (unsigned char)*p) * 1099511628211ULL;
    rng_seed(r, seed ^ h);
}

/* ------------------------------------------------------------------ state */

static int n, M;
static double *Wr, *Wi;       /* W[e * M + m] = w^(e m) */
static double *Pr, *Pi;       /* P[m] = g(w^m) for the current sequence */
static int s[MAXN];           /* current sequence: s[e] multiplies z^e */
static int best_s[MAXN];
static double best_sq = INFINITY;   /* true sup |g|^2 of best_s */
static long long tabu_until[MAXN];
static double trace_t[MAX_TRACE], trace_v[MAX_TRACE];
static int ntrace;
static long long n_iters, n_restarts, n_sup_calls;
static double cpu0;

static double cpu_now(void) { return (double)clock() / (double)CLOCKS_PER_SEC - cpu0; }

static void build_tables(void) {
    Wr = (double *)malloc(sizeof(double) * (size_t)n * (size_t)M);
    Wi = (double *)malloc(sizeof(double) * (size_t)n * (size_t)M);
    Pr = (double *)malloc(sizeof(double) * (size_t)M);
    Pi = (double *)malloc(sizeof(double) * (size_t)M);
    if (!Wr || !Wi || !Pr || !Pi) die("out of memory");
    for (int e = 0; e < n; e++)
        for (int m = 0; m < M; m++) {
            double a = 2.0 * M_PI * (double)(((long long)e * m) % M) / (double)M;
            Wr[(size_t)e * M + m] = cos(a);
            Wi[(size_t)e * M + m] = sin(a);
        }
}

static void sync_P(const int *seq) {
    for (int m = 0; m < M; m++) Pr[m] = Pi[m] = 0.0;
    for (int e = 0; e < n; e++) {
        const double *wr = Wr + (size_t)e * M, *wi = Wi + (size_t)e * M;
        double c = (double)seq[e];
        for (int m = 0; m < M; m++) { Pr[m] += c * wr[m]; Pi[m] += c * wi[m]; }
    }
}

static inline double ipow(double x, int q) {
    double r = 1.0;
    while (q) { if (q & 1) r *= x; x *= x; q >>= 1; }
    return r;
}

/* Surrogate of the sequence with s[e] flipped (e = -1: no flip). Stops early once it reaches `stop`. */
static double surrogate(int e, double stop) {
    double d = e >= 0 ? -2.0 * s[e] : 0.0;
    const double *wr = e >= 0 ? Wr + (size_t)e * M : Wr, *wi = e >= 0 ? Wi + (size_t)e * M : Wi;
    if (cfg.lp_surrogate) {
        double sum = 0.0, inv = 1.0 / n;
        for (int m = 0; m < M; m++) {
            double re = Pr[m] + d * wr[m], im = Pi[m] + d * wi[m];
            sum += ipow((re * re + im * im) * inv, cfg.lp_q);
            if (sum >= stop) return sum;
        }
        return sum;
    }
    double mx = 0.0;
    for (int m = 0; m < M; m++) {
        double re = Pr[m] + d * wr[m], im = Pi[m] + d * wi[m];
        double v = re * re + im * im;
        if (v > mx) { mx = v; if (mx >= stop) return mx; }
    }
    return mx;
}

static double grid_max_sq(void) {
    double mx = 0.0;
    for (int m = 0; m < M; m++) {
        double v = Pr[m] * Pr[m] + Pi[m] * Pi[m];
        if (v > mx) mx = v;
    }
    return mx;
}

static void apply_flip(int e) {
    double d = -2.0 * s[e];
    const double *wr = Wr + (size_t)e * M, *wi = Wi + (size_t)e * M;
    for (int m = 0; m < M; m++) { Pr[m] += d * wr[m]; Pi[m] += d * wi[m]; }
    s[e] = -s[e];
}

static long long acor[MAXN];   /* aperiodic autocorrelations of the sequence in true_sup_sq */

/* T(t) = |g(e^{it})|^2 = a_0 + 2 sum_k a_k cos(k t), by Clenshaw's recurrence (one cosine call). */
static double T_at(double t) {
    double x2 = 2.0 * cos(t), b1 = 0.0, b2 = 0.0;
    for (int k = n - 1; k >= 1; k--) {
        double b0 = 2.0 * (double)acor[k] + x2 * b1 - b2;
        b2 = b1;
        b1 = b0;
    }
    return (double)acor[0] + 0.5 * x2 * b1 - b2;
}

/* True sup over the circle of |g|^2 for the current sequence (P must be in sync with s).
 * T has degree d = n - 1, so |T''| <= d^2 max T (Bernstein) and the grid point nearest to the maximiser
 * has T >= max T (1 - d^2 h^2 / 8). Every grid peak at least that high is refined by golden-section search
 * on the two grid steps around it. */
static double true_sup_sq(void) {
    n_sup_calls++;
    for (int k = 0; k < n; k++) {
        long long acc = 0;
        for (int j = 0; j + k < n; j++) acc += s[j] * s[j + k];
        acor[k] = acc;
    }
    const double h = 2.0 * M_PI / M, g = 0.5 * (sqrt(5.0) - 1.0);
    double gmax = grid_max_sq(), d = n - 1.0;
    double floor_v = gmax * (1.0 - d * d * h * h / 8.0) * (1.0 - 1e-9), best = gmax;
    for (int m = 0; m < M; m++) {
        double v = Pr[m] * Pr[m] + Pi[m] * Pi[m];
        if (v < floor_v) continue;
        int l = (m + M - 1) % M, r = (m + 1) % M;
        if (v < Pr[l] * Pr[l] + Pi[l] * Pi[l] || v < Pr[r] * Pr[r] + Pi[r] * Pi[r]) continue;
        double lo = h * (m - 1), hi = h * (m + 1);
        double x1 = hi - g * (hi - lo), x2 = lo + g * (hi - lo), f1 = T_at(x1), f2 = T_at(x2);
        for (int it = 0; it < 60; it++) {
            if (f1 > f2) { hi = x2; x2 = x1; f2 = f1; x1 = hi - g * (hi - lo); f1 = T_at(x1); }
            else { lo = x1; x1 = x2; f1 = f2; x2 = lo + g * (hi - lo); f2 = T_at(x2); }
        }
        double v1 = f1 > f2 ? f1 : f2;
        if (v1 > best) best = v1;
    }
    return best;
}

static void offer_best(void) {
    double v = true_sup_sq();
    if (v < best_sq) {
        best_sq = v;
        memcpy(best_s, s, sizeof(int) * (size_t)n);
        if (ntrace < MAX_TRACE) {
            trace_t[ntrace] = cpu_now();
            trace_v[ntrace] = sqrt(v / (n + 1.0));
            ntrace++;
        }
    }
}

/* ------------------------------------------------------------------ ideas */

static int legendre(long long a, long long p) { /* Euler's criterion; 0 -> +1 */
    a %= p;
    if (a < 0) a += p;
    if (a == 0) return 1;
    long long r = 1, b = a, x = (p - 1) / 2;
    while (x) { if (x & 1) r = r * b % p; b = b * b % p; x >>= 1; }
    return r == 1 ? 1 : -1;
}

static long long fekete_prime(void) { /* smallest prime >= n + 1 (and >= 3) */
    for (long long p = n + 1 < 3 ? 3 : n + 1;; p++) {
        int prime = 1;
        for (long long q = 2; q * q <= p; q++) if (p % q == 0) { prime = 0; break; }
        if (prime) return p;
    }
}

static void fekete_seq(int *seq, long long p, long long r) {
    for (int e = 0; e < n; e++) seq[e] = legendre(e + 1 + r, p);
}

/* The rotation of the Legendre sequence with the smallest grid maximum (ties: the smaller shift). */
static void fekete_best(int *seq) {
    long long p = fekete_prime(), best_r = 0;
    double best_v = INFINITY;
    for (long long r = 0; r < p; r++) {
        fekete_seq(s, p, r);
        sync_P(s);
        double v = grid_max_sq();
        if (v < best_v) { best_v = v; best_r = r; }
    }
    fekete_seq(seq, p, best_r);
}

/* ------------------------------------------------------------------ driver */

static void write_output(const char *out_path) {
    char tmp[4096];
    snprintf(tmp, sizeof tmp, "%s.tmp", out_path);
    FILE *f = fopen(tmp, "w");
    if (!f) die("cannot write output");
    fprintf(f, "{\"solution\": [");
    for (int i = 0; i < n; i++) fprintf(f, "%s%d", i ? ", " : "", best_s[n - 1 - i]); /* highest power first */
    fprintf(f, "], \"stats\": {\"iters\": %lld, \"restarts\": %lld, \"sup_calls\": %lld, \"grid\": %d, "
               "\"score_internal\": %.17g, \"trace\": [", n_iters, n_restarts, n_sup_calls, M,
            sqrt(best_sq / (n + 1.0)));
    for (int i = 0; i < ntrace; i++) fprintf(f, "%s[%.3f, %.17g]", i ? ", " : "", trace_t[i], trace_v[i]);
    fprintf(f, "]}}\n");
    fclose(f);
    if (rename(tmp, out_path) != 0) die("cannot rename output");
}

int main(int argc, char **argv) {
    const char *cfg_path = NULL, *inst_path = NULL, *out_path = NULL;
    u64 seed = 1;
    double time_budget = -1;
    long long iter_budget = -1;
    cpu0 = (double)clock() / (double)CLOCKS_PER_SEC;
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
    if (n < 1 || n > MAXN) die("instance n must be in 1..4096");
    M = cfg.grid_mult * n < 64 ? 64 : cfg.grid_mult * n;
    /* keep a little of the budget back for writing the output */
    double limit = time_budget >= 0 ? time_budget - fmin(0.5, 0.03 * time_budget) : 0;

    Rng rng, kick_rng, fek_rng;
    rng_seed(&rng, seed);
    build_tables();

    long long fek_p = 0;
    if (cfg.fekete_start) { idea_rng(&fek_rng, seed, "fekete_start"); fek_p = fekete_prime(); }
    if (cfg.kick_restart) idea_rng(&kick_rng, seed, "kick_restart");

    /* first start: random signs from the main stream (drawn even when an idea replaces them) */
    for (int e = 0; e < n; e++) s[e] = (rng_next(&rng) >> 63) ? 1 : -1;
    if (cfg.fekete_start) fekete_best(s);
    sync_P(s);
    offer_best();   /* from here on best_s is always a valid solution */

    double run_best = surrogate(-1, INFINITY);
    long long stall = 0, since_sync = 0;
    int tmax = n - 1;  /* at most n - 1 moves are tabu, so a non-tabu move always exists */
    for (;;) {
        if (iter_budget >= 0) { if (n_iters >= iter_budget) break; }
        else if (cpu_now() >= limit) break;
        n_iters++;

        if (n > 1) {
            int pick = -1;
            double pick_v = INFINITY;
            for (int e = 0; e < n; e++) {
                int is_tabu = tabu_until[e] > n_iters;
                double stop = is_tabu ? fmin(pick_v, run_best) : pick_v;
                double v = surrogate(e, stop);
                if (v < stop) { pick = e; pick_v = v; }
            }
            if (pick < 0) pick = rng_below(&rng, n); /* cannot happen; kept for safety */
            apply_flip(pick);
            int ten = cfg.tenure + (cfg.tenure_rand ? rng_below(&rng, cfg.tenure_rand + 1) : 0);
            tabu_until[pick] = n_iters + 1 + (ten < tmax ? ten : tmax);
            if (++since_sync >= RESYNC) { sync_P(s); since_sync = 0; }
            if (grid_max_sq() < best_sq) offer_best();
            if (pick_v < run_best) { run_best = pick_v; stall = 0; }
            else stall++;
        } else {
            stall = cfg.stall_limit; /* n = 1: nothing to search */
        }

        if (stall >= cfg.stall_limit) {
            n_restarts++;
            if (cfg.kick_restart) {
                memcpy(s, best_s, sizeof(int) * (size_t)n);
                int k = cfg.kick_flips < n ? cfg.kick_flips : n;
                for (int i = 0; i < k; i++) { int e = rng_below(&kick_rng, n); s[e] = -s[e]; }
            } else if (cfg.fekete_start) {
                fekete_seq(s, fek_p, rng_below(&fek_rng, (int)fek_p));
            } else {
                for (int e = 0; e < n; e++) s[e] = (rng_next(&rng) >> 63) ? 1 : -1;
            }
            for (int e = 0; e < n; e++) tabu_until[e] = 0;
            sync_P(s);
            since_sync = 0;
            if (grid_max_sq() < best_sq) offer_best();
            run_best = surrogate(-1, INFINITY);
            stall = 0;
        }
    }
    write_output(out_path);
    return 0;
}
