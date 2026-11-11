/*
 * Native C++20 high-speed routing core for PerfBoardMaker AutoConnect.
 * Implements exact solder A*, orthogonal/diagonal jumper clearance & crossing rules,
 * multi-hop alternating hybrid pathfinding, multi-threaded group ordering search
 * with conflict-directed backjumping and PathFinder rip-up-and-reroute.
 */
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <numeric>
#include <queue>
#include <random>
#include <thread>
#include <vector>

#if defined(_WIN32)
#define RC_EXPORT extern "C" __declspec(dllexport)
#else
#define RC_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {

constexpr int64_t INF_COST = (1LL << 58);
constexpr int DIRS[4][2] = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}};
constexpr double PIN_CLEARANCE_MIN = 0.85;

struct Pt {
    int32_t x = 0;
    int32_t y = 0;
    bool operator==(const Pt& o) const { return x == o.x && y == o.y; }
    bool operator!=(const Pt& o) const { return x != o.x || y != o.y; }
};

struct Seg {
    int32_t x1 = 0, y1 = 0, x2 = 0, y2 = 0;
};

struct JumperData {
    Pt start;
    Pt end;
    std::vector<Pt> bends;
    int32_t min_x = 0, max_x = 0, min_y = 0, max_y = 0;

    void update_bbox() {
        min_x = std::min(start.x, end.x);
        max_x = std::max(start.x, end.x);
        min_y = std::min(start.y, end.y);
        max_y = std::max(start.y, end.y);
        for (const auto& b : bends) {
            min_x = std::min(min_x, b.x);
            max_x = std::max(max_x, b.x);
            min_y = std::min(min_y, b.y);
            max_y = std::max(max_y, b.y);
        }
    }
};

struct Settings {
    int64_t cost_solder_move = 10;
    int64_t cost_solder_turn = 15;
    int64_t cost_jumper_start = 50;
    int64_t cost_jumper_move = 2;
    int64_t cost_jumper_turn = 30;
    int64_t cost_jumper_cross = 100;
};

struct PQNode {
    int64_t f;
    int64_t g;
    int32_t state;
    bool operator>(const PQNode& o) const {
        if (f != o.f) return f > o.f;
        return g > o.g;
    }
};

struct TermPQNode {
    int64_t g;
    int32_t steps;
    int32_t state;
    bool operator>(const TermPQNode& o) const {
        if (g != o.g) return g > o.g;
        return steps > o.steps;
    }
};

struct Terminal {
    int32_t hole_idx;
    int64_t extra_cost;
    std::vector<std::pair<int32_t, int32_t>> solders;
};

struct GroupSpec {
    int32_t id = 0;
    std::vector<std::vector<int32_t>> targets;
    std::vector<int32_t> all_holes;
};

struct GroupResult {
    bool success = false;
    int32_t group_id = 0;
    int64_t cost = 0;
    std::vector<std::pair<int32_t, int32_t>> solders;
    std::vector<JumperData> jumpers;
};

struct FullSolution {
    bool success = false;
    int64_t total_cost = INF_COST;
    std::vector<GroupResult> group_results;
};

struct ShortOffset {
    int8_t dx;
    int8_t dy;
    int32_t dist_euc_int;
};

const std::vector<ShortOffset>& get_short_offsets() {
    static const std::vector<ShortOffset> offsets = []() {
        std::vector<ShortOffset> res;
        for (int dx = -5; dx <= 5; ++dx) {
            for (int dy = -5; dy <= 5; ++dy) {
                if (dx == 0 && dy == 0) continue;
                int d2 = dx * dx + dy * dy;
                if (d2 <= 25) {
                    res.push_back({static_cast<int8_t>(dx), static_cast<int8_t>(dy),
                                   static_cast<int32_t>(std::hypot(double(dx), double(dy)))});
                }
            }
        }
        return res;
    }();
    return offsets;
}

inline int64_t ccw(Pt a, Pt b, Pt c) {
    return static_cast<int64_t>(c.y - a.y) * (b.x - a.x) -
           static_cast<int64_t>(b.y - a.y) * (c.x - a.x);
}

inline bool pt_strictly_on_open_segment(Pt pt, Pt p1, Pt p2) {
    if (pt == p1 || pt == p2) return false;
    int64_t lhs = static_cast<int64_t>(pt.y - p1.y) * (p2.x - p1.x);
    int64_t rhs = static_cast<int64_t>(p2.y - p1.y) * (pt.x - p1.x);
    if (lhs != rhs) return false;
    int32_t min_x = std::min(p1.x, p2.x), max_x = std::max(p1.x, p2.x);
    int32_t min_y = std::min(p1.y, p2.y), max_y = std::max(p1.y, p2.y);
    return min_x <= pt.x && pt.x <= max_x && min_y <= pt.y && pt.y <= max_y;
}

inline bool is_collinear_seg(Pt sa1, Pt sa2, Pt sb1, Pt sb2) {
    int64_t dxa = sa2.x - sa1.x, dya = sa2.y - sa1.y;
    int64_t dxb = sb2.x - sb1.x, dyb = sb2.y - sb1.y;
    return dxa * dyb == dya * dxb;
}

inline double point_to_segment_dist(double px, double py, double x1, double y1, double x2, double y2) {
    double dx = x2 - x1;
    double dy = y2 - y1;
    double len_sq = dx * dx + dy * dy;
    if (len_sq == 0.0) return std::hypot(px - x1, py - y1);
    double t = ((px - x1) * dx + (py - y1) * dy) / len_sq;
    if (t < 0.0) t = 0.0;
    else if (t > 1.0) t = 1.0;
    double proj_x = x1 + t * dx;
    double proj_y = y1 + t * dy;
    return std::hypot(px - proj_x, py - proj_y);
}

inline bool is_straight_clear_of_pins(
    Pt p1, Pt p2, int32_t cols, int32_t rows, const uint8_t* pin_grid
) {
    if (p1 == p2) {
        return pin_grid[p1.y * cols + p1.x] == 0;
    }
    if (p1.y == p2.y) {
        int32_t r_off = p1.y * cols;
        int32_t c0 = std::min(p1.x, p2.x);
        int32_t c1 = std::max(p1.x, p2.x);
        for (int32_t c = c0; c <= c1; ++c) {
            if (pin_grid[r_off + c]) return false;
        }
        return true;
    }
    if (p1.x == p2.x) {
        int32_t c = p1.x;
        int32_t r0 = std::min(p1.y, p2.y);
        int32_t r1 = std::max(p1.y, p2.y);
        for (int32_t r = r0; r <= r1; ++r) {
            if (pin_grid[r * cols + c]) return false;
        }
        return true;
    }
    int32_t bx0 = std::max<int32_t>(0, std::min(p1.x, p2.x) - 1);
    int32_t bx1 = std::min<int32_t>(cols - 1, std::max(p1.x, p2.x) + 1);
    int32_t by0 = std::max<int32_t>(0, std::min(p1.y, p2.y) - 1);
    int32_t by1 = std::min<int32_t>(rows - 1, std::max(p1.y, p2.y) + 1);
    double x1 = p1.x, y1 = p1.y, x2 = p2.x, y2 = p2.y;
    for (int32_t r = by0; r <= by1; ++r) {
        int32_t row_off = r * cols;
        for (int32_t c = bx0; c <= bx1; ++c) {
            if (pin_grid[row_off + c]) {
                if (point_to_segment_dist(double(c), double(r), x1, y1, x2, y2) < PIN_CLEARANCE_MIN) {
                    return false;
                }
            }
        }
    }
    return true;
}

