// Optional fixed-replay diagnostics. GPL-3.0-or-later.
#include "TrackingDiagnostics.h"
#include <chrono>
#include <algorithm>
namespace ORB_SLAM3 {
namespace {
thread_local TrackingStageRecord* active=nullptr;
thread_local const FixedBackendPolicy* backendPolicy=nullptr;
thread_local BackendStageRecord* backendRecord=nullptr;
thread_local BackendStageRecord* globalRecord=nullptr;
thread_local const FixedWorkPolicy* policy=nullptr;
int64_t now() { return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count(); }
}
const FixedBackendPolicy* CurrentFixedBackendPolicy() { return backendPolicy; }
ActiveBackendScope::ActiveBackendScope(const FixedBackendPolicy* p,BackendStageRecord* r):
    previousPolicy(backendPolicy),previousRecord(backendRecord) {
    backendPolicy=p;backendRecord=r;if(r) *r=BackendStageRecord{};
}
ActiveBackendScope::~ActiveBackendScope() { backendPolicy=previousPolicy;backendRecord=previousRecord; }
void RecordBackendWork(uint64_t k,uint64_t p,uint64_t e,uint64_t fixed,uint64_t candidates,uint64_t dropped) {
    if(backendRecord) { ++backendRecord->baCalls;
        backendRecord->baKeyframesMax=std::max(backendRecord->baKeyframesMax,k);
        backendRecord->baPointsMax=std::max(backendRecord->baPointsMax,p);
        backendRecord->baEdgesMax=std::max(backendRecord->baEdgesMax,e);
        backendRecord->baFixedKeyframesMax=std::max(backendRecord->baFixedKeyframesMax,fixed);
        backendRecord->baFixedCandidatesMax=std::max(backendRecord->baFixedCandidatesMax,candidates);
        backendRecord->baDroppedPointsMax=std::max(backendRecord->baDroppedPointsMax,dropped);
    }
}
void RecordLocalBAAnchorRejection() { if(backendRecord) ++backendRecord->baAnchorRejects; }
void RecordBackendMaintenance(uint64_t f,uint64_t c,uint64_t s) {
    if(backendRecord) {
        backendRecord->fuseTargetsMax=std::max(backendRecord->fuseTargetsMax,f);
        backendRecord->cullCandidatesMax=std::max(backendRecord->cullCandidatesMax,c);
        backendRecord->cullSelectedMax=std::max(backendRecord->cullSelectedMax,s);
    }
}
ScopedGlobalBAOptimization::ScopedGlobalBAOptimization(unsigned requested):record(backendRecord),previous(globalRecord) {
    globalRecord=record;
    if(record) {++record->globalBACalls;record->globalBARequestedMax=std::max(record->globalBARequestedMax,uint64_t(requested));start=now();}
}
ScopedGlobalBAOptimization::~ScopedGlobalBAOptimization() {
    if(record) record->globalBAOptimizationNs+=now()-start;
    globalRecord=previous;
}
void RecordGlobalBAIterations(int iterations) {
    if(globalRecord) {
        if(iterations<0) ++globalRecord->globalBAIterationErrors;
        else globalRecord->globalBAActualMax=std::max(globalRecord->globalBAActualMax,uint64_t(iterations));
    }
}
ScopedBackendStage::ScopedBackendStage(BackendStage s):record(backendRecord),index(static_cast<unsigned>(s)) {
    if(record) start=now();
}
void ScopedBackendStage::stop() {
    if(!record) return;
    const auto finish=now();
    if(!record->calls[index]) record->begin[index]=start;
    record->end[index]=finish;record->ns[index]+=finish-start;
    ++record->calls[index];record=nullptr;
}
const FixedWorkPolicy* CurrentFixedWorkPolicy() { return policy; }
bool ShouldDeferRoutineKeyframe(const FixedWorkPolicy* p,bool stereo,bool trackingOK,
    bool establishedMap,bool maximumInterval,bool weakOrClose,int inliers) {
    return p && p->enabled && p->budgetReference && p->deferRoutineKeyframes &&
        !p->keyframeRequest && stereo && trackingOK && establishedMap &&
        !maximumInterval && !weakOrClose && inliers>=75;
}
ActiveFixedWorkPolicy::ActiveFixedWorkPolicy(const FixedWorkPolicy* p):previous(policy) { policy=p; }
ActiveFixedWorkPolicy::~ActiveFixedWorkPolicy() { policy=previous; }
void RecordExtractionWork(uint64_t cells,uint64_t candidates,uint64_t retained,uint64_t capped,uint64_t maximum) {
    if(active) {active->extractionCells+=cells;active->extractionCandidates+=candidates;
        active->extractionRetained+=retained;active->extractionCappedCells+=capped;
        active->extractionRetainedCellMax=std::max(active->extractionRetainedCellMax,maximum);}
}
void RecordProjectionSelection(uint64_t reference,uint64_t matchedSlots) {
    if(active) {active->projectionReference=reference;active->projectionMatchedSlots=matchedSlots;}
}
void RecordFixedKeyframe(uint64_t raw,uint64_t eligible,uint64_t used,uint64_t inliers,uint64_t closeTracked,uint64_t closeUntracked,uint64_t flags) {
    if(active) {active->refRaw=raw;active->refEligible=eligible;active->refUsed=used;
        active->inliers=inliers;active->closeTracked=closeTracked;active->closeUntracked=closeUntracked;active->keyframeFlags=flags;}
}
void RecordFixedWork(uint64_t k,uint64_t p,uint64_t s,uint64_t v) {
    if(active) {active->localKeyframes=k;active->localPoints=p;
        active->pointSlotsVisited=s;active->observationVotes=v;}
}
ActiveTrackingRecord::ActiveTrackingRecord(TrackingStageRecord* r):previous(active) {
    active=r;
    if(r) *r=TrackingStageRecord{};
}
ActiveTrackingRecord::~ActiveTrackingRecord() { active=previous; }
ScopedTrackingStage::ScopedTrackingStage(TrackingStage s):record(active),index(static_cast<unsigned>(s)) {
    if(record) start=now(); // no clock reads in the default disabled path
}
void ScopedTrackingStage::stop() {
    if(!record) return;
    const auto finish=now();
    if(!record->calls[index]) record->begin[index]=start;
    record->end[index]=finish;
    record->ns[index]+=finish-start;
    ++record->calls[index];record=nullptr;
}
}
