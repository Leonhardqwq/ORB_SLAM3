// Optional deterministic preselection for the fixed serial owner. GPL-3.0-or-later.
#ifndef ORB_FIXED_EXTRACTION_BUDGET_H
#define ORB_FIXED_EXTRACTION_BUDGET_H
#include <algorithm>
#include <vector>
namespace ORB_SLAM3 {
// Keep the strongest corners inside EACH cell, with a deterministic spatial tie
// break. Zero retains the exact original vector and order. FAST and its fallback
// run unchanged: this bounds octree input, not all extraction work or wall time.
template<class Corner> void LimitExtractionCell(std::vector<Corner>& points, unsigned cap) {
    if(!cap || points.size()<=cap) return;
    auto stronger=[](const Corner& a,const Corner& b) {
        if(a.response!=b.response) return a.response>b.response;
        if(a.pt.y!=b.pt.y) return a.pt.y<b.pt.y;
        return a.pt.x<b.pt.x;
    };
    std::partial_sort(points.begin(),points.begin()+cap,points.end(),stronger);
    points.resize(cap);
}
}
#endif