int64_t count_jumper_crossings(
    Pt j_start, Pt j_end, const Pt* bends, size_t n_bends,
    const std::vector<JumperData>& existing, int64_t cost_cross
) {
    if (cost_cross == 0 || existing.empty()) return 0;

    // Build candidate polyline points on stack when small
    Pt stack_pts[64];
    std::vector<Pt> heap_pts;
    Pt* cand_pts = stack_pts;
    size_t n_pts = n_bends + 2;
    if (n_pts > 64) {
        heap_pts.resize(n_pts);
        cand_pts = heap_pts.data();
    }
    cand_pts[0] = j_start;
    int32_t c_min_x = std::min(j_start.x, j_end.x);
    int32_t c_max_x = std::max(j_start.x, j_end.x);
    int32_t c_min_y = std::min(j_start.y, j_end.y);
    int32_t c_max_y = std::max(j_start.y, j_end.y);
    for (size_t i = 0; i < n_bends; ++i) {
        cand_pts[i + 1] = bends[i];
        c_min_x = std::min(c_min_x, bends[i].x);
        c_max_x = std::max(c_max_x, bends[i].x);
        c_min_y = std::min(c_min_y, bends[i].y);
        c_max_y = std::max(c_max_y, bends[i].y);
    }
    cand_pts[n_pts - 1] = j_end;
    size_t n_segs = n_pts - 1;

    int64_t half_units = 0;

    Pt o_stack_pts[64];
    std::vector<Pt> o_heap_pts;

    for (const auto& o : existing) {
        if (c_max_x < o.min_x || o.max_x < c_min_x || c_max_y < o.min_y || o.max_y < c_min_y) {
            continue;
        }
        size_t o_n_pts = o.bends.size() + 2;
        Pt* o_pts = o_stack_pts;
        if (o_n_pts > 64) {
            o_heap_pts.resize(o_n_pts);
            o_pts = o_heap_pts.data();
        }
        o_pts[0] = o.start;
        for (size_t i = 0; i < o.bends.size(); ++i) o_pts[i + 1] = o.bends[i];
        o_pts[o_n_pts - 1] = o.end;
        size_t o_n_segs = o_n_pts - 1;

        // Rule 3: cand endpoints strictly inside open segment of other
        Pt cand_eps[2] = {j_start, j_end};
        int n_cand_ep = (j_start == j_end) ? 1 : 2;
        for (int e = 0; e < n_cand_ep; ++e) {
            Pt ep = cand_eps[e];
            for (size_t j = 0; j < o_n_segs; ++j) {
                Pt s0 = o_pts[j], s1 = o_pts[j + 1];
                if (pt_strictly_on_open_segment(ep, s0, s1)) {
                    bool collinear_connected = false;
                    for (size_t i = 0; i < n_segs; ++i) {
                        if (cand_pts[i] == ep || cand_pts[i + 1] == ep) {
                            if (is_collinear_seg(cand_pts[i], cand_pts[i + 1], s0, s1)) {
                                collinear_connected = true;
                                break;
                            }
                        }
                    }
                    if (!collinear_connected) {
                        half_units += 1;
                    }
                }
            }
        }

        // Rule 3 symmetric: other endpoints strictly inside open segment of cand
        Pt o_eps[2] = {o.start, o.end};
        int n_o_ep = (o.start == o.end) ? 1 : 2;
        for (int e = 0; e < n_o_ep; ++e) {
            Pt ep = o_eps[e];
            for (size_t i = 0; i < n_segs; ++i) {
                Pt s0 = cand_pts[i], s1 = cand_pts[i + 1];
                if (pt_strictly_on_open_segment(ep, s0, s1)) {
                    bool collinear_connected = false;
                    for (size_t j = 0; j < o_n_segs; ++j) {
                        if (o_pts[j] == ep || o_pts[j + 1] == ep) {
                            if (is_collinear_seg(o_pts[j], o_pts[j + 1], s0, s1)) {
                                collinear_connected = true;
                                break;
                            }
                        }
                    }
                    if (!collinear_connected) {
                        half_units += 1;
                    }
                }
            }
        }

        // Rules 1 & 2: Segment-by-segment crossings and parallel overlaps
        for (size_t i = 0; i < n_segs; ++i) {
            Pt p1 = cand_pts[i], p2 = cand_pts[i + 1];
            int32_t min1_x = std::min(p1.x, p2.x), max1_x = std::max(p1.x, p2.x);
            int32_t min1_y = std::min(p1.y, p2.y), max1_y = std::max(p1.y, p2.y);

            for (size_t j = 0; j < o_n_segs; ++j) {
                Pt p3 = o_pts[j], p4 = o_pts[j + 1];
                int32_t min2_x = std::min(p3.x, p4.x), max2_x = std::max(p3.x, p4.x);
                int32_t min2_y = std::min(p3.y, p4.y), max2_y = std::max(p3.y, p4.y);

                if (max1_x < min2_x || max2_x < min1_x || max1_y < min2_y || max2_y < min1_y) {
                    continue;
                }

                // Rule 2: Horizontal parallel overlap
                if (p1.y == p2.y && p2.y == p3.y && p3.y == p4.y) {
                    int32_t ov_min = std::max(min1_x, min2_x);
                    int32_t ov_max = std::min(max1_x, max2_x);
                    if (ov_min < ov_max) {
                        half_units += static_cast<int64_t>(ov_max - ov_min + 1) * 2;
                    }
                    continue;
                }

                // Rule 2: Vertical parallel overlap
                if (p1.x == p2.x && p2.x == p3.x && p3.x == p4.x) {
                    int32_t ov_min = std::max(min1_y, min2_y);
                    int32_t ov_max = std::min(max1_y, max2_y);
                    if (ov_min < ov_max) {
                        half_units += static_cast<int64_t>(ov_max - ov_min + 1) * 2;
                    }
                    continue;
                }

                // Rule 2: Diagonal parallel overlap
                int64_t dx1 = p2.x - p1.x, dy1 = p2.y - p1.y;
                int64_t dx2 = p4.x - p3.x, dy2 = p4.y - p3.y;
                if (dx1 * dy2 == dy1 * dx2) {
                    if ((static_cast<int64_t>(p3.y - p1.y) * dx1) ==
                        (static_cast<int64_t>(p3.x - p1.x) * dy1)) {
                        int32_t ov_min_x = std::max(min1_x, min2_x);
                        int32_t ov_max_x = std::min(max1_x, max2_x);
                        if (ov_min_x < ov_max_x) {
                            half_units += static_cast<int64_t>(ov_max_x - ov_min_x + 1) * 2;
                        }
                        continue;
                    }
                }

                // Rule 1: Proper cross point
                int64_t d1 = ccw(p3, p4, p1);
                int64_t d2 = ccw(p3, p4, p2);
                int64_t d3 = ccw(p1, p2, p3);
                int64_t d4 = ccw(p1, p2, p4);

                if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
                    ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
                    half_units += 2;
                }
            }
        }
    }

    return (half_units * cost_cross) / 2;
}

struct SolverWorkspace {
    int32_t cols = 0;
    int32_t rows = 0;
    int32_t N = 0;

    std::vector<int32_t> dist_goal;
    std::vector<int32_t> bfs_q;

    std::vector<uint8_t> start_grid;
    std::vector<uint8_t> goal_grid;
    std::vector<uint8_t> near_goal_grid;

    std::vector<int64_t> g_solder;
    std::vector<int32_t> parent_solder;

    std::vector<int64_t> g_orth;
    std::vector<int32_t> parent_orth;

    std::vector<int64_t> g_term;
    std::vector<int32_t> parent_term;
    std::vector<int64_t> best_term_cost;
    std::vector<int32_t> best_term_state;

    std::vector<int64_t> g_hybrid;
    std::vector<int32_t> hyb_prev_state;
    std::vector<uint8_t> hyb_act_type; // 1 = solder, 2 = jumper
    std::vector<int32_t> hyb_act_data; // for solder: (from_idx), for jumper: rec_idx

    std::vector<PQNode> pq_buf;
    std::vector<PQNode> orth_pq_buf;
    std::vector<TermPQNode> term_pq_buf;
    std::vector<JumperData> rec_jumpers;

    void init(int32_t c, int32_t r) {
        if (cols == c && rows == r) return;
        cols = c;
        rows = r;
        N = c * r;
        dist_goal.resize(N);
        bfs_q.resize(N);
        start_grid.resize(N);
        goal_grid.resize(N);
        near_goal_grid.resize(N);
        g_solder.resize(N * 5);
        parent_solder.resize(N * 5);
        g_orth.resize(N * 4);
        parent_orth.resize(N * 4);
        g_term.resize(N * 5);
        parent_term.resize(N * 5);
        best_term_cost.resize(N);
        best_term_state.resize(N);
    }

    void compute_dist_to_goals(const std::vector<int32_t>& goal_holes) {
        std::fill(dist_goal.begin(), dist_goal.end(), -1);
        int32_t head = 0, tail = 0;
        for (int32_t idx : goal_holes) {
            if (dist_goal[idx] == -1) {
                dist_goal[idx] = 0;
                bfs_q[tail++] = idx;
            }
        }
        while (head < tail) {
            int32_t idx = bfs_q[head++];
            int32_t d = dist_goal[idx] + 1;
            int32_t c = idx % cols;
            int32_t r = idx / cols;
            if (c + 1 < cols && dist_goal[idx + 1] == -1) {
                dist_goal[idx + 1] = d;
                bfs_q[tail++] = idx + 1;
            }
            if (c - 1 >= 0 && dist_goal[idx - 1] == -1) {
                dist_goal[idx - 1] = d;
                bfs_q[tail++] = idx - 1;
            }
            if (r + 1 < rows && dist_goal[idx + cols] == -1) {
                dist_goal[idx + cols] = d;
                bfs_q[tail++] = idx + cols;
            }
            if (r - 1 >= 0 && dist_goal[idx - cols] == -1) {
                dist_goal[idx - cols] = d;
                bfs_q[tail++] = idx - cols;
            }
        }
    }

    // Pure solder A* search
    std::pair<int64_t, std::vector<int32_t>> route_solder_path(
        const std::vector<int32_t>& starts,
        const std::vector<int32_t>& goals,
        const uint8_t* obs_grid,
        const int64_t* hole_penalty, // nullable
        const Settings& settings
    ) {
        if (starts.empty() || goals.empty()) return {INF_COST, {}};

        std::fill(start_grid.begin(), start_grid.end(), 0);
        std::fill(goal_grid.begin(), goal_grid.end(), 0);
        for (int32_t idx : starts) start_grid[idx] = 1;
        for (int32_t idx : goals) {
            goal_grid[idx] = 1;
            if (start_grid[idx]) return {0, {idx}};
        }

        compute_dist_to_goals(goals);

        std::fill(g_solder.begin(), g_solder.end(), INF_COST);
        pq_buf.clear();

        for (int32_t sc : starts) {
            int32_t st = sc * 5 + 4;
            g_solder[st] = 0;
            parent_solder[st] = -1;
            int64_t h = static_cast<int64_t>(dist_goal[sc]) * settings.cost_solder_move;
            pq_buf.push_back({h, 0, st});
        }
        std::make_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());

        int32_t best_goal_state = -1;
        int64_t best_goal_cost = INF_COST;

        while (!pq_buf.empty()) {
            std::pop_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());
            PQNode top = pq_buf.back();
            pq_buf.pop_back();

            if (top.g > g_solder[top.state]) continue;

            int32_t idx = top.state / 5;
            int32_t d = top.state % 5;

            if (goal_grid[idx]) {
                best_goal_state = top.state;
                best_goal_cost = top.g;
                break;
            }

            int32_t c = idx % cols;
            int32_t r = idx / cols;

