// Cap behavior, disabled identity, tie break and input-order robustness.
#include "FixedExtractionBudget.h"
#include <cassert>
struct Corner { float response; struct Point { float x,y; } pt; };
int main() {
    using namespace ORB_SLAM3;
    std::vector<Corner> v={{1,{0,0}},{3,{2,0}},{3,{1,0}},{2,{1,1}},{3,{0,1}}};
    auto original=v;LimitExtractionCell(v,0);
    for(unsigned i=0;i<v.size();++i) assert(v[i].response==original[i].response && v[i].pt.x==original[i].pt.x && v[i].pt.y==original[i].pt.y);
    auto reverse=v;std::reverse(reverse.begin(),reverse.end());
    LimitExtractionCell(v,2);LimitExtractionCell(reverse,2);
    assert(v.size()==2 && v[0].pt.x==1 && v[1].pt.x==2);
    for(unsigned i=0;i<v.size();++i) assert(v[i].pt.x==reverse[i].pt.x && v[i].pt.y==reverse[i].pt.y);
    LimitExtractionCell(v,4);assert(v.size()==2);
    std::vector<Corner> empty;LimitExtractionCell(empty,16);assert(empty.empty());
}
