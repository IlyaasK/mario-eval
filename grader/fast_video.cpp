// Fast multi-threaded video gate verifier for Mario Eval.
// Bit-for-bit equivalent to compare_video() in grader/grade.py, using parallel
// zlib decompression, fast frame deduplication, L1-resident decoded RGB planes,
// and exact center-pixel skip before 3x3 neighborhood checks.

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <thread>
#include <vector>
#include <zlib.h>

namespace {

struct RGB {
    uint8_t r, g, b, pad;
};

static inline uint64_t hash_frame(const uint8_t* data, size_t len) {
    // Fast 64-bit word hash (used only with memcmp confirmation, so collisions are impossible).
    uint64_t h = 14695981039346656037ULL;
    size_t i = 0;
    for (; i + 8 <= len; i += 8) {
        uint64_t v;
        std::memcpy(&v, data + i, 8);
        h ^= v;
        h *= 1099511628211ULL;
    }
    for (; i < len; ++i) {
        h ^= data[i];
        h *= 1099511628211ULL;
    }
    return h;
}

static bool read_file_exact(const char* path, std::vector<uint8_t>& out, size_t expected) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    out.resize(expected);
    f.read(reinterpret_cast<char*>(out.data()), static_cast<std::streamsize>(expected));
    return static_cast<size_t>(f.gcount()) == expected;
}

static bool decompress_zlib_exact(const char* path, std::vector<uint8_t>& out, size_t expected) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) return false;
    std::streamsize sz = f.tellg();
    if (sz < 0) return false;
    f.seekg(0, std::ios::beg);
    std::vector<uint8_t> comp(static_cast<size_t>(sz));
    if (sz > 0 && !f.read(reinterpret_cast<char*>(comp.data()), sz)) return false;

    out.resize(expected);
    uLongf dest_len = static_cast<uLongf>(expected);
    int rc = uncompress(out.data(), &dest_len, comp.data(), static_cast<uLong>(comp.size()));
    return rc == Z_OK && static_cast<size_t>(dest_len) == expected;
}

static inline void decode_pixels(const uint8_t* src, RGB* dst, int n, int bpp) {
    if (bpp == 32) {
        for (int i = 0; i < n; ++i) {
            const uint8_t* p = src + static_cast<size_t>(i) * 4;
            dst[i] = {static_cast<uint8_t>(p[0] >> 3),
                      static_cast<uint8_t>(p[1] >> 3),
                      static_cast<uint8_t>(p[2] >> 3), 0};
        }
    } else {
        for (int i = 0; i < n; ++i) {
            uint16_t v = (static_cast<uint16_t>(src[2 * i]) << 8) | src[2 * i + 1];
            dst[i] = {static_cast<uint8_t>((v >> 11) & 31),
                      static_cast<uint8_t>((v >> 6) & 31),
                      static_cast<uint8_t>((v >> 1) & 31), 0};
        }
    }
}

static inline bool within_tol(RGB a, RGB b, int tol) {
    int dr = static_cast<int>(a.r) - static_cast<int>(b.r);
    int dg = static_cast<int>(a.g) - static_cast<int>(b.g);
    int db = static_cast<int>(a.b) - static_cast<int>(b.b);
    return (dr >= -tol && dr <= tol) &&
           (dg >= -tol && dg <= tol) &&
           (db >= -tol && db <= tol);
}

static double mismatch_frac(
    const RGB* c_rgb,
    const uint8_t* ref_raw,
    RGB* r_rgb,
    std::vector<int>& diff_idx,
    int w,
    int h,
    int bpp,
    int tol
) {
    const int n = w * h;
    diff_idx.clear();

    // Pass 1: decode ref frame and record ONLY pixels whose center diff > tol.
    // Any pixel with |c(p) - r(p)| <= tol automatically satisfies both
    // unmatched(c, r) == false and unmatched(r, c) == false at p.
    if (bpp == 32) {
        for (int i = 0; i < n; ++i) {
            const uint8_t* p = ref_raw + static_cast<size_t>(i) * 4;
            RGB rv = {static_cast<uint8_t>(p[0] >> 3),
                      static_cast<uint8_t>(p[1] >> 3),
                      static_cast<uint8_t>(p[2] >> 3), 0};
            r_rgb[i] = rv;
            if (!within_tol(c_rgb[i], rv, tol)) {
                diff_idx.push_back(i);
            }
        }
    } else {
        for (int i = 0; i < n; ++i) {
            uint16_t v = (static_cast<uint16_t>(ref_raw[2 * i]) << 8) | ref_raw[2 * i + 1];
            RGB rv = {static_cast<uint8_t>((v >> 11) & 31),
                      static_cast<uint8_t>((v >> 6) & 31),
                      static_cast<uint8_t>((v >> 1) & 31), 0};
            r_rgb[i] = rv;
            if (!within_tol(c_rgb[i], rv, tol)) {
                diff_idx.push_back(i);
            }
        }
    }

    if (diff_idx.empty()) return 0.0;

    int bad = 0;
    for (int idx : diff_idx) {
        const int y = idx / w;
        const int x = idx - y * w;
        const int y0 = (y > 0) ? y - 1 : 0;
        const int y1 = (y + 1 < h) ? y + 1 : h - 1;
        const int x0 = (x > 0) ? x - 1 : 0;
        const int x1 = (x + 1 < w) ? x + 1 : w - 1;

        const RGB cp = c_rgb[idx];
        bool ok_ab = false;
        for (int ny = y0; ny <= y1 && !ok_ab; ++ny) {
            const RGB* row = r_rgb + ny * w;
            for (int nx = x0; nx <= x1; ++nx) {
                if (within_tol(cp, row[nx], tol)) {
                    ok_ab = true;
                    break;
                }
            }
        }
        if (!ok_ab) {
            ++bad;
            continue;
        }

        const RGB rp = r_rgb[idx];
        bool ok_ba = false;
        for (int ny = y0; ny <= y1 && !ok_ba; ++ny) {
            const RGB* row = c_rgb + ny * w;
            for (int nx = x0; nx <= x1; ++nx) {
                if (within_tol(rp, row[nx], tol)) {
                    ok_ba = true;
                    break;
                }
            }
        }
        if (!ok_ba) {
            ++bad;
        }
    }

    return static_cast<double>(bad) / static_cast<double>(n);
}

