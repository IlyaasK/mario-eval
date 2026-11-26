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
    //    all frames minimizing (failed_frames, worst_frac, r).
    int best_r = 0;
    double best_worst_frac = 2.0;
    double best_mean_frac = 1.0;
    int best_worst_frame = -1;
    int best_failed = frames + 1;
    int best_variant = 0;

    for (int r = 0; r < n_ref_paths; ++r) {
        const size_t row = static_cast<size_t>(r) * n_frames;
        double r_worst_frac = 0.0;
        double r_sum_frac = 0.0;
        int r_worst_frame = -1;
        int r_failed = 0;
        int r_variant = 0;
        for (int i = 0; i < frames; ++i) {
            const size_t fi = static_cast<size_t>(i);
            const double f = frac_mat[row + fi];
            r_sum_frac += f;
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
        if (r_failed < best_failed ||
            (r_failed == best_failed && r_worst_frac < best_worst_frac)) {
            best_r = r;
            best_worst_frac = r_worst_frac;
            best_mean_frac = r_sum_frac / static_cast<double>(frames);
            best_worst_frame = r_worst_frame;
            best_failed = r_failed;
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