            for (int32_t nd = 0; nd < 4; ++nd) {
                int32_t nc = c + DIRS[nd][0];
                int32_t nr = r + DIRS[nd][1];
                if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                int32_t nidx = nr * cols + nc;
                if (obs_grid[nidx]) continue;

                int64_t turn_cost = (d != 4 && nd != d) ? settings.cost_solder_turn : 0;
                int64_t pen = hole_penalty ? hole_penalty[nidx] : 0;
                int64_t new_g = top.g + settings.cost_solder_move + turn_cost + pen;
                int32_t nst = nidx * 5 + nd;

                if (new_g < g_solder[nst]) {
                    g_solder[nst] = new_g;
                    parent_solder[nst] = top.state;
                    int64_t h = static_cast<int64_t>(dist_goal[nidx]) * settings.cost_solder_move;
                    pq_buf.push_back({new_g + h, new_g, nst});
                    std::push_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());
                }
            }
        }

        if (best_goal_state == -1) return {INF_COST, {}};

        std::vector<int32_t> path;
        int32_t curr = best_goal_state;
        while (curr != -1) {
            path.push_back(curr / 5);
            curr = parent_solder[curr];
        }
        std::reverse(path.begin(), path.end());
        return {best_goal_cost, std::move(path)};
    }

    // Orthogonal 90-degree A* jumper routing around pins
    std::pair<int64_t, std::vector<Pt>> find_orthogonal_jumper_path(
        Pt start, Pt goal,
        const uint8_t* pin_grid,
        const uint8_t* obs_grid,
        const Settings& settings,
        int64_t cost_limit = INF_COST
    ) {
        if (start == goal) return {0, {}};
        std::fill(g_orth.begin(), g_orth.end(), INF_COST);
        orth_pq_buf.clear();

        int64_t h_start = static_cast<int64_t>(std::abs(goal.x - start.x) + std::abs(goal.y - start.y)) *
                          settings.cost_jumper_move;
        if (h_start >= cost_limit) return {INF_COST, {}};

        int32_t s_idx = start.y * cols + start.x;
        for (int32_t d = 0; d < 4; ++d) {
            int32_t st = s_idx * 4 + d;
            g_orth[st] = 0;
            parent_orth[st] = -1;
            orth_pq_buf.push_back({h_start, 0, st});
        }
        std::make_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());

        int32_t goal_idx = goal.y * cols + goal.x;
        int32_t best_goal_state = -1;
        int64_t best_cost = INF_COST;

        while (!orth_pq_buf.empty()) {
            std::pop_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());
            PQNode top = orth_pq_buf.back();
            orth_pq_buf.pop_back();

            if (top.f >= cost_limit) break;
            if (top.g > g_orth[top.state]) continue;

            int32_t idx = top.state / 4;
            int32_t d = top.state % 4;
            if (idx == goal_idx) {
                best_goal_state = top.state;
                best_cost = top.g;
                break;
            }

            int32_t c = idx % cols;
            int32_t r = idx / cols;

            for (int32_t nd = 0; nd < 4; ++nd) {
                if ((nd + 2) % 4 == d) continue; // No 180° turns
                int32_t nc = c + DIRS[nd][0];
                int32_t nr = r + DIRS[nd][1];
                if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                int32_t nidx = nr * cols + nc;
                if (pin_grid[nidx]) continue;

                int64_t turn_cost = (nd != d) ? settings.cost_jumper_turn : 0;
                int64_t bend_pen = (nd != d && obs_grid[idx]) ? 500 : 0;
                int64_t new_g = top.g + settings.cost_jumper_move + turn_cost + bend_pen;
                int64_t h = static_cast<int64_t>(std::abs(goal.x - nc) + std::abs(goal.y - nr)) *
                            settings.cost_jumper_move;
                if (new_g + h >= cost_limit) continue;

                int32_t nst = nidx * 4 + nd;
                if (new_g < g_orth[nst]) {
                    g_orth[nst] = new_g;
                    parent_orth[nst] = top.state;
                    orth_pq_buf.push_back({new_g + h, new_g, nst});
                    std::push_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());
                }
            }
        }

        if (best_goal_state == -1) return {INF_COST, {}};

        std::vector<Pt> path;
        int32_t curr = best_goal_state;
        while (curr != -1) {
            int32_t p_idx = curr / 4;
            path.push_back({p_idx % cols, p_idx / cols});
            curr = parent_orth[curr];
        }
        std::reverse(path.begin(), path.end());

        std::vector<Pt> bends;
        for (size_t i = 1; i + 1 < path.size(); ++i) {
            int32_t d1x = path[i].x - path[i - 1].x;
            int32_t d1y = path[i].y - path[i - 1].y;
            int32_t d2x = path[i + 1].x - path[i].x;
            int32_t d2y = path[i + 1].y - path[i].y;
            if (d1x != d2x || d1y != d2y) {
                bends.push_back(path[i]);
            }
        }
        return {best_cost, std::move(bends)};
    }

    // Multi-step solder expansion to discover valid hybrid jumper terminals
    std::vector<Terminal> get_jumper_terminals(
        const std::vector<int32_t>& group_holes,
        const uint8_t* pin_grid,
        const uint8_t* obs_grid,
        const int64_t* hole_penalty,
        const Settings& settings,
        int32_t max_depth = 6
    ) {
        std::vector<Terminal> terminals;
        std::fill(start_grid.begin(), start_grid.end(), 0); // reuse as in_group mask
        std::fill(best_term_cost.begin(), best_term_cost.end(), INF_COST);
        std::fill(best_term_state.begin(), best_term_state.end(), -1);
        std::fill(g_term.begin(), g_term.end(), INF_COST);

        for (int32_t h : group_holes) start_grid[h] = 1;

        term_pq_buf.clear();
        for (int32_t h : group_holes) {
            if (!pin_grid[h] && !obs_grid[h]) {
                best_term_cost[h] = 0;
                best_term_state[h] = -2; // zero solder
            }
            if (!obs_grid[h]) {
                int32_t st = h * 5 + 4;
                g_term[st] = 0;
                parent_term[st] = -1;
                term_pq_buf.push_back({0, 0, st});
            }
        }
        std::make_heap(term_pq_buf.begin(), term_pq_buf.end(), std::greater<TermPQNode>());

        while (!term_pq_buf.empty()) {
            std::pop_heap(term_pq_buf.begin(), term_pq_buf.end(), std::greater<TermPQNode>());
            TermPQNode top = term_pq_buf.back();
            term_pq_buf.pop_back();

            if (top.g > g_term[top.state]) continue;
            if (top.steps >= max_depth) continue;

            int32_t idx = top.state / 5;
            int32_t d = top.state % 5;
            int32_t c = idx % cols;
            int32_t r = idx / cols;

            for (int32_t nd = 0; nd < 4; ++nd) {
                int32_t nc = c + DIRS[nd][0];
                int32_t nr = r + DIRS[nd][1];
                if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                int32_t nidx = nr * cols + nc;
                if (obs_grid[nidx]) continue;
                if (pin_grid[nidx] && !start_grid[nidx]) continue;

                int64_t turn_cost = (d != 4 && nd != d) ? settings.cost_solder_turn : 0;
                int64_t pen = hole_penalty ? hole_penalty[nidx] : 0;
                int64_t new_g = top.g + settings.cost_solder_move + turn_cost + pen;
                int32_t nst = nidx * 5 + nd;

                if (new_g < g_term[nst]) {
                    g_term[nst] = new_g;
                    parent_term[nst] = top.state;
                    term_pq_buf.push_back({new_g, top.steps + 1, nst});
                    std::push_heap(term_pq_buf.begin(), term_pq_buf.end(), std::greater<TermPQNode>());

                    if (!pin_grid[nidx] && new_g < best_term_cost[nidx]) {
                        best_term_cost[nidx] = new_g;
                        best_term_state[nidx] = nst;
                    }
                }
            }
        }

        for (int32_t idx = 0; idx < N; ++idx) {
            if (best_term_cost[idx] < INF_COST) {
                Terminal t;
                t.hole_idx = idx;
                t.extra_cost = best_term_cost[idx];
                if (best_term_state[idx] >= 0) {
                    std::vector<int32_t> path;
                    int32_t curr = best_term_state[idx];
                    while (curr != -1) {
                        path.push_back(curr / 5);
                        curr = parent_term[curr];
                    }
                    std::reverse(path.begin(), path.end());
                    for (size_t i = 0; i + 1 < path.size(); ++i) {
                        t.solders.push_back({path[i], path[i + 1]});
                    }
                }
                terminals.push_back(std::move(t));
            }
        }

        std::sort(terminals.begin(), terminals.end(),
                  [](const Terminal& a, const Terminal& b) { return a.extra_cost < b.extra_cost; });
        return terminals;
    }

    // Single-jumper + hybrid solder ends search
    struct JumperSearchResult {
        int64_t cost = INF_COST;
        int32_t start_idx = 0;
        int32_t goal_idx = 0;
        std::vector<Pt> bends;
        std::vector<std::pair<int32_t, int32_t>> extra_solders;
    };

    JumperSearchResult route_jumper(
        const std::vector<Terminal>& g1_terms,
        const std::vector<Terminal>& g2_terms,
        const uint8_t* obs_grid,
        const uint8_t* pin_grid,
        const std::vector<JumperData>& existing_jumpers,
        const Settings& settings,
        int64_t initial_cost_limit = INF_COST
    ) {
        JumperSearchResult best;
        best.cost = initial_cost_limit;
        bool found_any = false;
        if (g1_terms.empty() || g2_terms.empty()) return {INF_COST, 0, 0, {}, {}};

        int64_t j_start_cost = static_cast<int64_t>(existing_jumpers.size() + 1) * settings.cost_jumper_start;

        for (const auto& t1 : g1_terms) {
            if (t1.extra_cost + g2_terms[0].extra_cost + j_start_cost >= best.cost) break;
            Pt p1{t1.hole_idx % cols, t1.hole_idx / cols};

            for (const auto& t2 : g2_terms) {
                if (t1.hole_idx == t2.hole_idx) continue;
                int64_t base_term_cost = t1.extra_cost + t2.extra_cost + j_start_cost;
                if (base_term_cost >= best.cost) break;

                Pt p2{t2.hole_idx % cols, t2.hole_idx / cols};
                int32_t dx = std::abs(p2.x - p1.x);
                int32_t dy = std::abs(p2.y - p1.y);
                int32_t dist_man = dx + dy;
                double dist_euc = std::hypot(double(dx), double(dy));

                int64_t min_move_cost = (dist_euc <= 5.0)
                    ? static_cast<int64_t>(static_cast<int32_t>(dist_euc)) * settings.cost_jumper_move
                    : static_cast<int64_t>(dist_man) * settings.cost_jumper_move;
                if (base_term_cost + min_move_cost >= best.cost) continue;

                // Option 1: Direct straight (<= 5.0)
                if (dist_euc <= 5.0 && is_straight_clear_of_pins(p1, p2, cols, rows, pin_grid)) {
                    int64_t cross_cost = count_jumper_crossings(p1, p2, nullptr, 0, existing_jumpers, settings.cost_jumper_cross);
                    int64_t cost = base_term_cost + static_cast<int64_t>(static_cast<int32_t>(dist_euc)) * settings.cost_jumper_move + cross_cost;
                    if (cost < best.cost) {
                        found_any = true;
                        best.cost = cost;
                        best.start_idx = t1.hole_idx;
                        best.goal_idx = t2.hole_idx;
                        best.bends.clear();
                        best.extra_solders = t1.solders;
                        best.extra_solders.insert(best.extra_solders.end(), t2.solders.begin(), t2.solders.end());
                    }
                }

                // Option 2: Collinear orthogonal
                if (p1.x == p2.x || p1.y == p2.y) {
                    if (is_straight_clear_of_pins(p1, p2, cols, rows, pin_grid)) {
                        int64_t cross_cost = count_jumper_crossings(p1, p2, nullptr, 0, existing_jumpers, settings.cost_jumper_cross);
                        int64_t cost = base_term_cost + static_cast<int64_t>(dist_man) * settings.cost_jumper_move + cross_cost;
                        if (cost < best.cost) {
                            found_any = true;
                            best.cost = cost;
                            best.start_idx = t1.hole_idx;
                            best.goal_idx = t2.hole_idx;
                            best.bends.clear();
                            best.extra_solders = t1.solders;
                            best.extra_solders.insert(best.extra_solders.end(), t2.solders.begin(), t2.solders.end());
                        }
                    } else {
                        auto a_res = find_orthogonal_jumper_path(p1, p2, pin_grid, obs_grid, settings, best.cost - base_term_cost);
                        if (a_res.first < INF_COST) {
                            int64_t cross_cost = count_jumper_crossings(p1, p2, a_res.second.data(), a_res.second.size(), existing_jumpers, settings.cost_jumper_cross);
                            int64_t cost = base_term_cost + a_res.first + cross_cost;
                            if (cost < best.cost) {
                                found_any = true;
                                best.cost = cost;
                                best.start_idx = t1.hole_idx;
                                best.goal_idx = t2.hole_idx;
                                best.bends = std::move(a_res.second);
                                best.extra_solders = t1.solders;
                                best.extra_solders.insert(best.extra_solders.end(), t2.solders.begin(), t2.solders.end());
                            }
                        }
                    }
                } else {
                    // Option 3: 1-bend L-route
                    Pt bend_opts[2] = {{p1.x, p2.y}, {p2.x, p1.y}};
                    bool found_l = false;
                    for (int b = 0; b < 2; ++b) {
                        Pt bend = bend_opts[b];
                        int32_t b_idx = bend.y * cols + bend.x;
                        if (pin_grid[b_idx]) continue;
                        if (!is_straight_clear_of_pins(p1, bend, cols, rows, pin_grid)) continue;
                        if (!is_straight_clear_of_pins(bend, p2, cols, rows, pin_grid)) continue;

                        found_l = true;
                        int64_t cross_cost = count_jumper_crossings(p1, p2, &bend, 1, existing_jumpers, settings.cost_jumper_cross);
                        int64_t cost = base_term_cost +
                                       static_cast<int64_t>(dist_man) * settings.cost_jumper_move +
                                       settings.cost_jumper_turn + cross_cost +
                                       (obs_grid[b_idx] ? 500 : 0);
                        if (cost < best.cost) {
                            found_any = true;
                            best.cost = cost;
                            best.start_idx = t1.hole_idx;
                            best.goal_idx = t2.hole_idx;
                            best.bends = {bend};
                            best.extra_solders = t1.solders;
                            best.extra_solders.insert(best.extra_solders.end(), t2.solders.begin(), t2.solders.end());
                        }
                    }
                    // Option 4: A* multi-bend around pins when both L-routes blocked
                    if (!found_l) {
                        auto a_res = find_orthogonal_jumper_path(p1, p2, pin_grid, obs_grid, settings, best.cost - base_term_cost);
                        if (a_res.first < INF_COST) {
                            int64_t cross_cost = count_jumper_crossings(p1, p2, a_res.second.data(), a_res.second.size(), existing_jumpers, settings.cost_jumper_cross);
                            int64_t cost = base_term_cost + a_res.first + cross_cost;
                            if (cost < best.cost) {
                                found_any = true;
                                best.cost = cost;
                                best.start_idx = t1.hole_idx;
                                best.goal_idx = t2.hole_idx;
                                best.bends = std::move(a_res.second);
                                best.extra_solders = t1.solders;
                                best.extra_solders.insert(best.extra_solders.end(), t2.solders.begin(), t2.solders.end());
                            }
                        }
                    }
                }
            }
        }
        if (!found_any) best.cost = INF_COST;
        return best;
    }

    // Full multi-hop alternating hybrid (solder -> jumper -> solder -> jumper -> solder...)
    struct MultiHopResult {
        bool success = false;
        int64_t cost = INF_COST;
        std::vector<std::pair<int32_t, int32_t>> solders;
        std::vector<JumperData> jumpers;
    };

    MultiHopResult route_multi_hop_hybrid(
        const std::vector<int32_t>& starts,
        const std::vector<int32_t>& goals,
        const uint8_t* pin_grid,
        const uint8_t* obs_grid,
        const int64_t* hole_penalty,
        const std::vector<JumperData>& existing_jumpers,
        const Settings& settings,
        int64_t cost_limit = INF_COST,
        int32_t max_jumpers = 4
    ) {
        MultiHopResult out;
        if (starts.empty() || goals.empty()) return out;

        std::fill(start_grid.begin(), start_grid.end(), 0);
        std::fill(goal_grid.begin(), goal_grid.end(), 0);
        std::fill(near_goal_grid.begin(), near_goal_grid.end(), 0);

        for (int32_t idx : starts) start_grid[idx] = 1;
        for (int32_t idx : goals) {
            goal_grid[idx] = 1;
            if (start_grid[idx]) {
                out.success = true;
                out.cost = 0;
                return out;
            }
        }

        compute_dist_to_goals(goals);

        // Quick reachability / trapped-pin check: if starts or goals are completely boxed in by obs_grid
        // such that neither can step to any non-pin hole AND no solder path reaches goal, fail in microseconds.
        auto has_solder_escape_or_goal = [&](const std::vector<int32_t>& seeds, const std::vector<uint8_t>& other_mask) -> bool {
            std::vector<uint8_t> vis(N, 0);
            int32_t h_ptr = 0, t_ptr = 0;
            for (int32_t s : seeds) {
                if (!pin_grid[s] && !obs_grid[s]) return true;
                vis[s] = 1;
                bfs_q[t_ptr++] = s;
            }
            while (h_ptr < t_ptr) {
                int32_t u = bfs_q[h_ptr++];
                if (other_mask[u]) return true;
                if (!pin_grid[u]) return true;
                int32_t c = u % cols, r = u / cols;
                for (int d = 0; d < 4; ++d) {
                    int32_t nc = c + DIRS[d][0], nr = r + DIRS[d][1];
                    if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                    int32_t v = nr * cols + nc;
                    if (vis[v] || obs_grid[v]) continue;
                    if (pin_grid[v] && !goal_grid[v] && !start_grid[v]) continue;
                    vis[v] = 1;
                    bfs_q[t_ptr++] = v;
                }
            }
            return false;
        };
        if (!has_solder_escape_or_goal(starts, goal_grid) || !has_solder_escape_or_goal(goals, start_grid)) {
            return out;
        }

        // Precompute fixed goal + near-goal landing holes once
        std::vector<int32_t> fixed_goal_landings;
        std::vector<int32_t> near_goal_slot(N, -1);
        for (int32_t idx = 0; idx < N; ++idx) {
            if (dist_goal[idx] <= 1 && !pin_grid[idx] && !obs_grid[idx]) {
                near_goal_grid[idx] = 1;
                near_goal_slot[idx] = static_cast<int32_t>(fixed_goal_landings.size());
                fixed_goal_landings.push_back(idx);
            }
        }
        if (fixed_goal_landings.size() < 2) {
            for (int32_t idx = 0; idx < N; ++idx) {
                if (dist_goal[idx] == 2 && !pin_grid[idx] && !obs_grid[idx]) {
                    near_goal_grid[idx] = 1;
                    near_goal_slot[idx] = static_cast<int32_t>(fixed_goal_landings.size());
                    fixed_goal_landings.push_back(idx);
                }
            }
        }

        // Lazy reverse-Dijkstra cache for Option D multi-bend orthogonal jumpers into fixed_goal_landings
        size_t n_gl = fixed_goal_landings.size();
        std::vector<uint8_t> rev_computed(n_gl, 0);
        std::vector<std::vector<int64_t>> rev_best_cost(n_gl);
        std::vector<std::vector<int32_t>> rev_best_arr_dir(n_gl);
        std::vector<std::vector<int32_t>> rev_parent(n_gl);

        auto get_cached_orth_path = [&](size_t slot, Pt p_from) -> std::pair<int64_t, std::vector<Pt>> {
            int32_t lidx = fixed_goal_landings[slot];
            if (!rev_computed[slot]) {
                rev_computed[slot] = 1;
                rev_best_cost[slot].assign(N, INF_COST);
                rev_best_arr_dir[slot].assign(N, -1);
                rev_parent[slot].assign(N * 4, -1);

                std::fill(g_orth.begin(), g_orth.end(), INF_COST);
                orth_pq_buf.clear();
                for (int32_t d = 0; d < 4; ++d) {
                    int32_t st = lidx * 4 + d;
                    g_orth[st] = 0;
                    orth_pq_buf.push_back({0, 0, st});
                }
                std::make_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());

                while (!orth_pq_buf.empty()) {
                    std::pop_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());
                    PQNode top = orth_pq_buf.back();
                    orth_pq_buf.pop_back();
                    if (top.g > g_orth[top.state]) continue;

                    int32_t u = top.state / 4;
                    int32_t d = top.state % 4;
                    if (top.g < rev_best_cost[slot][u]) {
                        rev_best_cost[slot][u] = top.g;
                        rev_best_arr_dir[slot][u] = top.state;
                    }

                    int32_t uc = u % cols, ur = u / cols;
                    for (int32_t nd = 0; nd < 4; ++nd) {
                        if ((nd + 2) % 4 == d) continue;
                        int32_t nc = uc + DIRS[nd][0], nr = ur + DIRS[nd][1];
                        if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                        int32_t nidx = nr * cols + nc;
                        if (pin_grid[nidx]) continue;

                        int64_t turn_cost = (nd != d) ? settings.cost_jumper_turn : 0;
                        int64_t bend_pen = (nd != d && obs_grid[u]) ? 500 : 0;
                        int64_t new_g = top.g + settings.cost_jumper_move + turn_cost + bend_pen;
                        int32_t nst = nidx * 4 + nd;
                        if (new_g < g_orth[nst]) {
                            g_orth[nst] = new_g;
                            rev_parent[slot][nst] = top.state;
                            orth_pq_buf.push_back({new_g, new_g, nst});
                            std::push_heap(orth_pq_buf.begin(), orth_pq_buf.end(), std::greater<PQNode>());
                        }
                    }
                }
            }

            int32_t fidx = p_from.y * cols + p_from.x;
            int64_t c_val = rev_best_cost[slot][fidx];
            if (c_val >= INF_COST) return {INF_COST, {}};

            std::vector<Pt> path;
            int32_t curr = rev_best_arr_dir[slot][fidx];
            while (curr != -1) {
                int32_t pidx = curr / 4;
                path.push_back({pidx % cols, pidx / cols});
                curr = rev_parent[slot][curr];
            }
            std::vector<Pt> bends;
            for (size_t k = 1; k + 1 < path.size(); ++k) {
                int32_t d1x = path[k].x - path[k - 1].x, d1y = path[k].y - path[k - 1].y;
                int32_t d2x = path[k + 1].x - path[k].x, d2y = path[k + 1].y - path[k].y;
                if (d1x != d2x || d1y != d2y) bends.push_back(path[k]);
            }
            return {c_val, std::move(bends)};
        };

        int32_t num_layers = max_jumpers + 1;
        int32_t states_per_layer = N * 5;
        int32_t total_states = states_per_layer * num_layers;

        if (static_cast<int32_t>(g_hybrid.size()) < total_states) {
            g_hybrid.resize(total_states);
            hyb_prev_state.resize(total_states);
            hyb_act_type.resize(total_states);
            hyb_act_data.resize(total_states);
        }
        std::fill_n(g_hybrid.begin(), total_states, INF_COST);
        rec_jumpers.clear();
        pq_buf.clear();

        int64_t min_move = std::min(settings.cost_solder_move, settings.cost_jumper_move);
        auto calc_h = [&](int32_t idx, int32_t j_used) -> int64_t {
            int32_t d_m = dist_goal[idx];
            if (j_used >= max_jumpers) {
                return static_cast<int64_t>(d_m) * settings.cost_solder_move;
            }
            // Diagonal <=5.0 moves cover up to 2 Manhattan units per move cost
            return static_cast<int64_t>(d_m / 2) * min_move;
        };

        for (int32_t sc : starts) {
            int32_t st = sc * 5 + 4;
            g_hybrid[st] = 0;
            hyb_prev_state[st] = -1;
            hyb_act_type[st] = 0;
            pq_buf.push_back({calc_h(sc, 0), 0, st});
        }
        std::make_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());

        int64_t existing_j_count = static_cast<int64_t>(existing_jumpers.size());
        const auto& short_offsets = get_short_offsets();
        std::vector<int32_t> landings;
        landings.reserve(128);

        int32_t best_goal_state = -1;
        int64_t best_cost = cost_limit;

        while (!pq_buf.empty()) {
            std::pop_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());
            PQNode top = pq_buf.back();
            pq_buf.pop_back();

            if (top.f >= best_cost) break;
            if (top.g > g_hybrid[top.state]) continue;

            int32_t j_used = top.state / states_per_layer;
            int32_t rem = top.state % states_per_layer;
            int32_t idx = rem / 5;
            int32_t d = rem % 5;

            if (goal_grid[idx]) {
                best_goal_state = top.state;
                best_cost = top.g;
                break;
            }

            int32_t c = idx % cols;
            int32_t r = idx / cols;

            // 1. Solder Move along bottom layer
            for (int32_t nd = 0; nd < 4; ++nd) {
                int32_t nc = c + DIRS[nd][0];
                int32_t nr = r + DIRS[nd][1];
                if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                int32_t nidx = nr * cols + nc;
                if (obs_grid[nidx]) continue;
                if (pin_grid[nidx] && !goal_grid[nidx] && !start_grid[nidx]) continue;

                int64_t turn_cost = (d != 4 && nd != d) ? settings.cost_solder_turn : 0;
                int64_t pen = hole_penalty ? hole_penalty[nidx] : 0;
                int64_t new_g = top.g + settings.cost_solder_move + turn_cost + pen;
                int64_t nh = calc_h(nidx, j_used);
                if (new_g + nh >= best_cost) continue;

                int32_t nst = j_used * states_per_layer + nidx * 5 + nd;
                if (new_g < g_hybrid[nst]) {
                    g_hybrid[nst] = new_g;
                    hyb_prev_state[nst] = top.state;
                    hyb_act_type[nst] = 1;
                    hyb_act_data[nst] = idx;
                    pq_buf.push_back({new_g + nh, new_g, nst});
                    std::push_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());
                }
            }

            // 2. Jumper Hop along top layer
            if (!pin_grid[idx] && j_used < max_jumpers) {
                int64_t j_mult = existing_j_count + j_used + 1;
                int64_t j_start_cost = j_mult * settings.cost_jumper_start;
                if (top.g + j_start_cost >= best_cost) continue;

                landings.clear();
                // 2a. Fixed near-goal landings
                for (int32_t g_l : fixed_goal_landings) landings.push_back(g_l);

                // 2b. Obstacle-clearing cardinal hops
                for (int32_t ld = 0; ld < 4; ++ld) {
                    bool hit_obs = false;
                    for (int32_t step = 1; step < 20; ++step) {
                        int32_t nc = c + DIRS[ld][0] * step;
                        int32_t nr = r + DIRS[ld][1] * step;
                        if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) break;
                        int32_t nidx = nr * cols + nc;
                        if (obs_grid[nidx] || pin_grid[nidx]) {
                            hit_obs = true;
                        } else if (hit_obs) {
                            landings.push_back(nidx);
                            break;
                        }
                    }
                }

                // 2c. Short hops <= 5 units towards goal
                int32_t cur_d = dist_goal[idx];
                for (const auto& off : short_offsets) {
                    int32_t nc = c + off.dx;
                    int32_t nr = r + off.dy;
                    if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                    int32_t nidx = nr * cols + nc;
                    if (!obs_grid[nidx] && !pin_grid[nidx] && dist_goal[nidx] < cur_d) {
                        landings.push_back(nidx);
                    }
                }

                // Deduplicate landings cleanly
                std::sort(landings.begin(), landings.end());
                landings.erase(std::unique(landings.begin(), landings.end()), landings.end());

                Pt p_from{c, r};
                for (int32_t lidx : landings) {
                    if (lidx == idx) continue;
                    Pt p_to{lidx % cols, lidx / cols};

                    int32_t dx = std::abs(p_to.x - c);
                    int32_t dy = std::abs(p_to.y - r);
                    int32_t dist_man = dx + dy;
                    double dist_euc = std::hypot(double(dx), double(dy));

                    int64_t lb_h = calc_h(lidx, j_used + 1);
                    int64_t lb_move = (dist_euc <= 5.0)
                        ? static_cast<int64_t>(static_cast<int32_t>(dist_euc)) * settings.cost_jumper_move
                        : static_cast<int64_t>(dist_man) * settings.cost_jumper_move;
                    if (top.g + j_start_cost + lb_move + lb_h >= best_cost) continue;

                    bool j_valid = false;
                    int64_t j_move_cost = 0;
                    Pt l_bend;
                    bool has_l_bend = false;
                    std::vector<Pt> orth_bends;

                    // Option A: Straight <= 5.0
                    if (dist_euc <= 5.0 && is_straight_clear_of_pins(p_from, p_to, cols, rows, pin_grid)) {
                        j_valid = true;
                        j_move_cost = static_cast<int64_t>(static_cast<int32_t>(dist_euc)) * settings.cost_jumper_move;
                    }
                    // Option B: Collinear
                    else if (c == p_to.x || r == p_to.y) {
                        if (is_straight_clear_of_pins(p_from, p_to, cols, rows, pin_grid)) {
                            j_valid = true;
                            j_move_cost = static_cast<int64_t>(dist_man) * settings.cost_jumper_move;
                        } else if (near_goal_slot[lidx] >= 0) {
                            auto a_res = get_cached_orth_path(static_cast<size_t>(near_goal_slot[lidx]), p_from);
                            if (a_res.first < INF_COST) {
                                j_valid = true;
                                j_move_cost = a_res.first;
                                orth_bends = std::move(a_res.second);
                            }
                        }
                    }
                    // Option C: 1-bend L-route
                    else {
                        Pt cand_bends[2] = {{c, p_to.y}, {p_to.x, r}};
                        int64_t best_l_move = INF_COST;
                        for (int b = 0; b < 2; ++b) {
                            Pt bd = cand_bends[b];
                            int32_t b_idx = bd.y * cols + bd.x;
                            if (pin_grid[b_idx]) continue;
                            if (!is_straight_clear_of_pins(p_from, bd, cols, rows, pin_grid)) continue;
                            if (!is_straight_clear_of_pins(bd, p_to, cols, rows, pin_grid)) continue;
                            int64_t m_c = static_cast<int64_t>(dist_man) * settings.cost_jumper_move +
                                          settings.cost_jumper_turn +
                                          (obs_grid[b_idx] ? 500 : 0);
                            if (m_c < best_l_move) {
                                best_l_move = m_c;
                                l_bend = bd;
                                has_l_bend = true;
                            }
                        }
                        if (has_l_bend) {
                            j_valid = true;
                            j_move_cost = best_l_move;
                        } else if (near_goal_slot[lidx] >= 0) {
                            auto a_res = get_cached_orth_path(static_cast<size_t>(near_goal_slot[lidx]), p_from);
                            if (a_res.first < INF_COST) {
                                j_valid = true;
                                j_move_cost = a_res.first;
                                orth_bends = std::move(a_res.second);
                            }
                        }
                    }

                    if (!j_valid) continue;

                    const Pt* b_ptr = nullptr;
                    size_t b_cnt = 0;
                    if (!orth_bends.empty()) {
                        b_ptr = orth_bends.data();
                        b_cnt = orth_bends.size();
                    } else if (has_l_bend) {
                        b_ptr = &l_bend;
                        b_cnt = 1;
                    }

                    int64_t cross_cost = count_jumper_crossings(p_from, p_to, b_ptr, b_cnt, existing_jumpers, settings.cost_jumper_cross);
                    int64_t pen = hole_penalty ? hole_penalty[lidx] : 0;
                    int64_t new_g = top.g + j_start_cost + j_move_cost + cross_cost + pen;
                    if (new_g + lb_h >= best_cost) continue;

                    int32_t nst = (j_used + 1) * states_per_layer + lidx * 5 + 4;
                    if (new_g < g_hybrid[nst]) {
                        g_hybrid[nst] = new_g;
                        hyb_prev_state[nst] = top.state;
                        hyb_act_type[nst] = 2;
                        int32_t rec_id = static_cast<int32_t>(rec_jumpers.size());
                        JumperData jd;
                        jd.start = p_from;
                        jd.end = p_to;
                        if (b_cnt > 0) jd.bends.assign(b_ptr, b_ptr + b_cnt);
                        jd.update_bbox();
                        rec_jumpers.push_back(std::move(jd));
                        hyb_act_data[nst] = rec_id;

                        pq_buf.push_back({new_g + lb_h, new_g, nst});
                        std::push_heap(pq_buf.begin(), pq_buf.end(), std::greater<PQNode>());
                    }
                }
            }
        }

        if (best_goal_state == -1) return out;

        out.success = true;
        out.cost = best_cost;
        int32_t curr = best_goal_state;
        while (curr != -1 && hyb_act_type[curr] != 0) {
            uint8_t act = hyb_act_type[curr];
            if (act == 1) {
                int32_t to_idx = (curr % states_per_layer) / 5;
                int32_t from_idx = hyb_act_data[curr];
                out.solders.push_back({from_idx, to_idx});
            } else if (act == 2) {
                out.jumpers.push_back(rec_jumpers[hyb_act_data[curr]]);
            }
            curr = hyb_prev_state[curr];
        }
        std::reverse(out.solders.begin(), out.solders.end());
        std::reverse(out.jumpers.begin(), out.jumpers.end());
        return out;
    }

    // MST connector for a single group of 2+ targets
    GroupResult route_single_group(
        const GroupSpec& group,
        const uint8_t* obs_grid,
        const uint8_t* pin_grid,
        const int64_t* hole_penalty,
        std::vector<JumperData>& active_jumpers,
        const Settings& settings
    ) {
        GroupResult res;
        res.group_id = group.id;
        if (group.targets.size() < 2) return res;

        // Merge already-overlapping targets
        std::vector<std::vector<int32_t>> subgroups = group.targets;
        std::vector<std::vector<int32_t>> merged;
        std::vector<uint8_t> tmp_mark(N, 0);

        while (!subgroups.empty()) {
            std::vector<int32_t> first = std::move(subgroups.front());
            subgroups.erase(subgroups.begin());
            bool changed = true;
            while (changed) {
                changed = false;
                std::fill(tmp_mark.begin(), tmp_mark.end(), 0);
                for (int32_t h : first) tmp_mark[h] = 1;
                for (int i = static_cast<int>(subgroups.size()) - 1; i >= 0; --i) {
                    bool overlap = false;
                    for (int32_t h : subgroups[i]) {
                        if (tmp_mark[h]) {
                            overlap = true;
                            break;
                        }
                    }
                    if (overlap) {
                        first.insert(first.end(), subgroups[i].begin(), subgroups[i].end());
                        subgroups.erase(subgroups.begin() + i);
                        changed = true;
                    }
                }
            }
            std::sort(first.begin(), first.end());
            first.erase(std::unique(first.begin(), first.end()), first.end());
            merged.push_back(std::move(first));
        }

        if (merged.size() <= 1) {
            res.success = true;
            res.cost = 0;
            return res;
        }

        while (merged.size() > 1) {
            int64_t best_link_cost = INF_COST;
            int best_i = -1, best_j = -1;
            int best_kind = 0; // 1=solder, 2=jumper, 3=multihop
            std::vector<int32_t> best_s_path;
            JumperSearchResult best_j_res;
            MultiHopResult best_m_res;

            // Precompute terminals per subgroup when needed
            std::vector<std::vector<Terminal>> cached_terms(merged.size());
            std::vector<uint8_t> has_terms(merged.size(), 0);

            for (int i = 0; i < static_cast<int>(merged.size()); ++i) {
                for (int j = i + 1; j < static_cast<int>(merged.size()); ++j) {
                    const auto& g1 = merged[i];
                    const auto& g2 = merged[j];

                    // 1. Solder path
                    auto s_res = route_solder_path(g1, g2, obs_grid, hole_penalty, settings);
                    int64_t cand_cost = INF_COST;
                    int cand_kind = 0;

                    if (s_res.first < cand_cost) {
                        cand_cost = s_res.first;
                        cand_kind = 1;
                    }

                    // 2. 1-Jumper Hybrid (pruned against cand_cost)
                    if (!has_terms[i]) {
                        cached_terms[i] = get_jumper_terminals(g1, pin_grid, obs_grid, hole_penalty, settings, 6);
                        has_terms[i] = 1;
                    }
                    if (!has_terms[j]) {
                        cached_terms[j] = get_jumper_terminals(g2, pin_grid, obs_grid, hole_penalty, settings, 6);
                        has_terms[j] = 1;
                    }
                    auto j_res = route_jumper(cached_terms[i], cached_terms[j], obs_grid, pin_grid, active_jumpers, settings, cand_cost);
                    if (j_res.cost < cand_cost) {
                        cand_cost = j_res.cost;
                        cand_kind = 2;
                    }

                    // 3. Multi-hop alternating hybrid (pruned strictly against cand_cost)
                    auto m_res = route_multi_hop_hybrid(g1, g2, pin_grid, obs_grid, hole_penalty, active_jumpers, settings, cand_cost, 4);
                    if (m_res.success && m_res.cost < cand_cost) {
                        cand_cost = m_res.cost;
                        cand_kind = 3;
                    }

                    if (cand_cost < best_link_cost) {
                        best_link_cost = cand_cost;
                        best_i = i;
                        best_j = j;
                        best_kind = cand_kind;
                        if (cand_kind == 1) best_s_path = std::move(s_res.second);
                        else if (cand_kind == 2) best_j_res = std::move(j_res);
                        else if (cand_kind == 3) best_m_res = std::move(m_res);
                    }
                }
            }

            if (best_kind == 0 || best_link_cost >= INF_COST) {
                res.success = false;
                return res;
            }

            auto& g1 = merged[best_i];
            auto g2 = std::move(merged[best_j]);
            merged.erase(merged.begin() + best_j);
            g1.insert(g1.end(), g2.begin(), g2.end());

            if (best_kind == 1) {
                for (size_t k = 0; k + 1 < best_s_path.size(); ++k) {
                    res.solders.push_back({best_s_path[k], best_s_path[k + 1]});
                    g1.push_back(best_s_path[k]);
                    g1.push_back(best_s_path[k + 1]);
                }
            } else if (best_kind == 2) {
                for (const auto& seg : best_j_res.extra_solders) {
                    res.solders.push_back(seg);
                    g1.push_back(seg.first);
                    g1.push_back(seg.second);
                }
                JumperData jd;
                jd.start = {best_j_res.start_idx % cols, best_j_res.start_idx / cols};
                jd.end = {best_j_res.goal_idx % cols, best_j_res.goal_idx / cols};
                jd.bends = std::move(best_j_res.bends);
                jd.update_bbox();
                res.jumpers.push_back(jd);
                active_jumpers.push_back(jd);
                g1.push_back(best_j_res.start_idx);
                g1.push_back(best_j_res.goal_idx);
            } else {
                for (const auto& seg : best_m_res.solders) {
                    res.solders.push_back(seg);
                    g1.push_back(seg.first);
                    g1.push_back(seg.second);
                }
                for (const auto& jd : best_m_res.jumpers) {
                    res.jumpers.push_back(jd);
                    active_jumpers.push_back(jd);
                    g1.push_back(jd.start.y * cols + jd.start.x);
                    g1.push_back(jd.end.y * cols + jd.end.x);
                }
            }
            std::sort(g1.begin(), g1.end());
            g1.erase(std::unique(g1.begin(), g1.end()), g1.end());
            res.cost += best_link_cost;
        }

        res.success = true;
        return res;
    }
};