// GBA Eval-compatible single-scale block-SSIM on 5-bit quantized BT.601 luma.
// Expands 5-bit channels to 8-bit ((c << 3) | (c >> 2)), computes Wang et al.
// SSIM on non-overlapping 16x16 blocks (w >= 320) or 10x10 blocks (w < 320),
// applies the 0.15 block defect floor, and enforces a >=99.9% blank-frame gate.
static inline void decode_luma_and_uniform(
    const uint8_t* raw,
    float* luma,
    int w,
    int h,
    int bpp,
    bool& is_uniform
) {
    const int n = w * h;
    // Boyer-Moore majority vote on 15-bit RGB key to detect >=99.9% single-color frames in O(n).
    uint16_t maj_key = 0;
    int votes = 0;
    if (bpp == 32) {
        for (int i = 0; i < n; ++i) {
            const uint8_t* p = raw + static_cast<size_t>(i) * 4;
            uint8_t r5 = static_cast<uint8_t>(p[0] >> 3);
            uint8_t g5 = static_cast<uint8_t>(p[1] >> 3);
            uint8_t b5 = static_cast<uint8_t>(p[2] >> 3);
            uint16_t key = static_cast<uint16_t>((r5 << 10) | (g5 << 5) | b5);
            if (votes == 0) { maj_key = key; votes = 1; }
            else if (key == maj_key) { ++votes; }
            else { --votes; }
            float r8 = static_cast<float>((r5 << 3) | (r5 >> 2));
            float g8 = static_cast<float>((g5 << 3) | (g5 >> 2));
            float b8 = static_cast<float>((b5 << 3) | (b5 >> 2));
            luma[i] = 0.299f * r8 + 0.587f * g8 + 0.114f * b8;
        }
        int maj_cnt = 0;
        for (int i = 0; i < n; ++i) {
            const uint8_t* p = raw + static_cast<size_t>(i) * 4;
            uint16_t key = static_cast<uint16_t>(((p[0] >> 3) << 10) | ((p[1] >> 3) << 5) | (p[2] >> 3));
            if (key == maj_key) ++maj_cnt;
        }
        is_uniform = (static_cast<double>(maj_cnt) / static_cast<double>(n)) >= 0.999;
    } else {
        for (int i = 0; i < n; ++i) {
            uint16_t v = (static_cast<uint16_t>(raw[2 * i]) << 8) | raw[2 * i + 1];
            uint16_t key = static_cast<uint16_t>(v >> 1);
            if (votes == 0) { maj_key = key; votes = 1; }
            else if (key == maj_key) { ++votes; }
            else { --votes; }
            uint8_t r5 = static_cast<uint8_t>((v >> 11) & 31);
            uint8_t g5 = static_cast<uint8_t>((v >> 6) & 31);
            uint8_t b5 = static_cast<uint8_t>((v >> 1) & 31);
            float r8 = static_cast<float>((r5 << 3) | (r5 >> 2));
            float g8 = static_cast<float>((g5 << 3) | (g5 >> 2));
            float b8 = static_cast<float>((b5 << 3) | (b5 >> 2));
            luma[i] = 0.299f * r8 + 0.587f * g8 + 0.114f * b8;
        }
        int maj_cnt = 0;
        for (int i = 0; i < n; ++i) {
            uint16_t v = (static_cast<uint16_t>(raw[2 * i]) << 8) | raw[2 * i + 1];
            if (static_cast<uint16_t>(v >> 1) == maj_key) ++maj_cnt;
        }
        is_uniform = (static_cast<double>(maj_cnt) / static_cast<double>(n)) >= 0.999;
    }
}

static double block_ssim_defect(
    const float* ly_a,
    const float* ly_b,
    int w,
    int h
) {
    constexpr double C1 = 6.5025;   // (0.01 * 255)^2
    constexpr double C2 = 58.5225;  // (0.03 * 255)^2
    constexpr double FLOOR = 0.15;
    const int bs = (w >= 320) ? 16 : 10;

    double defect_sum = 0.0;
    int blocks = 0;
    for (int y0 = 0; y0 < h; y0 += bs) {
        const int y1 = std::min(h, y0 + bs);
        for (int x0 = 0; x0 < w; x0 += bs) {
            const int x1 = std::min(w, x0 + bs);
            const int cnt = (y1 - y0) * (x1 - x0);
            double sx = 0.0, sy = 0.0, sxx = 0.0, syy = 0.0, sxy = 0.0;
            for (int y = y0; y < y1; ++y) {
                const float* ra = ly_a + static_cast<size_t>(y) * w;
                const float* rb = ly_b + static_cast<size_t>(y) * w;
                for (int x = x0; x < x1; ++x) {
                    const double a = ra[x];
                    const double b = rb[x];
                    sx += a;
                    sy += b;
                    sxx += a * a;
                    syy += b * b;
                    sxy += a * b;
                }
            }
            const double inv_n = 1.0 / static_cast<double>(cnt);
            const double mx = sx * inv_n;
            const double my = sy * inv_n;
            const double vx = std::max(0.0, sxx * inv_n - mx * mx);
            const double vy = std::max(0.0, syy * inv_n - my * my);
            const double cov = sxy * inv_n - mx * my;
            const double num = (2.0 * mx * my + C1) * (2.0 * cov + C2);
            const double den = (mx * mx + my * my + C1) * (vx + vy + C2);
            double ssim = (den > 0.0) ? (num / den) : 1.0;
            if (ssim < 0.0) ssim = 0.0;
            if (ssim > 1.0) ssim = 1.0;
            double d = 1.0 - ssim;
            if (d < FLOOR) d = 0.0;
            defect_sum += d;
            ++blocks;
        }
    }
    return blocks > 0 ? (defect_sum / static_cast<double>(blocks)) : 0.0;
}

