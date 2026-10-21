// Optional fixed-replay diagnostics. GPL-3.0-or-later.
#ifndef ORB_TRACKING_DIAGNOSTICS_H
#define ORB_TRACKING_DIAGNOSTICS_H
#include <array>
#include <cstdint>
namespace ORB_SLAM3 {
enum class TrackingStage { Extraction, StereoMatch, Initialization, PosePrediction,
    LocalUpdate, LocalSearch, LocalOptimize, Keyframe, Count };
struct FixedWorkPolicy {
    bool enabled=false, budgetReference=false, referenceFirst=false, keyframeRequest=false, deferRoutineKeyframes=false;
    unsigned keyframes=0, points=0, extractionCellCandidates=0; // zero means no extra cap
};
bool ShouldDeferRoutineKeyframe(const FixedWorkPolicy*, bool stereo, bool trackingOK,
    bool establishedMap, bool maximumInterval, bool weakOrClose, int inliers);
struct TrackingStageRecord {
    uint64_t extractionCells=0, extractionCandidates=0, extractionRetained=0, extractionCappedCells=0, extractionRetainedCellMax=0;
    uint64_t projectionReference=0, projectionMatchedSlots=0;
    uint64_t refRaw=0, refEligible=0, refUsed=0, inliers=0, closeTracked=0, closeUntracked=0, keyframeFlags=0;
    uint64_t localKeyframes=0, localPoints=0, pointSlotsVisited=0, observationVotes=0;
    std::array<int64_t,8> ns{}, begin{}, end{};
    std::array<unsigned,8> calls{};
};
enum class BackendStage { Insert, CullPoints, CreatePoints, Fuse, LocalBA, CullKeyframes, Loop, Count };
struct FixedBackendPolicy { unsigned keyframes=0, points=0, maintenanceKeyframes=0, globalIterations=0, fixedKeyframes=0; };
struct BackendStageRecord {
    std::array<int64_t,7> ns{}, begin{}, end{};
    std::array<unsigned,7> calls{};
    uint64_t baCalls=0, baKeyframesMax=0, baPointsMax=0, baEdgesMax=0;
    uint64_t baFixedKeyframesMax=0, baFixedCandidatesMax=0, baDroppedPointsMax=0, baAnchorRejects=0;
    uint64_t fuseTargetsMax=0, cullCandidatesMax=0, cullSelectedMax=0;
    uint64_t globalBACalls=0, globalBARequestedMax=0, globalBAActualMax=0, globalBAIterationErrors=0;
    int64_t globalBAOptimizationNs=0;
};
const FixedBackendPolicy* CurrentFixedBackendPolicy();
void RecordBackendWork(uint64_t keyframes,uint64_t points,uint64_t edges, uint64_t fixed=0, uint64_t candidates=0, uint64_t dropped=0);
void RecordLocalBAAnchorRejection();
void RecordBackendMaintenance(uint64_t fuseTargets,uint64_t cullCandidates,uint64_t cullSelected);
void RecordGlobalBAIterations(int iterations);
class ScopedGlobalBAOptimization {
    BackendStageRecord* record;
    BackendStageRecord* previous;
    int64_t start=0;
public:
    explicit ScopedGlobalBAOptimization(unsigned requested);
    ~ScopedGlobalBAOptimization();
    ScopedGlobalBAOptimization(const ScopedGlobalBAOptimization&)=delete;
    ScopedGlobalBAOptimization& operator=(const ScopedGlobalBAOptimization&)=delete;
};
class ActiveBackendScope {
    const FixedBackendPolicy* previousPolicy;
    BackendStageRecord* previousRecord;
public:
    ActiveBackendScope(const FixedBackendPolicy*,BackendStageRecord*);
    ~ActiveBackendScope();
    ActiveBackendScope(const ActiveBackendScope&)=delete;
    ActiveBackendScope& operator=(const ActiveBackendScope&)=delete;
};
class ScopedBackendStage {
    BackendStageRecord* record;
    unsigned index;
    int64_t start=0;
public:
    explicit ScopedBackendStage(BackendStage);
    void stop();
    ~ScopedBackendStage() { stop(); }
    ScopedBackendStage(const ScopedBackendStage&)=delete;
    ScopedBackendStage& operator=(const ScopedBackendStage&)=delete;
};
struct TrackingContext {
    unsigned long mapId=0, mapPoints=0, mapKeyframes=0;
    unsigned long keypoints=0, pointSlots=0, nonnullPoints=0;
    int state=0;
    bool pendingReset=false;
};
// Policy is scoped to the fixed owner T call, never a process-global switch.
const FixedWorkPolicy* CurrentFixedWorkPolicy();
void RecordExtractionWork(uint64_t cells,uint64_t candidates,uint64_t retained,uint64_t capped,uint64_t maximum);
void RecordProjectionSelection(uint64_t reference,uint64_t matchedSlots);
void RecordFixedKeyframe(uint64_t raw,uint64_t eligible,uint64_t used,uint64_t inliers,uint64_t closeTracked,uint64_t closeUntracked,uint64_t flags);
void RecordFixedWork(uint64_t keyframes,uint64_t points,uint64_t slots,uint64_t votes);
class ActiveFixedWorkPolicy {
    const FixedWorkPolicy* previous;
public:
    explicit ActiveFixedWorkPolicy(const FixedWorkPolicy*);
    ~ActiveFixedWorkPolicy();
    ActiveFixedWorkPolicy(const ActiveFixedWorkPolicy&)=delete;
    ActiveFixedWorkPolicy& operator=(const ActiveFixedWorkPolicy&)=delete;
};
// Thread-local scope is activated only by the fixed owner around one T call.
// Joined extraction workers are measured as one wall interval on that owner.
class ActiveTrackingRecord {
    TrackingStageRecord* previous;
public:
    explicit ActiveTrackingRecord(TrackingStageRecord*);
    ~ActiveTrackingRecord();
    ActiveTrackingRecord(const ActiveTrackingRecord&)=delete;
    ActiveTrackingRecord& operator=(const ActiveTrackingRecord&)=delete;
};
class ScopedTrackingStage {
    TrackingStageRecord* record;
    unsigned index;
    int64_t start=0;
public:
    explicit ScopedTrackingStage(TrackingStage);
    void stop();
    ~ScopedTrackingStage() { stop(); }
    ScopedTrackingStage(const ScopedTrackingStage&)=delete;
    ScopedTrackingStage& operator=(const ScopedTrackingStage&)=delete;
};
}
#endif
