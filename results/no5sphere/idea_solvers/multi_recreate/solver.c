/*
 * Mendel seed solver for "no 5 on a sphere" (problem pack: no5sphere).
 *
 *   ./solver --config CFG.json --instance INSTANCE.json --seed N (--time SECONDS | --iters N) --out OUT.json
 *
 * Method: ruin-and-recreate on a set that is valid at all times, in exact int64 arithmetic.
 *
 * Geometry. Five points are forbidden iff det[x, y, z, x^2+y^2+z^2, 1] = 0. Translating one of them to the
 * origin, that is: the four lifted vectors (dx, dy, dz, dx^2+dy^2+dz^2) are linearly dependent. For three of
 * them the 4D cross product N is the normal of "their" sphere or plane through the origin, and a further
 * point d is on it iff N . lift(d) = 0. With |d| <= n-1 <= 63 every value here is below 72 * 63^5 < 2^37.
 *
 * Data structure.
 *   cnt[g]   for every grid point g: the number of 4-subsets of the registered set whose sphere/plane holds g.
 *            A non-member g can be added iff cnt[g] == 0.
 *   recs[]   one record (g, 4 members) per such incidence, so that removing a member is one pass over recs
 *            instead of a geometric recomputation.
 *   Registering a new member q ("commit_add") enumerates, for each triple of members, the lattice points on
 *   the sphere through q and the triple: the equation separates as fx[x] + fy[y] + fz[z] = 0, solved by
 *   hashing fz and looking up -(fx[x] + fy[y]) for all n^2 pairs.
 *   The recreate step is *tentative*: it only tracks the currently free points (a short list), testing them
 *   against the spheres through each newly placed point. The expensive enumeration is paid only for points
 *   that survive into an accepted set.
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

typedef int64_t i64;
typedef uint64_t u64;

#define MAXN 64
#define MAXK (4 * MAXN + 8) /* a valid set has at most 4n points */

/* ------------------------------------------------------------------ genes */

typedef struct {
    /* idea switches (default off) */
    int centrosymmetric; /* build the set from antipodal pairs about the cube centre */
    int lookahead;       /* recreate picks the least-blocking of lookahead_m sampled free points */
    int guided_ruin;     /* ruin frees a point blocked by a single sphere and inserts it first */
    /* numeric alleles */
    int ruin_max;             /* ruin size is uniform in 1..ruin_max (pairs when centrosymmetric) */
    double accept_worse_prob; /* chance to accept a set one unit smaller than the current one */
    int patience;             /* iterations without a new best before a kick */
    double kick_fraction;     /* fraction of the set removed by a kick */
    int lookahead_m;          /* samples per pick when lookahead is on */
    /* gene multi_recreate */
    int multi_recreate;   /* refill the same ruin several times and keep the best refill */
    int multi_recreate_m; /* refills per ruin when multi_recreate is on */
} Config;

static Config cfg;

static void die(const char *msg) {
    fprintf(stderr, "solver: %s\n", msg);
    exit(2);
}

/* ------------------------------------------------------------------ flat JSON reader */

#define FLAT_MAX 256
typedef struct {
    char key[64];
    int type; /* 0 number, 1 bool, 2 string, 3 other */
    double num;
    char str[64];
} FlatEntry;
typedef struct {
    FlatEntry e[FLAT_MAX];
    int n;
} Flat;