static void compute_video_ssim_metrics(
    const std::vector<uint8_t>& cand_buf,
    const std::vector<uint8_t>& ref_buf,
    int frames,
    int w,
    int h,
    int bpp,
    int threads,
    double& out_mean_score,
    double& out_worst_score,
    int& out_worst_frame,
    double& out_tau,
    double& out_worst_defect
) {
    const size_t n_px = static_cast<size_t>(w) * static_cast<size_t>(h);
    const size_t fsize = n_px * static_cast<size_t>(bpp / 8);

    // 1. Decode all reference frames to luma + uniformity in parallel, and compute
    //    cand-vs-ref defect per frame in the same pass.
    std::vector<float> ref_luma(static_cast<size_t>(frames) * n_px);
    std::vector<uint8_t> ref_unif(static_cast<size_t>(frames), 0);
    std::vector<double> cand_defects(static_cast<size_t>(frames), 0.0);

    {
        std::atomic<int> next_f{0};
        const int n_workers = std::min(threads, frames);
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(n_workers));
        for (int t = 0; t < n_workers; ++t) {
            pool.emplace_back([&]() {
                std::vector<float> c_luma(n_px);
                while (true) {
                    int i = next_f.fetch_add(1, std::memory_order_relaxed);
                    if (i >= frames) break;
                    const size_t fi = static_cast<size_t>(i);
                    const uint8_t* rf = ref_buf.data() + fi * fsize;
                    const uint8_t* cf = cand_buf.data() + fi * fsize;
                    float* rl = ref_luma.data() + fi * n_px;
                    bool ru = false;
                    decode_luma_and_uniform(rf, rl, w, h, bpp, ru);
                    ref_unif[fi] = ru ? 1 : 0;
                    if (std::memcmp(cf, rf, fsize) == 0) {
                        cand_defects[fi] = 0.0;
                    } else {
                        bool cu = false;
                        decode_luma_and_uniform(cf, c_luma.data(), w, h, bpp, cu);
                        if (cu && !ru) {
                            cand_defects[fi] = 1.0;
                        } else {
                            cand_defects[fi] = block_ssim_defect(c_luma.data(), rl, w, h);
                        }
                    }
                }
            });
        }
        for (auto& th : pool) th.join();
    }

    // 2. Motion-adaptive per-replay tau = p90(defect(ref_t, ref_{t+1}) for moving pairs),
    //    clamped to [0.005, 0.35] (default 0.05 if no moving pairs).
    double tau = 0.05;
    if (frames >= 2) {
        std::vector<double> motion(static_cast<size_t>(frames - 1), 0.0);
        std::atomic<int> next_p{0};
        const int n_pairs = frames - 1;
        const int n_workers = std::min(threads, n_pairs);
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(n_workers));
        for (int t = 0; t < n_workers; ++t) {
            pool.emplace_back([&]() {
                while (true) {
                    int i = next_p.fetch_add(1, std::memory_order_relaxed);
                    if (i >= n_pairs) break;
                    const size_t fi = static_cast<size_t>(i);
                    if (std::memcmp(ref_buf.data() + fi * fsize,
                                    ref_buf.data() + (fi + 1) * fsize, fsize) == 0) {
                        motion[fi] = 0.0;
                    } else {
                        motion[fi] = block_ssim_defect(
                            ref_luma.data() + fi * n_px,
                            ref_luma.data() + (fi + 1) * n_px,
                            w, h
                        );
                    }
                }
            });
        }
        for (auto& th : pool) th.join();

        std::vector<double> moving;
        moving.reserve(static_cast<size_t>(n_pairs));
        for (double d : motion) {
            if (d > 0.0) moving.push_back(d);
        }
        if (!moving.empty()) {
            std::sort(moving.begin(), moving.end());
            double pos = 0.90 * static_cast<double>(moving.size() - 1);
            size_t lo = static_cast<size_t>(std::floor(pos));
            size_t hi = static_cast<size_t>(std::ceil(pos));
            double frac = pos - static_cast<double>(lo);
            double p90 = moving[lo] * (1.0 - frac) + moving[hi] * frac;
            tau = std::clamp(p90, 0.005, 0.35);
        }
    }

    // 3. Hill per-frame score: 1 / (1 + (d / tau)^4).
    double score_sum = 0.0;
    double worst_score = 1.0;
    int worst_frame = -1;
    double worst_defect = 0.0;
    const double inv_tau = 1.0 / std::max(tau, 1e-12);
    for (int i = 0; i < frames; ++i) {
        const double d = cand_defects[static_cast<size_t>(i)];
        const double r = d * inv_tau;
        const double r2 = r * r;
        const double sc = 1.0 / (1.0 + r2 * r2);
        score_sum += sc;
        if (d > worst_defect) {
            worst_defect = d;
        }
        if (sc < worst_score) {
            worst_score = sc;
            worst_frame = i;
        }
    }
    out_mean_score = score_sum / static_cast<double>(frames);
    out_worst_score = worst_score;
    out_worst_frame = worst_frame;
    out_tau = tau;
    out_worst_defect = worst_defect;
}

}  // namespace

