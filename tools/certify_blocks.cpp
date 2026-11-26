/*
 * Reproduce the exact small-block constants used in card_sorter.py.
 *
 *   c++ -O3 -std=c++20 certify_blocks.cpp -o certify_blocks
 *   ./certify_blocks 11
 *
 * The argument is the maximum size to enumerate (1..11). The largest case
 * takes approximately 1.5 GiB of working memory. No third-party libraries.
 * The final pair of columns covers all-in-L to n-1 cards in L and one in R.
 */
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using Word = std::uint64_t;
using Bits = std::vector<Word>;
using Layers = std::vector<Bits>;

constexpr int left = 0;
constexpr int center = 1;
constexpr int right = 2;
constexpr int limit = 11;

struct Distances {
    int count = 0;
    int maximum = 0;
    std::int64_t sum = 0;
};

struct Shape {
    int left_size;
    int center_size;
    // Indices of neighboring shapes, -1 if the corresponding source is empty.
    int left_to_center;
    int center_to_left;
    int center_to_right;
    int right_to_center;
};

class StateSpace {
public:
    explicit StateSpace(int n) : n_(n) {
        factorial_[0] = 1;
        for (int k = 1; k <= n_; ++k) {
            factorial_[k] = k * factorial_[k - 1];
            build_rotations(k);
        }
        int index = 0;
        for (int l = 0; l <= n_; ++l)
            for (int c = 0; c <= n_ - l; ++c)
                shape_id_[l][c] = index++;
        for (int l = 0; l <= n_; ++l) {
            for (int c = 0; c <= n_ - l; ++c) {
                shapes_.push_back({l, c,
                    l > 0 ? shape_id_[l - 1][c + 1] : -1,
                    c > 0 ? shape_id_[l + 1][c - 1] : -1,
                    c > 0 ? shape_id_[l][c - 1] : -1,
                    l + c < n_ ? shape_id_[l][c + 1] : -1});
            }
        }
        full_ = {shape_id_[n_][0], shape_id_[0][n_], shape_id_[0][0]};
    }

    std::array<Distances, 4> enumerate(int source) const {
        const int orders = factorial_[n_];
        const auto words = static_cast<std::size_t>((orders + 63) / 64);
        Layers seen(shapes_.size(), Bits(words));
        Layers frontier = seen;
        Layers next = seen;
        // Rank zero is one arbitrary all-in-source order. Card relabeling
        // preserves the graph, so it serves for all relative orders.
        seen[full_[source]][0] = frontier[full_[source]][0] = 1;
        std::array<Distances, 4> result{};
        const std::array<int, 4> endpoints = {
            full_[left], full_[center], full_[right], shape_id_[n_ - 1][0]};
        for (int depth = 0; ; ++depth) {
            for (std::size_t index = 0; index < endpoints.size(); ++index) {
                int count = 0;
                for (Word word : frontier[endpoints[index]])
                    count += std::popcount(word);
                if (count) {
                    result[index].count += count;
                    result[index].maximum = depth;
                    result[index].sum += static_cast<std::int64_t>(count) * depth;
                }
            }
            if (std::all_of(result.begin(), result.end(),
                            [orders](const Distances &d) { return d.count == orders; }))
                return result;

            for (std::size_t h = 0; h < shapes_.size(); ++h)
                expand(shapes_[h], frontier[h], next);

            bool found = false;
            for (std::size_t h = 0; h < shapes_.size(); ++h) {
                for (std::size_t w = 0; w < words; ++w) {
                    Word fresh = next[h][w] & ~seen[h][w];
                    frontier[h][w] = fresh;
                    seen[h][w] |= fresh;
                    next[h][w] = 0;
                    found |= fresh != 0;
                }
            }
            if (!found)
                throw std::logic_error("Some requested endpoint is unreachable.");
        }
    }

private:
    int n_;
    std::array<int, limit + 1> factorial_{};
    std::array<std::vector<int>, limit + 1> rotate_left_, rotate_right_;
    int shape_id_[limit + 1][limit + 1]{};
    std::vector<Shape> shapes_;
    std::array<int, 3> full_{};

    // Flatten the stacks as L bottom-first, C top-first, R bottom-first.
    // C -> R rotates the n-l suffix one place to the left. Its inverse
    // rotates that suffix to the right. Compute the new suffix's Lehmer rank.
    void build_rotations(int k) {
        std::vector<int> values(k);
        std::iota(values.begin(), values.end(), 0);
        rotate_left_[k].resize(factorial_[k]);
        rotate_right_[k].resize(factorial_[k]);
        int rank = 0;
        do {
            int rotated_rank = 0;
            unsigned available = (1u << k) - 1;
            for (int i = 0; i < k; ++i) {
                int x = values[(i + 1) % k];
                unsigned smaller = available & ((1u << x) - 1);
                rotated_rank += std::popcount(smaller) * factorial_[k - i - 1];
                available ^= 1u << x;
            }
            rotate_left_[k][rank] = rotated_rank;
            rotate_right_[k][rotated_rank] = rank;
            ++rank;
        } while (std::next_permutation(values.begin(), values.end()));
    }

    void expand(const Shape &shape, const Bits &frontier, Layers &next) const {
        // C <-> L changes a boundary only, preserving the full permutation.
        for (int h : {shape.left_to_center, shape.center_to_left}) {
            if (h < 0) continue;
            for (std::size_t w = 0; w < frontier.size(); ++w)
                next[h][w] |= frontier[w];
        }
        int k = n_ - shape.left_size;
        if (k == 0) return;
        for (std::size_t w = 0; w < frontier.size(); ++w) {
            Word bits = frontier[w];
            while (bits) {
                int rank = static_cast<int>(64 * w) + std::countr_zero(bits);
                bits &= bits - 1;
                // In lexicographic ranking with a fixed prefix, the suffix
                // occupies one consecutive interval of k! permutation ranks.
                int suffix = (k == n_) ? rank : rank % factorial_[k];
                int base = rank - suffix;
                if (shape.center_to_right >= 0)
                    mark(next[shape.center_to_right], base + rotate_left_[k][suffix]);
                if (shape.right_to_center >= 0)
                    mark(next[shape.right_to_center], base + rotate_right_[k][suffix]);
            }
        }
    }

    static void mark(Bits &bits, int rank) {
        bits[rank / 64] |= Word{1} << (rank % 64);
    }
};

int main(int argc, char **argv) {
    try {
        int largest = (argc == 1) ? limit : std::stoi(argv[1]);
        if (argc > 2 || largest < 1 || largest > limit)
            throw std::invalid_argument("Usage: certify_blocks [maximum size 1 through 11]");
        std::cout << "n,CC_max,CC_sum,CO_max,CO_sum,OO_max,OO_sum,LR_max,LR_sum,"
                     "L_split_max,L_split_sum\n";
        for (int n = 1; n <= largest; ++n) {
            const StateSpace space(n);
            auto from_center = space.enumerate(center);
            auto from_outer = space.enumerate(left);
            if (from_center[left].maximum != from_outer[center].maximum ||
                from_center[left].sum != from_outer[center].sum)
                throw std::logic_error("Time-reversed endpoint counts disagree.");
            std::cout << n;
            for (const Distances &d : {from_center[center], from_center[left],
                                       from_outer[left], from_outer[right], from_outer[3]})
                std::cout << ',' << d.maximum << ',' << d.sum;
            std::cout << std::endl;
        }
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