// Marks single-exit frontier holes of unrouted targets so earlier nets never entomb later pins
void build_group_obstacles(
    int cols, int rows, int N,
    int32_t current_order_pos,
    const std::vector<int32_t>& perm,
    const std::vector<GroupSpec>& groups,
    const uint8_t* base_obs,
    const uint8_t* pin_grid,
    const std::vector<uint8_t>& placed_holes,
    bool protect_forced_exits,
    std::vector<uint8_t>& out_obs,
    std::vector<uint8_t>& cur_group_holes
) {
    out_obs.assign(base_obs, base_obs + N);
    std::fill(cur_group_holes.begin(), cur_group_holes.end(), 0);

    const auto& cur_g = groups[perm[current_order_pos]];
    for (int32_t h : cur_g.all_holes) {
        cur_group_holes[h] = 1;
    }
    for (size_t idx = 0; idx < static_cast<size_t>(N); ++idx) {
        if (placed_holes[idx]) out_obs[idx] = 1;
    }
    for (size_t k = 0; k < perm.size(); ++k) {
        if (static_cast<int32_t>(k) == current_order_pos) continue;
        for (int32_t h : groups[perm[k]].all_holes) {
            out_obs[h] = 1;
        }
    }
    // Own target holes are allowed
    for (int32_t h : cur_g.all_holes) {
        out_obs[h] = 0;
    }

    if (!protect_forced_exits) return;

    // For every STILL-UNROUTED group later in perm, protect targets with a single free orthogonal escape hole
    std::vector<int32_t> exits;
    exits.reserve(8);
    for (size_t k = static_cast<size_t>(current_order_pos) + 1; k < perm.size(); ++k) {
        const auto& fut_g = groups[perm[k]];
        for (const auto& targ : fut_g.targets) {
            if (targ.empty()) continue;
            bool all_pins = true;
            for (int32_t h : targ) {
                if (!pin_grid[h]) {
                    all_pins = false;
                    break;
                }
            }
            if (!all_pins) continue;
            exits.clear();
            for (int32_t h : targ) {
                int32_t c = h % cols;
                int32_t r = h / cols;
                for (int d = 0; d < 4; ++d) {
                    int32_t nc = c + DIRS[d][0];
                    int32_t nr = r + DIRS[d][1];
                    if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
                    int32_t nidx = nr * cols + nc;
                    // Ignore holes belonging to targ itself
                    if (std::find(targ.begin(), targ.end(), nidx) != targ.end()) continue;
                    // Neighbor is open if not already blocked (treating other groups' holes as blocked unless same target)
                    if (!out_obs[nidx]) {
                        exits.push_back(nidx);
                    }
                }
            }
            std::sort(exits.begin(), exits.end());
            exits.erase(std::unique(exits.begin(), exits.end()), exits.end());
            if (exits.size() == 1) {
                int32_t forced_exit = exits[0];
                if (!cur_group_holes[forced_exit] && !pin_grid[forced_exit]) {
                    out_obs[forced_exit] = 1;
                }
            }
        }
    }
}