extern "C" int compare_video_v3(
    const char* cand_path,
    const char** ref_paths,
    int n_ref_paths,
    int frames,
    int w,
    int h,
    int bpp,
    int tol,
    double limit,
    int max_threads,
    int* out_pass,
    double* out_worst_frac,
    int* out_worst_frame,
    int* out_failed_frames,
    int* out_variant_frames,
    int* out_best_ref,
    double* out_mean_frac,
    double* out_ssim_score,
    double* out_worst_ssim_score,
    int* out_worst_ssim_frame,
    double* out_ssim_tau,
    double* out_worst_ssim_defect
) {
    if (n_ref_paths <= 0 || frames <= 0 || w <= 0 || h <= 0 || (bpp != 16 && bpp != 32)) {
        return 1;
    }
    const size_t fsize = static_cast<size_t>(w) * static_cast<size_t>(h) * static_cast<size_t>(bpp / 8);
    const size_t total_bytes = static_cast<size_t>(frames) * fsize;
    int threads = std::max(1, max_threads);

    auto write_ssim_perfect = [&]() {
        if (out_mean_frac) *out_mean_frac = 0.0;
        if (out_ssim_score) *out_ssim_score = 1.0;
        if (out_worst_ssim_score) *out_worst_ssim_score = 1.0;
        if (out_worst_ssim_frame) *out_worst_ssim_frame = -1;
        if (out_ssim_tau) *out_ssim_tau = 0.05;
        if (out_worst_ssim_defect) *out_worst_ssim_defect = 0.0;
    };

    // 1. Read cand_path and decompress ref_paths[0] (orig) first.
    //    If all frames match orig byte-for-byte, skip decompressing variants entirely!
    std::vector<uint8_t> cand_buf;
    std::vector<std::vector<uint8_t>> ref_bufs(static_cast<size_t>(n_ref_paths));
    std::atomic<int> io_err{0};

    {
        std::thread t_cand([&]() {
            if (!read_file_exact(cand_path, cand_buf, total_bytes)) {
                io_err.store(2, std::memory_order_relaxed);
            }
        });
        if (!decompress_zlib_exact(ref_paths[0], ref_bufs[0], total_bytes)) {
            io_err.store(3, std::memory_order_relaxed);
        }
        t_cand.join();
    }
    if (io_err.load() != 0) return io_err.load();

    // Fast path 0: entire video matches orig byte-for-byte (0 variant decompression!).
    if (std::memcmp(cand_buf.data(), ref_bufs[0].data(), total_bytes) == 0) {
        *out_pass = 1;
        *out_worst_frac = 0.0;
        *out_worst_frame = -1;
        *out_failed_frames = 0;
        *out_variant_frames = 0;
        if (out_best_ref) *out_best_ref = 0;
        write_ssim_perfect();
        return 0;
    }

    // Fast path 0b: check every non-exact frame against orig FIRST; if every frame
    // already has 0.0 mismatch vs orig, no variant can improve on 0.0 and orig (r=0)
    // wins tie-breaking — skip decompressing all variant files!
    std::vector<double> orig_fracs(static_cast<size_t>(frames), 0.0);
    std::vector<uint8_t> orig_exact(static_cast<size_t>(frames), 0);
    std::atomic<int> any_need_variants{0};
    {
        std::atomic<int> next_frame{0};
        const int n_workers = std::min(threads, frames);
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(n_workers));
        for (int t = 0; t < n_workers; ++t) {
            pool.emplace_back([&]() {
                std::vector<RGB> c_rgb(static_cast<size_t>(w) * static_cast<size_t>(h));
                std::vector<RGB> r_rgb(static_cast<size_t>(w) * static_cast<size_t>(h));
                std::vector<int> diff_idx;
                diff_idx.reserve(4096);
                while (true) {
                    int i = next_frame.fetch_add(1, std::memory_order_relaxed);
                    if (i >= frames) break;
                    const size_t off = static_cast<size_t>(i) * fsize;
                    const uint8_t* cand_f = cand_buf.data() + off;
                    const uint8_t* orig_f = ref_bufs[0].data() + off;
                    if (std::memcmp(cand_f, orig_f, fsize) == 0) {
                        orig_exact[static_cast<size_t>(i)] = 1;
                        continue;
                    }
                    if (n_ref_paths > 1) {
                        any_need_variants.store(1, std::memory_order_relaxed);
                    }
                    decode_pixels(cand_f, c_rgb.data(), w * h, bpp);
                    double of = mismatch_frac(c_rgb.data(), orig_f, r_rgb.data(), diff_idx, w, h, bpp, tol);
                    orig_fracs[static_cast<size_t>(i)] = of;
                    if (of > 0.0) {
                        any_need_variants.store(1, std::memory_order_relaxed);
                    }
                }
            });
        }
        for (auto& th : pool) th.join();
    }
    if (any_need_variants.load() == 0) {
        *out_pass = 1;
        *out_worst_frac = 0.0;
        *out_worst_frame = -1;
        *out_failed_frames = 0;
        *out_variant_frames = 0;
        if (out_best_ref) *out_best_ref = 0;
        if (out_mean_frac) *out_mean_frac = 0.0;
        if (out_ssim_score || out_worst_ssim_score || out_worst_ssim_frame || out_ssim_tau || out_worst_ssim_defect) {
            double ms = 1.0, ws = 1.0, tau = 0.05, wd = 0.0;
            int wf = -1;
            compute_video_ssim_metrics(cand_buf, ref_bufs[0], frames, w, h, bpp, threads, ms, ws, wf, tau, wd);
            if (out_ssim_score) *out_ssim_score = ms;
            if (out_worst_ssim_score) *out_worst_ssim_score = ws;
            if (out_worst_ssim_frame) *out_worst_ssim_frame = wf;
            if (out_ssim_tau) *out_ssim_tau = tau;
            if (out_worst_ssim_defect) *out_worst_ssim_defect = wd;
        }
        return 0;
    }

    // Decompress remaining variant reference files in parallel.
    if (n_ref_paths > 1) {
        std::atomic<int> next_ref{1};
        const int n_workers = std::min(threads, n_ref_paths - 1);
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(n_workers));
        for (int t = 0; t < n_workers; ++t) {
            pool.emplace_back([&]() {
                while (true) {
                    int r = next_ref.fetch_add(1, std::memory_order_relaxed);
                    if (r >= n_ref_paths) break;
                    if (!decompress_zlib_exact(ref_paths[r], ref_bufs[static_cast<size_t>(r)], total_bytes)) {
                        io_err.store(3, std::memory_order_relaxed);
                    }
                }
            });
        }
        for (auto& th : pool) th.join();
    }
    if (io_err.load() != 0) return io_err.load();

    // 2. Parallel per-frame evaluation against every distinct variant picture,
    //    populating frac_mat[r * frames + i] so that a single consistent variant r
    //    must hold across all frames of the workload (no per-frame variant mixing).
    const size_t n_refs = static_cast<size_t>(n_ref_paths);
    const size_t n_frames = static_cast<size_t>(frames);
    std::vector<double> frac_mat(n_refs * n_frames, 0.0);
    std::vector<uint8_t> exact_mat(n_refs * n_frames, 0);
    for (size_t i = 0; i < n_frames; ++i) {
        frac_mat[i] = orig_fracs[i];
        exact_mat[i] = orig_exact[i];
    }

    if (n_ref_paths > 1) {
        std::atomic<int> next_frame{0};
        const int n_workers = std::min(threads, frames);
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(n_workers));
        for (int t = 0; t < n_workers; ++t) {
            pool.emplace_back([&]() {
                std::vector<RGB> c_rgb(static_cast<size_t>(w) * static_cast<size_t>(h));
                std::vector<RGB> r_rgb(static_cast<size_t>(w) * static_cast<size_t>(h));
                std::vector<int> diff_idx;
                diff_idx.reserve(4096);
                std::vector<const uint8_t*> uniq_ptrs;
                std::vector<uint64_t> uniq_hashes;
                std::vector<double> uniq_fracs;
                std::vector<int> ref_to_uniq(n_refs, -1);
                uniq_ptrs.reserve(n_refs);
                uniq_hashes.reserve(n_refs);
                uniq_fracs.reserve(n_refs);

                while (true) {
                    int i = next_frame.fetch_add(1, std::memory_order_relaxed);
                    if (i >= frames) break;

                    const size_t fi = static_cast<size_t>(i);
                    const size_t off = fi * fsize;
                    const uint8_t* cand_f = cand_buf.data() + off;
                    const uint8_t* orig_f = ref_bufs[0].data() + off;

                    uniq_ptrs.clear();
                    uniq_hashes.clear();
                    uniq_fracs.clear();
                    uniq_ptrs.push_back(orig_f);
                    uniq_hashes.push_back(hash_frame(orig_f, fsize));
                    uniq_fracs.push_back(orig_fracs[fi]);
                    ref_to_uniq[0] = 0;

                    bool cand_decoded = false;
                    for (int r = 1; r < n_ref_paths; ++r) {
                        const size_t ri = static_cast<size_t>(r);
                        const uint8_t* rf = ref_bufs[ri].data() + off;
                        if (std::memcmp(cand_f, rf, fsize) == 0) {
                            exact_mat[ri * n_frames + fi] = 1;
                            frac_mat[ri * n_frames + fi] = 0.0;
                            ref_to_uniq[ri] = -1;
                            continue;
                        }
                        uint64_t rh = hash_frame(rf, fsize);
                        int found = -1;
                        for (size_t k = 0; k < uniq_ptrs.size(); ++k) {
                            if (uniq_hashes[k] == rh && std::memcmp(uniq_ptrs[k], rf, fsize) == 0) {
                                found = static_cast<int>(k);
                                break;
                            }
                        }
                        if (found >= 0) {
                            ref_to_uniq[ri] = found;
                            frac_mat[ri * n_frames + fi] = uniq_fracs[static_cast<size_t>(found)];
                        } else {
                            if (!cand_decoded) {
                                decode_pixels(cand_f, c_rgb.data(), w * h, bpp);
                                cand_decoded = true;
                            }
                            double vf = mismatch_frac(c_rgb.data(), rf, r_rgb.data(), diff_idx, w, h, bpp, tol);
                            int uidx = static_cast<int>(uniq_ptrs.size());
                            uniq_ptrs.push_back(rf);
                            uniq_hashes.push_back(rh);
                            uniq_fracs.push_back(vf);
                            ref_to_uniq[ri] = uidx;
                            frac_mat[ri * n_frames + fi] = vf;
                        }
                    }
                }
            });
        }
        for (auto& th : pool) th.join();
    }

    // 3. Deterministic sequential reduction: choose one consistent variant r across
    //    all frames minimizing (failed_frames, worst_frac, sum_frac, -exact_frames, r).
    int best_r = 0;
    double best_worst_frac = 2.0;
    double best_sum_frac = 1e18;
    double best_mean_frac = 1.0;
    int best_worst_frame = -1;
    int best_failed = frames + 1;
    int best_exact = -1;
    int best_variant = 0;
    std::vector<int> zero_fail_refs;

    for (int r = 0; r < n_ref_paths; ++r) {
        const size_t row = static_cast<size_t>(r) * n_frames;
        double r_worst_frac = 0.0;
        double r_sum_frac = 0.0;
        int r_worst_frame = -1;
        int r_failed = 0;
        int r_exact = 0;
        int r_variant = 0;
        for (int i = 0; i < frames; ++i) {
            const size_t fi = static_cast<size_t>(i);
            const double f = frac_mat[row + fi];
            r_sum_frac += f;
            if (exact_mat[row + fi]) {
                ++r_exact;
            }
            if (f > limit) {
                ++r_failed;
            }
            if (r > 0 && !exact_mat[fi]) {
                if (exact_mat[row + fi] || (orig_fracs[fi] > limit && f <= limit)) {
                    ++r_variant;
                }
            }
            if (f > r_worst_frac) {
                r_worst_frac = f;
                r_worst_frame = i;
            }
        }
        if (r_failed == 0 && r_worst_frac <= limit) {
            zero_fail_refs.push_back(r);
        }
        bool better = false;
        if (r_failed != best_failed) {
            better = (r_failed < best_failed);
        } else if (r_worst_frac != best_worst_frac) {
            better = (r_worst_frac < best_worst_frac);
        } else if (std::abs(r_sum_frac - best_sum_frac) > 1e-15) {
            better = (r_sum_frac < best_sum_frac);
        } else if (r_exact != best_exact) {
            better = (r_exact > best_exact);
        }
        if (better) {
            best_r = r;
            best_worst_frac = r_worst_frac;
            best_sum_frac = r_sum_frac;
            best_mean_frac = r_sum_frac / static_cast<double>(frames);
            best_worst_frame = r_worst_frame;
            best_failed = r_failed;
            best_exact = r_exact;
            best_variant = r_variant;
        }
    }

    *out_pass = (best_worst_frac <= limit) ? 1 : 0;
    *out_worst_frac = best_worst_frac;
    *out_worst_frame = best_worst_frame;
    *out_failed_frames = best_failed;
    *out_variant_frames = best_variant;
    if (out_best_ref) *out_best_ref = best_r;
    if (out_mean_frac) *out_mean_frac = best_mean_frac;

    if (out_ssim_score || out_worst_ssim_score || out_worst_ssim_frame || out_ssim_tau || out_worst_ssim_defect) {
        if (std::memcmp(cand_buf.data(), ref_bufs[static_cast<size_t>(best_r)].data(), total_bytes) == 0) {
            if (out_ssim_score) *out_ssim_score = 1.0;
            if (out_worst_ssim_score) *out_worst_ssim_score = 1.0;
            if (out_worst_ssim_frame) *out_worst_ssim_frame = -1;
            if (out_ssim_tau) *out_ssim_tau = 0.05;
            if (out_worst_ssim_defect) *out_worst_ssim_defect = 0.0;
        } else {
            double ms = 1.0, ws = 1.0, tau = 0.05, wd = 0.0;
            int wf = -1;
            compute_video_ssim_metrics(
                cand_buf, ref_bufs[static_cast<size_t>(best_r)],
                frames, w, h, bpp, threads, ms, ws, wf, tau, wd
            );
            // If multiple refs passed the pixel gate (0 failed frames) and best_r
            // did not achieve near-exact SSIM, pick the pixel-passing ref with highest SSIM.
            if (zero_fail_refs.size() > 1 && (ms < 0.999 || ws < 0.95)) {
                for (int alt_r : zero_fail_refs) {
                    if (alt_r == best_r) continue;
                    double ams = 1.0, aws = 1.0, atau = 0.05, awd = 0.0;
                    int awf = -1;
                    compute_video_ssim_metrics(
                        cand_buf, ref_bufs[static_cast<size_t>(alt_r)],
                        frames, w, h, bpp, threads, ams, aws, awf, atau, awd
                    );
                    if (ams > ms + 1e-9 || (std::abs(ams - ms) <= 1e-9 && aws > ws + 1e-9)) {
                        best_r = alt_r;
                        ms = ams; ws = aws; wf = awf; tau = atau; wd = awd;
                        const size_t row = static_cast<size_t>(alt_r) * n_frames;
                        double rw = 0.0, rs = 0.0;
                        int rwf = -1, rv = 0;
                        for (int i = 0; i < frames; ++i) {
                            const size_t fi = static_cast<size_t>(i);
                            const double f = frac_mat[row + fi];
                            rs += f;
                            if (alt_r > 0 && !exact_mat[fi] && (exact_mat[row + fi] || (orig_fracs[fi] > limit && f <= limit))) {
                                ++rv;
                            }
                            if (f > rw) { rw = f; rwf = i; }
                        }
                        *out_worst_frac = rw;
                        *out_worst_frame = rwf;
                        *out_variant_frames = rv;
                        if (out_best_ref) *out_best_ref = alt_r;
                        if (out_mean_frac) *out_mean_frac = rs / static_cast<double>(frames);
                    }
                }
            }
            if (out_ssim_score) *out_ssim_score = ms;
            if (out_worst_ssim_score) *out_worst_ssim_score = ws;
            if (out_worst_ssim_frame) *out_worst_ssim_frame = wf;
            if (out_ssim_tau) *out_ssim_tau = tau;
            if (out_worst_ssim_defect) *out_worst_ssim_defect = wd;
        }
    }
    return 0;
}

