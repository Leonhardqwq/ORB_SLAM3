#include "ProjectionBudget.h"
#include <cassert>
using namespace ORB_SLAM3;
struct P {bool bad;};
int main() {
    P a{false},b{false},c{false},d{true},e{false},f{false};
    std::vector<P*> ref{&a,&b,&b,nullptr,&d};
    std::vector<std::vector<P*>> views{{&a,&c,&e},{&b,&f,&c}};
    std::unordered_set<P*> matched{&a};
    auto valid=[](P* p){return !p->bad;};
    auto x=SelectProjectionCandidates(ref,views,matched,3,valid);
    assert((x.points==std::vector<P*>{&b,&c,&f}));
    assert(x.referenceSelected==1 && x.matchedSlots==2);
    auto y=SelectProjectionCandidates(ref,views,matched,1,valid);
    assert((y.points==std::vector<P*>{&b}));
    auto z=SelectProjectionCandidates(ref,views,matched,0,valid);
    assert((z.points==std::vector<P*>{&b,&c,&f,&e}));
    std::unordered_set<P*> all{&a,&b,&c,&e,&f};
    assert(SelectProjectionCandidates(ref,views,all,3,valid).points.empty());
    assert(SelectProjectionCandidates<P>(std::vector<P*>{},{},matched,3,valid).points.empty());
    assert((ref==std::vector<P*>{&a,&b,&b,nullptr,&d})); // no source mutation
}