FullSolution run_ordering_with_backjumping(
    SolverWorkspace& ws,
    int cols, int rows, int N,
    std::vector<int32_t> perm,
    const std::vector<GroupSpec>& groups,
    const uint8_t* base_obs,
    const uint8_t* pin_grid,
    const std::vector<JumperData>& init_jumpers,
    const Settings& settings,
    bool protect_forced_exits,
    std::atomic<int64_t>& global_best_cost,
    std::atomic<int32_t>& win_count
) {
    FullSolution best;
    int32_t G = static_cast<int32_t>(perm.size());
    std::vector<uint8_t> placed_holes(N, 0);
    std::vector<uint8_t> g_obs(N, 0);
    std::vector<uint8_t> cur_holes(N, 0);
    std::vector<JumperData> active_jumpers;
    std::vector<std::vector<int32_t>> tried_perms;

    int32_t max_attempts = (G <= 4) ? 1 : std::min<int32_t>(10, G * 2);

    for (int32_t attempt = 0; attempt < max_attempts; ++attempt) {
        if (attempt >= 1 && win_count.load(std::memory_order_relaxed) > 0) {
            break;
        }
        if (std::find(tried_perms.begin(), tried_perms.end(), perm) != tried_perms.end()) {
            break;
        }
        tried_perms.push_back(perm);

        std::fill(placed_holes.begin(), placed_holes.end(), 0);
        active_jumpers = init_jumpers;

        FullSolution trial;
        trial.group_results.resize(G);
        int64_t total_cost = 0;
        int32_t failed_pos = -1;
        bool pruned = false;

        for (int32_t pos = 0; pos < G; ++pos) {
            if (total_cost >= global_best_cost.load(std::memory_order_relaxed)) {
                pruned = true;
                break;
            }
            int32_t g_idx = perm[pos];
            build_group_obstacles(
                cols, rows, N, pos, perm, groups, base_obs, pin_grid,
                placed_holes, protect_forced_exits, g_obs, cur_holes
            );
            GroupResult g_res = ws.route_single_group(
                groups[g_idx], g_obs.data(), pin_grid, nullptr, active_jumpers, settings
            );
            if (!g_res.success) {
                failed_pos = pos;
                break;
            }
            for (const auto& seg : g_res.solders) {
                placed_holes[seg.first] = 1;
                placed_holes[seg.second] = 1;
            }
            for (const auto& jd : g_res.jumpers) {
                placed_holes[jd.start.y * cols + jd.start.x] = 1;
                placed_holes[jd.end.y * cols + jd.end.x] = 1;
            }
            total_cost += g_res.cost;
            trial.group_results[pos] = std::move(g_res);
        }

        if (pruned) {
            return best;
        }

        if (failed_pos == -1) {
            trial.success = true;
            trial.total_cost = total_cost;
            win_count.fetch_add(1, std::memory_order_relaxed);
            int64_t cur = global_best_cost.load(std::memory_order_relaxed);
            while (total_cost < cur && !global_best_cost.compare_exchange_weak(cur, total_cost, std::memory_order_relaxed)) {}
            return trial;
        }

        // Conflict-directed backjump: bump failing group earlier
        int32_t failed_grp = perm[failed_pos];
        perm.erase(perm.begin() + failed_pos);
        int32_t target_pos = (attempt % 2 == 0) ? 0 : std::max(0, failed_pos / 2);
        perm.insert(perm.begin() + target_pos, failed_grp);
    }
    return best;
}