extern "C" int compare_video_consistent(
    const char* cand_path,
    const char** ref_paths,
    int n_ref_paths,
    int frames,
    int w,
    int h,
    int bpp,
    int tol,
    double limit,
    int max_threads,
    int* out_pass,
    double* out_worst_frac,
    int* out_worst_frame,
    int* out_failed_frames,
    int* out_variant_frames,
    int* out_best_ref
) {
    return compare_video_v3(
        cand_path, ref_paths, n_ref_paths, frames, w, h, bpp, tol, limit, max_threads,
        out_pass, out_worst_frac, out_worst_frame, out_failed_frames, out_variant_frames,
        out_best_ref, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr
    );
}

extern "C" int compare_video_fast(
    const char* cand_path,
    const char** ref_paths,
    int n_ref_paths,
    int frames,
    int w,
    int h,
    int bpp,
    int tol,
    double limit,
    int max_threads,
    int* out_pass,
    double* out_worst_frac,
    int* out_worst_frame,
    int* out_failed_frames,
    int* out_variant_frames
) {
    return compare_video_consistent(
        cand_path, ref_paths, n_ref_paths, frames, w, h, bpp, tol, limit, max_threads,
        out_pass, out_worst_frac, out_worst_frame, out_failed_frames, out_variant_frames,
        nullptr
    );
}

