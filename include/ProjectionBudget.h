// Optional projection candidate selection. GPL-3.0-or-later.
#ifndef ORB_PROJECTION_BUDGET_H
#define ORB_PROJECTION_BUDGET_H
#include <algorithm>
#include <cstdint>
#include <unordered_set>
#include <vector>
namespace ORB_SLAM3 {
template<class Point> struct ProjectionSelection {
    std::vector<Point*> points;
    uint64_t slots=0, matchedSlots=0, referenceSelected=0;
};
// Keep existing frame associations outside the extra-search quota. Preserve
// reference-frame feature order, then interleave other views deterministically.
// The quota bounds candidates, not all CPU work or latency.
template<class Point, class Valid>
ProjectionSelection<Point> SelectProjectionCandidates(
    const std::vector<Point*>& reference,
    const std::vector<std::vector<Point*>>& views,
    const std::unordered_set<Point*>& matched, unsigned limit, Valid valid) {
    ProjectionSelection<Point> out;
    std::unordered_set<Point*> seen;
    auto full=[&](){return limit && out.points.size()>=limit;};
    auto add=[&](Point* p) {
        ++out.slots;
        if(!p || !valid(p)) return false;
        if(matched.count(p)) {++out.matchedSlots;return false;}
        if(!seen.insert(p).second) return false;
        out.points.push_back(p);return true;
    };
    for(auto p:reference) {
        if(full()) break;
        if(add(p)) ++out.referenceSelected;
    }
    size_t longest=0;
    for(const auto& v:views) longest=std::max(longest,v.size());
    for(size_t i=0;i<longest && !full();++i) {
        for(const auto& v:views) {
            if(full()) break;
            if(i<v.size()) add(v[i]);
        }
    }
    return out;
}
}
#endif