// PathFinder Iterative Rip-Up & Reroute with negotiated hole congestion penalties
FullSolution run_pathfinder_reroute(
    SolverWorkspace& ws,
    int cols, int rows, int N,
    const std::vector<int32_t>& init_perm,
    const std::vector<GroupSpec>& groups,
    const uint8_t* base_obs,
    const uint8_t* pin_grid,
    const std::vector<JumperData>& init_jumpers,
    const Settings& settings
) {
    FullSolution sol;
    int32_t G = static_cast<int32_t>(groups.size());

    // Hard obstacles shared by ALL iterations: base_obs + all_pins (except each group's own targets)
    // Non-pin empty holes are negotiable with escalating congestion penalties.
    std::vector<uint8_t> g_obs(N, 0);
    std::vector<uint8_t> cur_holes(N, 0);
    std::vector<uint8_t> all_target_holes(N, 0);
    for (const auto& g : groups) {
        for (int32_t h : g.all_holes) all_target_holes[h] = 1;
    }

    std::vector<int64_t> hist_pen(N, 0);
    std::vector<int64_t> active_pen(N, 0);
    std::vector<int32_t> hole_owner_count(N, 0);
    std::vector<std::vector<int32_t>> net_used_holes(G);
    std::vector<GroupResult> net_results(G);
    std::vector<uint8_t> net_dirty(G, 1);

    auto recompute_net_holes = [&](int gi) {
        auto& vec = net_used_holes[gi];
        vec.clear();
        for (int32_t h : groups[gi].all_holes) vec.push_back(h);
        for (const auto& seg : net_results[gi].solders) {
            vec.push_back(seg.first);
            vec.push_back(seg.second);
        }
        for (const auto& jd : net_results[gi].jumpers) {
            vec.push_back(jd.start.y * cols + jd.start.x);
            vec.push_back(jd.end.y * cols + jd.end.x);
        }
        std::sort(vec.begin(), vec.end());
        vec.erase(std::unique(vec.begin(), vec.end()), vec.end());
    };

    const int32_t max_iters = 45;
    std::vector<int32_t> order = init_perm;

    for (int32_t iter = 0; iter < max_iters; ++iter) {
        int64_t present_cost = 1500 + static_cast<int64_t>(iter) * 2000;

        for (int32_t pos = 0; pos < G; ++pos) {
            int32_t gi = order[pos];
            if (iter > 0 && !net_dirty[gi]) continue;

            // Decrement old usage of gi
            if (iter > 0) {
                for (int32_t h : net_used_holes[gi]) {
                    if (hole_owner_count[h] > 0) hole_owner_count[h]--;
                }
            }

            // Build hard obstacle mask: base_obs + all OTHER groups' target holes
            g_obs.assign(base_obs, base_obs + N);
            for (int32_t gj = 0; gj < G; ++gj) {
                if (gj == gi) continue;
                for (int32_t h : groups[gj].all_holes) g_obs[h] = 1;
            }
            for (int32_t h : groups[gi].all_holes) g_obs[h] = 0;

            // Build negotiated soft penalty from currently occupying nets + history
            for (int32_t h = 0; h < N; ++h) {
                int64_t occ = hole_owner_count[h];
                active_pen[h] = hist_pen[h] + (occ > 0 ? occ * present_cost : 0);
            }

            // Active jumpers for crossings = init_jumpers + all other nets' jumpers
            std::vector<JumperData> cur_jumpers = init_jumpers;
            for (int32_t gj = 0; gj < G; ++gj) {
                if (gj != gi) {
                    cur_jumpers.insert(cur_jumpers.end(), net_results[gj].jumpers.begin(), net_results[gj].jumpers.end());
                }
            }

            GroupResult g_res = ws.route_single_group(
                groups[gi], g_obs.data(), pin_grid, active_pen.data(), cur_jumpers, settings
            );
            if (!g_res.success) {
                return sol; // Impossible even when allowing intermediate hole negotiation
            }

            net_results[gi] = std::move(g_res);
            recompute_net_holes(gi);
            for (int32_t h : net_used_holes[gi]) {
                hole_owner_count[h]++;
            }
        }

        // Check if any hole is shared by 2+ nets
        int32_t conflicted_holes = 0;
        std::fill(net_dirty.begin(), net_dirty.end(), 0);
        for (int32_t h = 0; h < N; ++h) {
            if (hole_owner_count[h] > 1) {
                conflicted_holes++;
                hist_pen[h] += 1000 + static_cast<int64_t>(iter) * 1500;
            }
        }
        if (conflicted_holes == 0) {
            // Re-evaluate exact costs and active jumper crossings cleanly in fixed order
            std::fill(hole_owner_count.begin(), hole_owner_count.end(), 0);
            std::vector<uint8_t> dummy_placed(N, 0);
            std::vector<JumperData> final_jumpers = init_jumpers;
            int64_t exact_total = 0;
            sol.group_results.clear();
            bool verified = true;
            for (int32_t gi : order) {
                // Recompute exact cost with 0 artificial penalty while locking all other nets' holes
                g_obs.assign(base_obs, base_obs + N);
                for (int32_t gj = 0; gj < G; ++gj) {
                    if (gj == gi) continue;
                    for (int32_t h : net_used_holes[gj]) g_obs[h] = 1;
                }
                GroupResult exact_res = ws.route_single_group(
                    groups[gi], g_obs.data(), pin_grid, nullptr, final_jumpers, settings
                );
                if (!exact_res.success) {
                    verified = false;
                    break;
                }
                exact_total += exact_res.cost;
                net_results[gi] = exact_res;
                recompute_net_holes(gi);
                sol.group_results.push_back(std::move(exact_res));
            }
            if (verified) {
                sol.success = true;
                sol.total_cost = exact_total;
                return sol;
            }
        }

        // Mark only conflicted nets dirty for next iteration & move conflicted nets earlier
        std::vector<int32_t> conflicted_nets, clean_nets;
        for (int32_t gi : order) {
            bool bad = false;
            for (int32_t h : net_used_holes[gi]) {
                if (hole_owner_count[h] > 1) {
                    bad = true;
                    break;
                }
            }
            if (bad) {
                net_dirty[gi] = 1;
                conflicted_nets.push_back(gi);
            } else {
                clean_nets.push_back(gi);
            }
        }
        order = conflicted_nets;
        order.insert(order.end(), clean_nets.begin(), clean_nets.end());
    }
    return sol;
}