namespace {

static inline uint32_t be32(const uint8_t* p) {
    return (static_cast<uint32_t>(p[0]) << 24) |
           (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8)  |
           static_cast<uint32_t>(p[3]);
}

static inline uint16_t be16(const uint8_t* p) {
    return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8) | p[1]);
}

static inline float be_f32(const uint8_t* p) {
    uint32_t u = be32(p);
    float f;
    std::memcpy(&f, &u, sizeof(float));
    return f;
}

static bool kuhn_augment(
    int u,
    const std::vector<std::vector<int>>& adj,
    int* match_b,
    uint8_t* seen
) {
    for (int v : adj[static_cast<size_t>(u)]) {
        if (seen[v]) continue;
        seen[v] = 1;
        if (match_b[v] < 0 || kuhn_augment(match_b[v], adj, match_b, seen)) {
            match_b[v] = u;
            return true;
        }
    }
    return false;
}

}  // namespace

// Fast C++ implementation of SM64 player-equivalence compare_obs() over 4224-byte
// big-endian mev_obs_t records (1056 32-bit words per frame, 256 actor slots).
// When out_pass == 0, out_first_fail_frame identifies the exact first failing frame
// so Python only decodes that single frame to format human-readable failure details.
extern "C" int compare_obs_sm64_fast(
    const uint8_t* ref_buf,
    const uint8_t* cand_buf,
    int frames,
    double tol_mario_pos,
    double tol_mario_vel,
    double tol_floor_height,
    double tol_cam_pos,
    double tol_cam_focus,
    double actor_tol,
    double actor_radius,
    int* out_pass,
    int* out_failed_frames,
    int* out_first_fail_frame,
    double* out_gameplay_score,
    double* out_max_pos_drift
) {
    if (!ref_buf || !cand_buf || frames <= 0) return 1;
    constexpr size_t FRAME_BYTES = 4224;
    constexpr int MAX_ACTORS = 256;

    double worst_drift = 0.0;
    double score_sum = 0.0;
    int failed_frames = 0;
    int first_fail_frame = -1;

    std::vector<int> near_idx;
    near_idx.reserve(MAX_ACTORS);
    std::vector<std::vector<int>> adj(MAX_ACTORS);
    int match_b[MAX_ACTORS];
    uint8_t seen[MAX_ACTORS];

    auto check_vec_tol = [](const uint8_t* rp, const uint8_t* cp, int count, double tol,
                            double& max_excess, bool& failed, double* raw_max_out) {
        double ftol = std::max(tol, 1e-9);
        double best = 0.0;
        for (int k = 0; k < count; ++k) {
            double rf = static_cast<double>(be_f32(rp + k * 4));
            double cf = static_cast<double>(be_f32(cp + k * 4));
            if (!std::isfinite(rf) || !std::isfinite(cf)) {
                failed = true;
                max_excess = INFINITY;
                return;
            }
            double d = std::abs(rf - cf);
            if (d > best) best = d;
        }
        if (raw_max_out && best > *raw_max_out) *raw_max_out = best;
        if (best > ftol) {
            failed = true;
            double r = best / ftol;
            if (r > max_excess) max_excess = r;
        }
    };

    for (int i = 0; i < frames; ++i) {
        const uint8_t* rf = ref_buf + static_cast<size_t>(i) * FRAME_BYTES;
        const uint8_t* cf = cand_buf + static_cast<size_t>(i) * FRAME_BYTES;
        if (std::memcmp(rf, cf, FRAME_BYTES) == 0) {
            score_sum += 1.0;
            continue;
        }

        bool frame_exact_ok = true;
        bool frame_failed = false;

        // Exact fields: frame (w0), level_area (w1), mario_action (w4),
        // mario_stats[4] (w20..23), actor_count (w31).
        if (be32(rf + 0 * 4) != be32(cf + 0 * 4) ||
            be32(rf + 1 * 4) != be32(cf + 1 * 4) ||
            be32(rf + 4 * 4) != be32(cf + 4 * 4) ||
            std::memcmp(rf + 20 * 4, cf + 20 * 4, 16) != 0 ||
            be32(rf + 31 * 4) != be32(cf + 31 * 4)) {
            frame_exact_ok = false;
            frame_failed = true;
        }

        double max_excess_ratio = 0.0;
        // Float tolerances: mario_pos (w8..10), mario_vel (w11..13),
        // mario_floor_height (w15), cam_pos (w24..26), cam_focus (w27..29).
        check_vec_tol(rf + 8 * 4,  cf + 8 * 4,  3, tol_mario_pos,    max_excess_ratio, frame_failed, &worst_drift);
        check_vec_tol(rf + 11 * 4, cf + 11 * 4, 3, tol_mario_vel,    max_excess_ratio, frame_failed, nullptr);
        check_vec_tol(rf + 15 * 4, cf + 15 * 4, 1, tol_floor_height, max_excess_ratio, frame_failed, nullptr);
        check_vec_tol(rf + 24 * 4, cf + 24 * 4, 3, tol_cam_pos,      max_excess_ratio, frame_failed, nullptr);
        check_vec_tol(rf + 27 * 4, cf + 27 * 4, 3, tol_cam_focus,    max_excess_ratio, frame_failed, nullptr);

        bool actor_miss = false;
        if (actor_tol >= 0.0) {
            uint32_t r_cnt = be32(rf + 31 * 4);
            uint32_t c_cnt = be32(cf + 31 * 4);
            if (r_cnt == c_cnt && r_cnt > 0 && r_cnt <= static_cast<uint32_t>(MAX_ACTORS)) {
                const int cnt = static_cast<int>(r_cnt);
                const uint8_t* r_apos = rf + 32 * 4;
                const uint8_t* c_apos = cf + 32 * 4;
                const uint8_t* r_ast  = rf + 800 * 4;
                const uint8_t* c_ast  = cf + 800 * 4;

                bool in_order_ok = (std::memcmp(r_ast, c_ast, static_cast<size_t>(cnt) * 4) == 0);
                if (in_order_ok) {
                    for (int k = 0; k < cnt * 3; ++k) {
                        double rv = static_cast<double>(be_f32(r_apos + k * 4));
                        double cv = static_cast<double>(be_f32(c_apos + k * 4));
                        if (!std::isfinite(rv) || !std::isfinite(cv) || std::abs(rv - cv) > actor_tol) {
                            in_order_ok = false;
                            break;
                        }
                    }
                }
                if (!in_order_ok) {
                    const double mx = static_cast<double>(be_f32(rf + 8 * 4));
                    const double my = static_cast<double>(be_f32(rf + 9 * 4));
                    const double mz = static_cast<double>(be_f32(rf + 10 * 4));
                    const double rad2 = actor_radius * actor_radius;
                    near_idx.clear();
                    for (int a = 0; a < cnt; ++a) {
                        const double rx = static_cast<double>(be_f32(r_apos + (a * 3 + 0) * 4));
                        const double ry = static_cast<double>(be_f32(r_apos + (a * 3 + 1) * 4));
                        const double rz = static_cast<double>(be_f32(r_apos + (a * 3 + 2) * 4));
                        const double dx = rx - mx, dy = ry - my, dz = rz - mz;
                        if (dx * dx + dy * dy + dz * dz <= rad2) {
                            near_idx.push_back(a);
                        }
                    }
                    if (!near_idx.empty()) {
                        for (int a : near_idx) {
                            adj[static_cast<size_t>(a)].clear();
                            const uint32_t rs = be32(r_ast + a * 4);
                            const double rx = static_cast<double>(be_f32(r_apos + (a * 3 + 0) * 4));
                            const double ry = static_cast<double>(be_f32(r_apos + (a * 3 + 1) * 4));
                            const double rz = static_cast<double>(be_f32(r_apos + (a * 3 + 2) * 4));
                            for (int b = 0; b < cnt; ++b) {
                                if (be32(c_ast + b * 4) != rs) continue;
                                const double cx = static_cast<double>(be_f32(c_apos + (b * 3 + 0) * 4));
                                const double cy = static_cast<double>(be_f32(c_apos + (b * 3 + 1) * 4));
                                const double cz = static_cast<double>(be_f32(c_apos + (b * 3 + 2) * 4));
                                if (std::isfinite(cx) && std::isfinite(cy) && std::isfinite(cz) &&
                                    std::abs(rx - cx) <= actor_tol &&
                                    std::abs(ry - cy) <= actor_tol &&
                                    std::abs(rz - cz) <= actor_tol) {
                                    adj[static_cast<size_t>(a)].push_back(b);
                                }
                            }
                        }
                        std::fill(match_b, match_b + cnt, -1);
                        for (int a : near_idx) {
                            std::memset(seen, 0, static_cast<size_t>(cnt));
                            if (!kuhn_augment(a, adj, match_b, seen)) {
                                actor_miss = true;
                                break;
                            }
                        }
                    }
                }
            }
        }
        if (actor_miss) {
            frame_failed = true;
        }
        if (frame_failed) {
            ++failed_frames;
            if (first_fail_frame < 0) first_fail_frame = i;
        }
        double fscore = 0.0;
        if (frame_exact_ok && std::isfinite(max_excess_ratio)) {
            if (max_excess_ratio <= 1.0) {
                fscore = 1.0;
            } else {
                double r2 = max_excess_ratio * max_excess_ratio;
                fscore = 1.0 / (1.0 + r2 * r2);
            }
            if (actor_miss) fscore *= 0.5;
        }
        score_sum += fscore;
    }

    *out_pass = (first_fail_frame < 0) ? 1 : 0;
    *out_failed_frames = failed_frames;
    *out_first_fail_frame = first_fail_frame;
    *out_gameplay_score = std::round((score_sum / static_cast<double>(frames)) * 1e6) / 1e6;
    *out_max_pos_drift = std::round(worst_drift * 1e4) / 1e4;
    return 0;
}