static char *read_file(const char *path) {
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

static const char *skip_ws(const char *s) {
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
    return s;
}

static const char *read_string(const char *s, char *out, size_t cap) { /* s points at the opening quote */
    size_t len = 0;
    s++;
    while (*s && *s != '"') {
        if (*s == '\\' && s[1]) s++;
        if (len + 1 < cap) out[len++] = *s;
        s++;
    }
    out[len] = 0;
    return *s ? s + 1 : s;
}

/* Parses {"key": number | true | false | "string", ...}. Nested values are skipped. */
static int flat_parse(const char *path, Flat *f) {
    char *buf = read_file(path);
    f->n = 0;
    if (!buf) return -1;
    const char *s = skip_ws(buf);
    if (*s == '{') s++;
    while (*s) {
        s = skip_ws(s);
        if (*s == ',') { s++; continue; }
        if (*s != '"') break;
        FlatEntry *e = &f->e[f->n < FLAT_MAX ? f->n : FLAT_MAX - 1];
        s = read_string(s, e->key, sizeof e->key);
        s = skip_ws(s);
        if (*s == ':') s++;
        s = skip_ws(s);
        e->num = 0;
        e->str[0] = 0;
        if (*s == '"') {
            e->type = 2;
            s = read_string(s, e->str, sizeof e->str);
        } else if (!strncmp(s, "true", 4)) {
            e->type = 1; e->num = 1; s += 4;
        } else if (!strncmp(s, "false", 5)) {
            e->type = 1; e->num = 0; s += 5;
        } else if (*s == '{' || *s == '[') {
            int depth = 0;
            e->type = 3;
            do {
                if (*s == '{' || *s == '[') depth++;
                if (*s == '}' || *s == ']') depth--;
                s++;
            } while (*s && depth > 0);
        } else if (!strncmp(s, "null", 4)) {
            e->type = 3; s += 4;
        } else {
            char *end;
            e->type = 0;
            e->num = strtod(s, &end);
            if (end == s) break;
            s = end;
        }
        if (f->n < FLAT_MAX) f->n++;
    }
    free(buf);
    return 0;
}

static const FlatEntry *flat_get(const Flat *f, const char *key) {
    for (int i = 0; i < f->n; i++)
        if (!strcmp(f->e[i].key, key)) return &f->e[i];
    return NULL;
}
static double flat_num(const Flat *f, const char *key, double dflt) {
    const FlatEntry *e = flat_get(f, key);
    return (e && e->type <= 1) ? e->num : dflt;
}
static int flat_bool(const Flat *f, const char *key, int dflt) {
    const FlatEntry *e = flat_get(f, key);
    return (e && e->type <= 1) ? (e->num != 0) : dflt;
}

static void load_config(const char *path) {
    Flat f;
    f.n = 0;
    if (path && flat_parse(path, &f) != 0) die("cannot read config");
    cfg.centrosymmetric = flat_bool(&f, "centrosymmetric", 0);
    cfg.lookahead = flat_bool(&f, "lookahead", 0);
    cfg.guided_ruin = flat_bool(&f, "guided_ruin", 0);
    cfg.ruin_max = (int)flat_num(&f, "ruin_max", 3);
    cfg.accept_worse_prob = flat_num(&f, "accept_worse_prob", 0.02);
    cfg.patience = (int)flat_num(&f, "patience", 3000);
    cfg.kick_fraction = flat_num(&f, "kick_fraction", 0.25);
    cfg.lookahead_m = (int)flat_num(&f, "lookahead_m", 3);
    cfg.multi_recreate = flat_bool(&f, "multi_recreate", 0);
    cfg.multi_recreate_m = (int)flat_num(&f, "multi_recreate_m", 3);
    if (cfg.ruin_max < 1) cfg.ruin_max = 1;
    if (cfg.patience < 1) cfg.patience = 1;
    if (cfg.lookahead_m < 1) cfg.lookahead_m = 1;
    if (cfg.kick_fraction < 0) cfg.kick_fraction = 0;
    if (cfg.kick_fraction > 1) cfg.kick_fraction = 1;
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
static double rng_unit(void) { return (double)(rng_next() >> 11) * (1.0 / 9007199254740992.0); }

/* ------------------------------------------------------------------ state */

typedef struct {
    int32_t p;    /* grid point lying on the sphere/plane of ... */
    int32_t m[4]; /* ... these four members */
} Rec;

static int n, G;           /* grid side, number of grid points */
static int *gx, *gy, *gz;  /* coordinates of grid id g = (x*n + y)*n + z */
static int32_t *cnt;       /* incidence count per grid point */
static uint8_t *is_mem;    /* registered member flag */
static uint8_t *flag_rm;   /* scratch: member being removed in this iteration */
static uint8_t *flag_gone; /* scratch: removed member that did not come back */
static int S[MAXK], k;     /* registered members */
static Rec *recs, *saved;
static size_t nrec, caprec, nsaved, capsaved;
static int internal_error; /* set if an invariant is ever violated; output is re-verified regardless */

/* tentative (recreate) state */
static int T[MAXK], nT;       /* tentative set */
static int *F, *posF;         /* free points: F[0..nsel) selectable, F[nsel..nF) parked; posF = index+1 */
static int nF, nsel;
static i64 *ux, *uy, *uz, *uw; /* scratch for tent_eval */
static int *uid, *kills, *kills2;

static u64 n_iters, n_commit_scans, n_tent_evals;

static void rec_push(Rec **arr, size_t *cnt_, size_t *cap, Rec r) {
    if (*cnt_ == *cap) {
        *cap = *cap ? *cap * 2 : 4096;
        *arr = (Rec *)realloc(*arr, *cap * sizeof(Rec));
        if (!*arr) die("out of memory");
    }
    (*arr)[(*cnt_)++] = r;
}

static void F_push(int g) {
    F[nF] = g;
    posF[g] = ++nF;
    nsel = nF;
}
static void F_remove(int g) {
    int i = posF[g] - 1;
    if (i < 0) return;
    if (i < nsel) { /* fill the hole with the last selectable entry */
        nsel--;
        if (i != nsel) {
            int last = F[nsel];
            F[i] = last;
            posF[last] = i + 1;
        }
        i = nsel;
    }
    nF--;
    if (i != nF) { /* then fill that hole with the last entry overall */
        int lastg = F[nF];
        F[i] = lastg;
        posF[lastg] = i + 1;
    }
    posF[g] = 0;
}
static void F_park(int g) { /* keep g as a free point but never select it again */
    int i = posF[g] - 1;
    if (i < 0 || i >= nsel) return;
    int last = F[nsel - 1];
    F[i] = last;
    posF[last] = i + 1;
    F[nsel - 1] = g;
    posF[g] = nsel;
    nsel--;
}
static void F_clear(void) {
    for (int i = 0; i < nF; i++) posF[F[i]] = 0;
    nF = nsel = 0;
}
static int F_selectable(int g) { return posF[g] && posF[g] - 1 < nsel; }

/* 4D cross product of a, b (through their 2x2 minors m) and c */
#define MINORS(a, b)                                                                       \
    const i64 m01 = vx[a] * vy[b] - vy[a] * vx[b], m02 = vx[a] * vz[b] - vz[a] * vx[b],    \
              m03 = vx[a] * vw[b] - vw[a] * vx[b], m12 = vy[a] * vz[b] - vz[a] * vy[b],    \
              m13 = vy[a] * vw[b] - vw[a] * vy[b], m23 = vz[a] * vw[b] - vw[a] * vz[b]
#define NORMAL(c)                                                         \
    const i64 N0 = m12 * vw[c] - m13 * vz[c] + m23 * vy[c],               \
              N1 = -(m02 * vw[c] - m03 * vz[c] + m23 * vx[c]),            \
              N2 = m01 * vw[c] - m03 * vy[c] + m13 * vx[c],               \
              N3 = -(m01 * vz[c] - m02 * vy[c] + m12 * vx[c])

/*
 * Which free points would adding p to the tentative set T block? Writes their ids to out[] and returns
 * how many, or -1 if p forms a concyclic/collinear 4-subset with T (then p cannot be added at all).
 * Does not change any state.
 */
static int tent_eval(int p, int *out) {
    i64 vx[MAXK], vy[MAXK], vz[MAXK], vw[MAXK];
    const int px = gx[p], py = gy[p], pz = gz[p];
    n_tent_evals++;
    for (int i = 0; i < nT; i++) {
        i64 dx = gx[T[i]] - px, dy = gy[T[i]] - py, dz = gz[T[i]] - pz;
        vx[i] = dx; vy[i] = dy; vz[i] = dz; vw[i] = dx * dx + dy * dy + dz * dz;
    }
    int nu = 0, nk = 0;
    for (int i = 0; i < nF; i++) {
        int g = F[i];
        if (g == p) continue;
        i64 dx = gx[g] - px, dy = gy[g] - py, dz = gz[g] - pz;
        ux[nu] = dx; uy[nu] = dy; uz[nu] = dz; uw[nu] = dx * dx + dy * dy + dz * dz;
        uid[nu++] = g;
    }
    for (int a = 0; a < nT; a++)
        for (int b = a + 1; b < nT; b++) {
            MINORS(a, b);
            for (int c = b + 1; c < nT; c++) {
                NORMAL(c);
                if ((N0 | N1 | N2 | N3) == 0) return -1;
                for (int j = 0; j < nu;) {
                    if (N0 * ux[j] + N1 * uy[j] + N2 * uz[j] + N3 * uw[j] == 0) {
                        out[nk++] = uid[j];
                        nu--;
                        ux[j] = ux[nu]; uy[j] = uy[nu]; uz[j] = uz[nu]; uw[j] = uw[nu]; uid[j] = uid[nu];
                    } else {
                        j++;
                    }
                }
            }
            /* once nothing is left to block, only the degenerate test remains; it cannot fire for nT >= 4
               because p was free with respect to every 4-subset of T */
            if (nu == 0 && nT >= 4) return nk;
        }
    return nk;
}

static void tent_apply(int p, const int *list, int nk) {
    F_remove(p);
    for (int i = 0; i < nk; i++) F_remove(list[i]);
    T[nT++] = p;
}

/*
 * Register q as a member: enumerate the grid points on the sphere/plane through q and every triple of
 * members, record the incidences and raise their counters.
 */
static void commit_add(int q) {
    i64 vx[MAXK], vy[MAXK], vz[MAXK], vw[MAXK];
    i64 dx1[MAXN], dx2[MAXN], dy1[MAXN], dy2[MAXN], dz1[MAXN], dz2[MAXN];
    i64 fx[MAXN], fy[MAXN], fz[MAXN];
    uint8_t tab[256];
    const int qx = gx[q], qy = gy[q], qz = gz[q];
    n_commit_scans++;
    for (int i = 0; i < k; i++) {
        i64 dx = gx[S[i]] - qx, dy = gy[S[i]] - qy, dz = gz[S[i]] - qz;
        vx[i] = dx; vy[i] = dy; vz[i] = dz; vw[i] = dx * dx + dy * dy + dz * dz;
    }
    for (int t = 0; t < n; t++) {
        dx1[t] = t - qx; dx2[t] = dx1[t] * dx1[t];
        dy1[t] = t - qy; dy2[t] = dy1[t] * dy1[t];
        dz1[t] = t - qz; dz2[t] = dz1[t] * dz1[t];
    }
    for (int a = 0; a < k; a++)
        for (int b = a + 1; b < k; b++) {
            MINORS(a, b);
            for (int c = b + 1; c < k; c++) {
                NORMAL(c);
                /* point q + d is on the surface iff N0 dx + N1 dy + N2 dz + N3 |d|^2 = fx + fy + fz = 0 */
                memset(tab, 0, sizeof tab);
                for (int t = 0; t < n; t++) {
                    fx[t] = N0 * dx1[t] + N3 * dx2[t];
                    fy[t] = N1 * dy1[t] + N3 * dy2[t];
                    fz[t] = N2 * dz1[t] + N3 * dz2[t];
                    unsigned h = (unsigned)(((u64)fz[t] * 0x9E3779B97F4A7C15ULL) >> 56);
                    tab[h] = tab[h] ? 255 : (uint8_t)(t + 1);
                }
                const int sa = S[a], sb = S[b], sc = S[c];
                for (int x = 0; x < n; x++) {
                    const i64 fxx = fx[x];
                    for (int y = 0; y < n; y++) {
                        const i64 t = -(fxx + fy[y]);
                        const unsigned s = tab[(unsigned)(((u64)t * 0x9E3779B97F4A7C15ULL) >> 56)];
                        if (!s) continue;
                        int z0 = 0, z1 = n;
                        if (s != 255) { z0 = (int)s - 1; z1 = z0 + 1; }
                        for (int z = z0; z < z1; z++) {
                            if (fz[z] != t) continue;
                            const int g = (x * n + y) * n + z;
                            if (g == q || g == sa || g == sb || g == sc) continue;
                            if (is_mem[g]) { internal_error = 1; continue; }
                            Rec r = {g, {q, sa, sb, sc}};
                            rec_push(&recs, &nrec, &caprec, r);
                            cnt[g]++;
                        }
                    }
                }
            }
        }
    S[k++] = q;
    is_mem[q] = 1;
}

/* Unregister the members flagged in flag_rm: their records move to saved[], counters drop. */
static void remove_flagged(void) {
    size_t w = 0;
    nsaved = 0;
    for (size_t i = 0; i < nrec; i++) {
        const Rec *e = &recs[i];
        if (flag_rm[e->m[0]] | flag_rm[e->m[1]] | flag_rm[e->m[2]] | flag_rm[e->m[3]]) {
            rec_push(&saved, &nsaved, &capsaved, *e);
            cnt[e->p]--;
        } else {
            recs[w++] = *e;
        }
    }
    nrec = w;
    int kk = 0;
    for (int i = 0; i < k; i++) {
        if (flag_rm[S[i]]) is_mem[S[i]] = 0;
        else S[kk++] = S[i];
    }
    k = kk;
}

/* Exact brute-force validity of a point list: every 5-subset. Returns 1 when valid. */
static int set_is_valid(const int *ids, int m) {
    i64 vx[MAXK], vy[MAXK], vz[MAXK], vw[MAXK];
    for (int e = 4; e < m; e++) {
        for (int i = 0; i < e; i++) {
            i64 dx = gx[ids[i]] - gx[ids[e]], dy = gy[ids[i]] - gy[ids[e]], dz = gz[ids[i]] - gz[ids[e]];
            vx[i] = dx; vy[i] = dy; vz[i] = dz; vw[i] = dx * dx + dy * dy + dz * dz;
        }
        for (int a = 0; a < e; a++)
            for (int b = a + 1; b < e; b++) {
                MINORS(a, b);
                for (int c = b + 1; c < e; c++) {
                    NORMAL(c);
                    for (int d = c + 1; d < e; d++)
                        if (N0 * vx[d] + N1 * vy[d] + N2 * vz[d] + N3 * vw[d] == 0) return 0;
                }
            }
    }
    return 1;
}

/* ------------------------------------------------------------------ search */

static int best[MAXK], nbest;
static double trace_t[4096];
static int trace_v[4096], ntrace;

static double cpu_now(void) { return (double)clock() / (double)CLOCKS_PER_SEC; }

static void note_best(void) { /* T (possibly with completion extras) is a new best */
    nbest = nT;
    memcpy(best, T, (size_t)nT * sizeof(int));
    if (ntrace < 4096) {
        trace_t[ntrace] = cpu_now();
        trace_v[ntrace++] = nbest;
    }
}

/* Fill T from the free list until nothing selectable is left. `forced` (or -1) is tried first. */
static void recreate(int forced, int symmetric) {
    while (nsel > 0) {
        int p;
        if (forced >= 0 && F_selectable(forced)) {
            p = forced;
        } else if (cfg.lookahead) {
            int best_nk = INT_MAX;
            p = -1;
            for (int t = 0; t < cfg.lookahead_m; t++) {
                int cand = F[rng_below(nsel)];
                int nk = tent_eval(cand, kills2);
                if (nk >= 0 && nk < best_nk) { best_nk = nk; p = cand; }
            }
            if (p < 0) p = F[rng_below(nsel)];
        } else {
            p = F[rng_below(nsel)];
        }
        forced = -1;
        if (symmetric) {
            const int q = G - 1 - p; /* antipode about the cube centre */
            if (q != p && !F_selectable(q)) { F_park(p); continue; }
            int nk = tent_eval(p, kills);
            if (nk < 0) { F_remove(p); continue; }
            int partner_blocked = 0;
            if (q != p)
                for (int i = 0; i < nk; i++)
                    if (kills[i] == q) partner_blocked = 1;
            if (partner_blocked) { F_park(p); F_park(q); continue; }
            tent_apply(p, kills, nk);
            if (q != p) {
                nk = tent_eval(q, kills);
                if (nk < 0) { nT--; F_remove(q); continue; } /* p alone would break the symmetry: drop it */
                tent_apply(q, kills, nk);
            }
        } else {
            int nk = tent_eval(p, kills);
            if (nk < 0) { F_remove(p); continue; }
            tent_apply(p, kills, nk);
        }
    }
}

/* gene multi_recreate: number of placed points T[from..nT) that are not members being put back */
#define MR_CAP 256 /* buffer bound: ruins that free more points than this are refilled once */
static int mr_novel(int from) {
    int c = 0;
    for (int i = from; i < nT; i++) c += !flag_rm[T[i]];
    return c;
}

/*
 * One ruin-and-recreate step. R[0..r) are the members to remove (already expanded to pairs when
 * centrosymmetric). Returns 1 if the new set was accepted.
 */
static int step(const int *R, int r, int forced, int force_accept) {
    const int kb = k;
    for (int i = 0; i < r; i++) flag_rm[R[i]] = 1;
    remove_flagged();
    F_clear();
    for (int g = 0; g < G; g++)
        if (cnt[g] == 0 && !is_mem[g]) F_push(g);
    int accepted = 0;
    if (nF > r || force_accept) { /* otherwise only the removed points are free: nothing can change */
        nT = k;
        memcpy(T, S, (size_t)k * sizeof(int));
        /* gene multi_recreate: the ruin (a pass over all records and the grid) is paid once, so remember
           the free list and refill the same hole several times */
        int mr_F0[MR_CAP], mr_nF0 = 0;
        if (cfg.multi_recreate && !force_accept && nF <= MR_CAP) {
            mr_nF0 = nF;
            memcpy(mr_F0, F, (size_t)nF * sizeof(int));
        }
        recreate(forced, cfg.centrosymmetric);
        if (mr_nF0 > 0) {
            /* keep the largest refill; among equals the one that brings in the most new points. Stop as
               soon as a refill beats the set before the ruin. */
            int bT[MAXK], bF[MR_CAP], nbT = nT, nbF = nF, bnov = mr_novel(k), last_is_best = 1;
            memcpy(bT, T + k, (size_t)(nT - k) * sizeof(int));
            memcpy(bF, F, (size_t)nF * sizeof(int)); /* parked points (centrosymmetric only) */
            for (int t = 1; t < cfg.multi_recreate_m && nbT <= kb; t++) {
                F_clear();
                for (int i = 0; i < mr_nF0; i++) F_push(mr_F0[i]);
                nT = k;
                recreate(forced, cfg.centrosymmetric);
                const int nov = mr_novel(k);
                last_is_best = nT > nbT || (nT == nbT && nov > bnov);
                if (last_is_best) {
                    nbT = nT; nbF = nF; bnov = nov;
                    memcpy(bT, T + k, (size_t)(nT - k) * sizeof(int));
                    memcpy(bF, F, (size_t)nF * sizeof(int));
                }
            }
            if (!last_is_best) { /* put the best refill and its parked points back */
                nT = nbT;
                memcpy(T + k, bT, (size_t)(nT - k) * sizeof(int));
                F_clear();
                for (int i = 0; i < nbF; i++) F_push(bF[i]);
                nsel = 0;
            }
        }
        const int knew = nT;
        if (cfg.centrosymmetric && nF > 0 && nT + nF > nbest) {
            /* completion: the parked points are free one by one; add what fits, for the record only */
            nsel = nF;
            recreate(-1, 0);
            if (nT > nbest) note_best();
            nT = knew;
        } else if (nT > nbest) {
            note_best();
        }
        const int unit = cfg.centrosymmetric ? 2 : 1;
        accepted = force_accept || knew >= kb;
        if (!accepted && knew >= kb - unit && cfg.accept_worse_prob > 0 && rng_unit() < cfg.accept_worse_prob)
            accepted = 1;
        if (accepted) {
            /* T = kept members, then the points placed by recreate */
            for (int i = 0; i < r; i++) flag_gone[R[i]] = 1;
            for (int i = k; i < knew; i++) flag_gone[T[i]] = 0;
            for (size_t i = 0; i < nsaved; i++) {
                const Rec *e = &saved[i];
                if (flag_gone[e->m[0]] | flag_gone[e->m[1]] | flag_gone[e->m[2]] | flag_gone[e->m[3]]) continue;
                rec_push(&recs, &nrec, &caprec, *e);
                cnt[e->p]++;
            }
            const int kept = k;
            for (int i = kept; i < knew; i++) /* returning members: their records were just restored */
                if (flag_rm[T[i]]) { S[k++] = T[i]; is_mem[T[i]] = 1; }
            for (int i = kept; i < knew; i++) /* genuinely new members: enumerate their spheres */
                if (!flag_rm[T[i]]) commit_add(T[i]);
            for (int i = 0; i < r; i++) flag_gone[R[i]] = 0;
        }
    }
    if (!accepted) {
        for (size_t i = 0; i < nsaved; i++) {
            rec_push(&recs, &nrec, &caprec, saved[i]);
            cnt[saved[i].p]++;
        }
        for (int i = 0; i < r; i++) { S[k++] = R[i]; is_mem[R[i]] = 1; }
    }
    for (int i = 0; i < r; i++) flag_rm[R[i]] = 0;
    nsaved = 0;
    return accepted;
}

/* Choose `units` random members (plus antipodes when centrosymmetric) into R; returns the count. */
static int pick_random(int *R, int r, int units) {
    for (int u = 0; u < units && r < k; u++) {
        int g, tries = 0;
        do { g = S[rng_below(k)]; } while (flag_gone[g] && ++tries < 64);
        if (flag_gone[g]) break;
        flag_gone[g] = 1; /* borrowed as an "already chosen" mark; cleared below */
        R[r++] = g;
        if (cfg.centrosymmetric) {
            int q = G - 1 - g;
            if (q != g && is_mem[q] && !flag_gone[q]) { flag_gone[q] = 1; R[r++] = q; }
        }
    }
    return r;
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
    Flat inst;
    if (flat_parse(inst_path, &inst) != 0) die("cannot read instance");
    n = (int)flat_num(&inst, "n", 0);
    if (n < 1 || n > MAXN) die("instance n must be in 1..64");
    G = n * n * n;

    gx = (int *)malloc(sizeof(int) * (size_t)G);
    gy = (int *)malloc(sizeof(int) * (size_t)G);
    gz = (int *)malloc(sizeof(int) * (size_t)G);
    cnt = (int32_t *)calloc((size_t)G, sizeof(int32_t));
    is_mem = (uint8_t *)calloc((size_t)G, 1);
    flag_rm = (uint8_t *)calloc((size_t)G, 1);
    flag_gone = (uint8_t *)calloc((size_t)G, 1);
    F = (int *)malloc(sizeof(int) * (size_t)G);
    posF = (int *)calloc((size_t)G, sizeof(int));
    ux = (i64 *)malloc(sizeof(i64) * (size_t)G);
    uy = (i64 *)malloc(sizeof(i64) * (size_t)G);
    uz = (i64 *)malloc(sizeof(i64) * (size_t)G);
    uw = (i64 *)malloc(sizeof(i64) * (size_t)G);
    uid = (int *)malloc(sizeof(int) * (size_t)G);
    kills = (int *)malloc(sizeof(int) * (size_t)G);
    kills2 = (int *)malloc(sizeof(int) * (size_t)G);
    if (!gx || !gy || !gz || !cnt || !is_mem || !flag_rm || !flag_gone || !F || !posF || !ux || !uy || !uz || !uw || !uid || !kills || !kills2)
        die("out of memory");
    for (int g = 0; g < G; g++) {
        gx[g] = g / (n * n);
        gy[g] = (g / n) % n;
        gz[g] = g % n;
    }
    rng_seed(seed);

    /* initial construction: a recreate from the empty set, always accepted */
    int R[MAXK] = {0};
    step(R, 0, -1, 1);

    long long since_best = 0;
    int last_best = nbest;
    while (1) {
        if (iter_budget >= 0 && (long long)n_iters >= iter_budget) break;
        if (time_budget >= 0 && cpu_now() >= time_budget) break;
        n_iters++;
        int r = 0, forced = -1, force_accept = 0;
        if (since_best >= cfg.patience) { /* kick: a large ruin, accepted whatever comes out */
            int units = (int)ceil(cfg.kick_fraction * (cfg.centrosymmetric ? k / 2 : k));
            if (units < 1) units = 1;
            r = pick_random(R, 0, units);
            force_accept = 1;
            since_best = 0;
        } else {
            int units = 1 + rng_below(cfg.ruin_max);
            if (cfg.guided_ruin && nrec > 0) {
                /* find a grid point blocked by exactly one sphere; removing one of that sphere's four
                   members frees it, and it is then inserted first */
                for (int t = 0; t < 16; t++) {
                    const Rec *e = &recs[rng_below((int)nrec)];
                    if (cnt[e->p] != 1) continue;
                    int g = e->m[rng_below(4)];
                    forced = e->p;
                    flag_gone[g] = 1;
                    R[r++] = g;
                    if (cfg.centrosymmetric) {
                        int q = G - 1 - g;
                        if (q != g && is_mem[q]) { flag_gone[q] = 1; R[r++] = q; }
                    }
                    units--;
                    break;
                }
            }
            r = pick_random(R, r, units);
        }
        for (int i = 0; i < r; i++) flag_gone[R[i]] = 0;
        step(R, r, forced, force_accept);
        if (nbest > last_best) { last_best = nbest; since_best = 0; }
        else since_best++;
    }

    /* the output is re-verified from scratch; if that ever failed, fall back to a valid subset */
    int out[MAXK], nout = 0;
    int ok = set_is_valid(best, nbest);
    if (ok) {
        nout = nbest;
        memcpy(out, best, (size_t)nbest * sizeof(int));
    } else {
        fprintf(stderr, "solver: internal error, best set failed the self-check; repairing\n");
        for (int i = 0; i < nbest; i++) {
            out[nout++] = best[i];
            if (!set_is_valid(out, nout)) nout--;
        }
    }
    /* canonical order */
    for (int i = 1; i < nout; i++) {
        int v = out[i], j = i - 1;
        while (j >= 0 && out[j] > v) { out[j + 1] = out[j]; j--; }
        out[j + 1] = v;
    }
    FILE *f = fopen(out_path, "w");
    if (!f) die("cannot write output");
    fprintf(f, "{\"solution\": [");
    for (int i = 0; i < nout; i++) fprintf(f, "%s[%d, %d, %d]", i ? ", " : "", gx[out[i]], gy[out[i]], gz[out[i]]);
    fprintf(f, "], \"stats\": {\"iters\": %llu, \"trace\": [", (unsigned long long)n_iters);
    for (int i = 0; i < ntrace; i++) fprintf(f, "%s[%.4f, %d]", i ? ", " : "", trace_t[i], trace_v[i]);
    fprintf(f, "], \"cpu_seconds\": %.4f, \"commit_scans\": %llu, \"tent_evals\": %llu, \"self_check\": %s}}\n", cpu_now(),
            (unsigned long long)n_commit_scans, (unsigned long long)n_tent_evals, (ok && !internal_error) ? "true" : "false");
    fclose(f);
    return 0;
}