int32_t count_group_escape_freedom(
    int cols, int rows, const GroupSpec& grp, const uint8_t* base_obs
) {
    std::vector<int32_t> frontier;
    for (int32_t h : grp.all_holes) {
        int32_t c = h % cols, r = h / cols;
        for (int d = 0; d < 4; ++d) {
            int32_t nc = c + DIRS[d][0], nr = r + DIRS[d][1];
            if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
            int32_t nidx = nr * cols + nc;
            if (!base_obs[nidx] && std::find(grp.all_holes.begin(), grp.all_holes.end(), nidx) == grp.all_holes.end()) {
                frontier.push_back(nidx);
            }
        }
    }
    std::sort(frontier.begin(), frontier.end());
    frontier.erase(std::unique(frontier.begin(), frontier.end()), frontier.end());
    return static_cast<int32_t>(frontier.size());
}

std::vector<std::vector<int32_t>> build_candidate_orderings(
    int cols, int rows,
    const std::vector<GroupSpec>& groups,
    const uint8_t* base_obs
) {
    int32_t G = static_cast<int32_t>(groups.size());
    std::vector<std::vector<int32_t>> orderings;

    if (G <= 4) {
        std::vector<int32_t> p(G);
        std::iota(p.begin(), p.end(), 0);
        do {
            orderings.push_back(p);
        } while (std::next_permutation(p.begin(), p.end()));
        return orderings;
    }

    struct Meta {
        int32_t idx;
        int32_t n_targets;
        int32_t freedom;
        int32_t min_c, max_c, min_r, max_r;
        int32_t bbox_w, man_span;
    };
    std::vector<Meta> metas;
    metas.reserve(G);
    for (int32_t i = 0; i < G; ++i) {
        Meta m{};
        m.idx = i;
        m.n_targets = static_cast<int32_t>(groups[i].targets.size());
        m.freedom = count_group_escape_freedom(cols, rows, groups[i], base_obs);
        m.min_c = cols; m.max_c = 0; m.min_r = rows; m.max_r = 0;
        for (int32_t h : groups[i].all_holes) {
            int32_t c = h % cols, r = h / cols;
            m.min_c = std::min(m.min_c, c); m.max_c = std::max(m.max_c, c);
            m.min_r = std::min(m.min_r, r); m.max_r = std::max(m.max_r, r);
        }
        m.bbox_w = m.max_c - m.min_c;
        m.man_span = (m.max_c - m.min_c) + (m.max_r - m.min_r);
        metas.push_back(m);
    }

    auto push_sorted = [&](auto cmp) {
        auto copy = metas;
        std::stable_sort(copy.begin(), copy.end(), cmp);
        std::vector<int32_t> p(G);
        for (int32_t i = 0; i < G; ++i) p[i] = copy[i].idx;
        orderings.push_back(std::move(p));
    };

    // 1. Constrained pins first (lowest escape degree)
    push_sorted([](const Meta& a, const Meta& b) {
        if (a.freedom != b.freedom) return a.freedom < b.freedom;
        return a.man_span < b.man_span;
    });
    // 2. Original router.py order
    push_sorted([](const Meta& a, const Meta& b) {
        if (a.n_targets != b.n_targets) return a.n_targets < b.n_targets;
        return a.bbox_w < b.bbox_w;
    });
    // 3. Shortest span first
    push_sorted([](const Meta& a, const Meta& b) { return a.man_span < b.man_span; });
    // 4. Longest span first
    push_sorted([](const Meta& a, const Meta& b) { return a.man_span > b.man_span; });
    // 5-8. Spatial sweeps (top->bottom, bottom->top, left->right, right->left)
    push_sorted([](const Meta& a, const Meta& b) { return a.min_r < b.min_r; });
    push_sorted([](const Meta& a, const Meta& b) { return a.min_r > b.min_r; });
    push_sorted([](const Meta& a, const Meta& b) { return a.min_c < b.min_c; });
    push_sorted([](const Meta& a, const Meta& b) { return a.min_c > b.min_c; });
    // 9. Outside-in (pins farthest from board center first)
    int32_t mid_c = cols / 2, mid_r = rows / 2;
    push_sorted([&](const Meta& a, const Meta& b) {
        int32_t da = std::abs((a.min_c + a.max_c) / 2 - mid_c) + std::abs((a.min_r + a.max_r) / 2 - mid_r);
        int32_t db = std::abs((b.min_c + b.max_c) / 2 - mid_c) + std::abs((b.min_r + b.max_r) / 2 - mid_r);
        return da > db;
    });
    // 10. Inside-out
    push_sorted([&](const Meta& a, const Meta& b) {
        int32_t da = std::abs((a.min_c + a.max_c) / 2 - mid_c) + std::abs((a.min_r + a.max_r) / 2 - mid_r);
        int32_t db = std::abs((b.min_c + b.max_c) / 2 - mid_c) + std::abs((b.min_r + b.max_r) / 2 - mid_r);
        return da < db;
    });

    // Deterministic diverse shuffles up to 32 orderings
    std::mt19937 rng(0x50455246u);
    std::vector<int32_t> base(G);
    std::iota(base.begin(), base.end(), 0);
    while (orderings.size() < 32) {
        auto shuf = base;
        std::shuffle(shuf.begin(), shuf.end(), rng);
        orderings.push_back(std::move(shuf));
    }

    // Deduplicate while preserving heuristic priority
    std::vector<std::vector<int32_t>> unique_orders;
    for (const auto& o : orderings) {
        if (std::find(unique_orders.begin(), unique_orders.end(), o) == unique_orders.end()) {
            unique_orders.push_back(o);
        }
    }
    return unique_orders;
}