// Direct binary scan of 32-bit big-endian MIPS ELF executable PROGBITS sections
// for `lui $rt, <imm16>` and MIPS trap instructions (teq/tne/tlt/tltu/tge/tgeu
// + immediate variants), replacing two slow `mips64-elf-objdump -d` passes.
extern "C" int scan_elf_mips_words(
    const char* elf_path,
    uint32_t lui_imm16,
    int* out_lui_hits,
    int* out_trap_hits
) {
    if (!elf_path || !out_lui_hits || !out_trap_hits) return 1;
    std::ifstream f(elf_path, std::ios::binary | std::ios::ate);
    if (!f) return 2;
    std::streamsize sz = f.tellg();
    if (sz < 52) return 3;
    f.seekg(0, std::ios::beg);
    std::vector<uint8_t> buf(static_cast<size_t>(sz));
    if (!f.read(reinterpret_cast<char*>(buf.data()), sz)) return 4;

    const uint8_t* d = buf.data();
    // Require 32-bit (ELFCLASS32 = 1) big-endian (ELFDATA2MSB = 2) MIPS (EM_MIPS = 8) ELF.
    if (d[0] != 0x7f || d[1] != 'E' || d[2] != 'L' || d[3] != 'F') return 5;
    if (d[4] != 1 || d[5] != 2) return 6;
    if (be16(d + 18) != 8) return 7;

    const uint32_t shoff = be32(d + 32);
    const uint16_t shentsize = be16(d + 46);
    const uint16_t shnum = be16(d + 48);
    if (shoff == 0 || shentsize < 40 || shnum == 0) return 8;
    if (static_cast<uint64_t>(shoff) + static_cast<uint64_t>(shentsize) * shnum > buf.size()) return 9;

    const uint32_t target_lui = 0x3c000000u | (lui_imm16 & 0xffffu);
    int lui_hits = 0;
    int trap_hits = 0;

    for (uint16_t s = 0; s < shnum; ++s) {
        const uint8_t* sh = d + shoff + static_cast<size_t>(s) * shentsize;
        const uint32_t sh_type = be32(sh + 4);
        const uint32_t sh_flags = be32(sh + 8);
        const uint32_t sh_offset = be32(sh + 16);
        const uint32_t sh_size = be32(sh + 20);
        // SHT_PROGBITS (1) with SHF_EXECINSTR (0x4)
        if (sh_type != 1u || (sh_flags & 0x4u) == 0u || sh_size < 4u) continue;
        if (static_cast<uint64_t>(sh_offset) + sh_size > buf.size()) return 10;
        const uint32_t n_words = sh_size >> 2;
        const uint8_t* p = d + sh_offset;
        for (uint32_t i = 0; i < n_words; ++i, p += 4) {
            const uint32_t insn = be32(p);
            if ((insn & 0xffe0ffffu) == target_lui && ((insn >> 16) & 0x1fu) != 0u) {
                ++lui_hits;
            }
            const uint32_t op = insn >> 26;
            if (op == 0u) {
                const uint32_t fn = insn & 0x3fu;
                if (fn == 0x30u || fn == 0x31u || fn == 0x32u || fn == 0x33u || fn == 0x34u || fn == 0x36u) {
                    ++trap_hits;
                }
            } else if (op == 1u) {
                const uint32_t rt = (insn >> 16) & 0x1fu;
                if (rt == 0x08u || rt == 0x09u || rt == 0x0au || rt == 0x0bu || rt == 0x0cu || rt == 0x0eu) {
                    ++trap_hits;
                }
            }
        }
    }

    *out_lui_hits = lui_hits;
    *out_trap_hits = trap_hits;
    return 0;
}