int32_t* serialize_solution(const FullSolution& sol, int32_t* out_len) {
    /*
     * Output format (flat int32_t array):
     * [0]: success (1 or 0)
     * [1]: total_cost_low32, [2]: total_cost_high32 (or int64 clamped? pack hi/lo cleanly!)
     * [3]: num_groups
     * For each group:
     *   [group_id, cost_lo, cost_hi, num_solder_segs, s0_h1, s0_h2, ..., num_jumpers,
     *    (j_start_idx, j_end_idx, n_bends, b0_idx, ..., bk_idx), ...]
     */
    std::vector<int32_t> buf;
    buf.reserve(4096);

    auto push_i64 = [&](int64_t v) {
        uint64_t u = static_cast<uint64_t>(v);
        buf.push_back(static_cast<int32_t>(u & 0xFFFFFFFFULL));
        buf.push_back(static_cast<int32_t>((u >> 32) & 0xFFFFFFFFULL));
    };

    buf.push_back(sol.success ? 1 : 0);
    push_i64(sol.success ? sol.total_cost : 0);
    buf.push_back(static_cast<int32_t>(sol.group_results.size()));

    if (sol.success) {
        for (const auto& gr : sol.group_results) {
            buf.push_back(gr.group_id);
            push_i64(gr.cost);
            buf.push_back(static_cast<int32_t>(gr.solders.size()));
            for (const auto& seg : gr.solders) {
                buf.push_back(seg.first);
                buf.push_back(seg.second);
            }
            buf.push_back(static_cast<int32_t>(gr.jumpers.size()));
            for (const auto& jd : gr.jumpers) {
                // Packed Pt coordinates (x, y) directly
                buf.push_back(jd.start.x);
                buf.push_back(jd.start.y);
                buf.push_back(jd.end.x);
                buf.push_back(jd.end.y);
                buf.push_back(static_cast<int32_t>(jd.bends.size()));
                for (const auto& b : jd.bends) {
                    buf.push_back(b.x);
                    buf.push_back(b.y);
                }
            }
        }
    }

    *out_len = static_cast<int32_t>(buf.size());
    int32_t* raw = static_cast<int32_t*>(std::malloc(buf.size() * sizeof(int32_t)));
    if (raw && !buf.empty()) {
        std::memcpy(raw, buf.data(), buf.size() * sizeof(int32_t));
    }
    return raw;
}

std::vector<JumperData> parse_existing_jumpers(const int32_t* data, int32_t count) {
    std::vector<JumperData> out;
    if (!data || count <= 0) return out;
    int32_t pos = 0;
    for (int32_t i = 0; i < count; ++i) {
        JumperData jd;
        jd.start.x = data[pos++];
        jd.start.y = data[pos++];
        jd.end.x = data[pos++];
        jd.end.y = data[pos++];
        int32_t nb = data[pos++];
        jd.bends.reserve(nb);
        for (int32_t b = 0; b < nb; ++b) {
            int32_t bx = data[pos++];
            int32_t by = data[pos++];
            jd.bends.push_back({bx, by});
        }
        jd.update_bbox();
        out.push_back(std::move(jd));
    }
    return out;
}

} // namespace

RC_EXPORT void rc_free_buffer(int32_t* ptr) {
    std::free(ptr);
}

RC_EXPORT int32_t* rc_solve_multi(
    int32_t cols, int32_t rows,
    const int64_t* settings_arr,      // 6 int64s
    const int32_t* base_obs_holes, int32_t n_base_obs,
    const int32_t* pin_holes, int32_t n_pins,
    const int32_t* existing_j_data, int32_t n_existing_j,
    const int32_t* groups_data, int32_t n_groups,
    int32_t* out_len
) {
    Settings settings;
    settings.cost_solder_move = settings_arr[0];
    settings.cost_solder_turn = settings_arr[1];
    settings.cost_jumper_start = settings_arr[2];
    settings.cost_jumper_move = settings_arr[3];
    settings.cost_jumper_turn = settings_arr[4];
    settings.cost_jumper_cross = settings_arr[5];

    int32_t N = cols * rows;
    std::vector<uint8_t> base_obs(N, 0);
    for (int32_t i = 0; i < n_base_obs; ++i) {
        int32_t h = base_obs_holes[i];
        if (h >= 0 && h < N) base_obs[h] = 1;
    }

    std::vector<uint8_t> pin_grid(N, 0);
    for (int32_t i = 0; i < n_pins; ++i) {
        int32_t h = pin_holes[i];
        if (h >= 0 && h < N) pin_grid[h] = 1;
    }

    std::vector<JumperData> init_jumpers = parse_existing_jumpers(existing_j_data, n_existing_j);

    // Parse groups_data: [group_id, n_targets, (n_holes, h0, h1...), ...]
    std::vector<GroupSpec> groups;
    groups.reserve(n_groups);
    int32_t pos = 0;
    for (int32_t g = 0; g < n_groups; ++g) {
        GroupSpec gs;
        gs.id = groups_data[pos++];
        int32_t nt = groups_data[pos++];
        gs.targets.resize(nt);
        for (int32_t t = 0; t < nt; ++t) {
            int32_t nh = groups_data[pos++];
            gs.targets[t].reserve(nh);
            for (int32_t h = 0; h < nh; ++h) {
                int32_t h_idx = groups_data[pos++];
                if (h_idx >= 0 && h_idx < N) {
                    gs.targets[t].push_back(h_idx);
                    gs.all_holes.push_back(h_idx);
                }
            }
        }
        std::sort(gs.all_holes.begin(), gs.all_holes.end());
        gs.all_holes.erase(std::unique(gs.all_holes.begin(), gs.all_holes.end()), gs.all_holes.end());
        groups.push_back(std::move(gs));
    }

    if (groups.empty()) {
        FullSolution empty_sol;
        return serialize_solution(empty_sol, out_len);
    }

    // Build candidate group orderings
    std::vector<std::vector<int32_t>> orderings = build_candidate_orderings(cols, rows, groups, base_obs.data());

    // Execute across worker threads
    int32_t num_tasks = static_cast<int32_t>(orderings.size());
    int32_t hw = static_cast<int32_t>(std::thread::hardware_concurrency());
    if (hw <= 0) hw = 4;
    int32_t num_threads = std::min(hw, num_tasks);
    if (groups.size() <= 1 || num_tasks <= 1) num_threads = 1;

    std::vector<FullSolution> thread_best(num_threads);
    std::atomic<int64_t> global_best_cost{INF_COST};
    std::atomic<int32_t> win_count{0};

    auto worker_fn = [&](int32_t tid, bool protect_exits) {
        SolverWorkspace ws;
        ws.init(cols, rows);
        FullSolution& best = thread_best[tid];
        for (int32_t i = tid; i < num_tasks; i += num_threads) {
            if (i >= 10 && win_count.load(std::memory_order_relaxed) >= 6) break;
            FullSolution sol = run_ordering_with_backjumping(
                ws, cols, rows, N, orderings[i], groups,
                base_obs.data(), pin_grid.data(), init_jumpers, settings, protect_exits,
                global_best_cost, win_count
            );
            if (sol.success && sol.total_cost < best.total_cost) {
                best = std::move(sol);
            }
        }
    };

    if (num_threads == 1) {
        worker_fn(0, true);
    } else {
        std::vector<std::thread> threads;
        threads.reserve(num_threads);
        for (int32_t t = 0; t < num_threads; ++t) {
            threads.emplace_back(worker_fn, t, true);
        }
        for (auto& th : threads) th.join();
    }

    FullSolution overall_best;
    for (auto& tb : thread_best) {
        if (tb.success && tb.total_cost < overall_best.total_cost) {
            overall_best = std::move(tb);
        }
    }

    // If strict exit protection didn't find a clean route, run without forced-exit lock
    // AND run PathFinder iterative rip-up-and-reroute in parallel!
    if (!overall_best.success) {
        for (auto& tb : thread_best) {
            tb = FullSolution{};
        }
        global_best_cost.store(INF_COST, std::memory_order_relaxed);
        win_count.store(0, std::memory_order_relaxed);
        auto fallback_fn = [&](int32_t tid) {
            SolverWorkspace ws;
            ws.init(cols, rows);
            FullSolution& best = thread_best[tid];
            for (int32_t i = tid; i < num_tasks; i += num_threads) {
                if (i >= 10 && win_count.load(std::memory_order_relaxed) >= 4) break;
                FullSolution sol = run_ordering_with_backjumping(
                    ws, cols, rows, N, orderings[i], groups,
                    base_obs.data(), pin_grid.data(), init_jumpers, settings, false,
                    global_best_cost, win_count
                );
                if (sol.success && sol.total_cost < best.total_cost) {
                    best = std::move(sol);
                }
            }
            if (!best.success && win_count.load(std::memory_order_relaxed) == 0 && tid < 4) {
                // PathFinder congestion negotiation starting from top diverse seeds
                int32_t pf_idx = std::min<int32_t>(tid, num_tasks - 1);
                FullSolution pf_sol = run_pathfinder_reroute(
                    ws, cols, rows, N, orderings[pf_idx], groups,
                    base_obs.data(), pin_grid.data(), init_jumpers, settings
                );
                if (pf_sol.success && pf_sol.total_cost < best.total_cost) {
                    best = std::move(pf_sol);
                }
            }
        };

        if (num_threads == 1) {
            fallback_fn(0);
        } else {
            std::vector<std::thread> threads;
            threads.reserve(num_threads);
            for (int32_t t = 0; t < num_threads; ++t) {
                threads.emplace_back(fallback_fn, t);
            }
            for (auto& th : threads) th.join();
        }

        for (auto& tb : thread_best) {
            if (tb.success && tb.total_cost < overall_best.total_cost) {
                overall_best = std::move(tb);
            }
        }
    }

    return serialize_solution(overall_best, out_len);
}
