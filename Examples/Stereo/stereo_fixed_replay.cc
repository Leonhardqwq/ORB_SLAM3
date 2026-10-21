// Research replay entry for the optional fixed schedule. GPL-3.0-or-later,
// following ORB-SLAM3's license; visual algorithms remain in the shared library.
#include "System.h"
#include <opencv2/imgcodecs.hpp>
#include <chrono>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <thread>
#include <stdexcept>
#include <vector>
#include <string>
#include <algorithm>
#include <cmath>
#include <unistd.h>
#include <dirent.h>
#include <time.h>
#include <sys/resource.h>

using Clock = std::chrono::steady_clock;
using NS = std::chrono::nanoseconds;
using i64 = long long;
static i64 nowNs() { return std::chrono::duration_cast<NS>(Clock::now().time_since_epoch()).count(); }
static int threadCount() {
    DIR* tasks=opendir("/proc/self/task");
    if (!tasks) return -1;
    int count=0;
    while (auto entry=readdir(tasks)) if (entry->d_name[0]!='.') ++count;
    closedir(tasks); return count;
}
static i64 cpuNs() {
    timespec t; if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t)!=0)
        throw std::runtime_error("process CPU clock unavailable");
    return i64(t.tv_sec)*1000000000+t.tv_nsec;
}
// Optional probes belong only to this replay, never to System or its callers.
// Mode 1 records wall-clock boundaries; mode 2 adds thread CPU/switch probes.
// Probe cost remains in the measured gap and is NOT subtracted for acceptance.
struct ReleaseTrace {
    i64 enter=0,wake=0,spinBegin=0,spinExit=0,probeEnd=0;
    i64 maxPollGap=0,maxPollEnd=0,polls=0,cpuBegin=0,cpuEnd=0;
    long voluntaryBefore=0,voluntaryAfter=0,involuntaryBefore=0,involuntaryAfter=0;
};
static i64 threadCpuNs() {
    timespec t;
    if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)!=0) throw std::runtime_error("thread CPU clock unavailable");
    return i64(t.tv_sec)*1000000000+t.tv_nsec;
}
static void switches(long& voluntary,long& involuntary) {
    rusage r;
    if(getrusage(RUSAGE_THREAD,&r)!=0) throw std::runtime_error("thread usage unavailable");
    voluntary=r.ru_nvcsw;involuntary=r.ru_nivcsw;
}
static void waitRelease(i64 release,i64 spin,int diagnostics,ReleaseTrace& trace) {
    if (!diagnostics) {
        std::this_thread::sleep_until(Clock::time_point(NS(release-spin)));
        if (spin) while (nowNs()<release) { }
        return;
    }
    trace.enter=nowNs();
    std::this_thread::sleep_until(Clock::time_point(NS(release-spin)));
    trace.wake=nowNs();
    if (diagnostics==2) {
        switches(trace.voluntaryBefore,trace.involuntaryBefore);
        trace.cpuBegin=threadCpuNs();
    }
    trace.spinBegin=nowNs();
    i64 prior=trace.spinBegin,current=prior;
    if(spin) do {
        current=nowNs();++trace.polls;
        if(current-prior>trace.maxPollGap) {trace.maxPollGap=current-prior;trace.maxPollEnd=current;}
        prior=current;
    } while(current<release);
    trace.spinExit=current;
    if (diagnostics==2) {
        trace.cpuEnd=threadCpuNs();
        switches(trace.voluntaryAfter,trace.involuntaryAfter);
    }
    trace.probeEnd=nowNs();
}
struct Row {
    unsigned long round=0, frame=0, resets=0;
    int k=-1, state=-1;
    double sensorTime=0;
    Eigen::Vector3f position=Eigen::Vector3f::Zero();
    i64 release=0,aT=0,eT=0,aB=0,eB=0;
    std::vector<unsigned long> ids;
    ReleaseTrace releaseTrace;
    int threadsBeforeT=-1, threadsAfterT=-1, threadsAfterB=-1;
    std::vector<unsigned long> backendCounts;
    std::vector<unsigned long> workloadBefore,workloadAfter;
    int workMode=0; bool keyframeRequest=false; unsigned keyframeBudget=0,pointBudget=0;
    ORB_SLAM3::TrackingContext context;
    ORB_SLAM3::TrackingStageRecord stages;
    ORB_SLAM3::BackendStageRecord backendStages;
    i64 contextBegin=0,contextEnd=0,stagesReadBegin=0,stagesReadEnd=0;
    i64 probeBeforeBegin=0,probeBeforeEnd=0,probeAfterBegin=0,probeAfterEnd=0;
    i64 processCpuBeforeT=0,processCpuAfterT=0;
    long voluntaryBeforeT=0,involuntaryBeforeT=0,voluntaryAfterT=0,involuntaryAfterT=0;
};
// Public getters return copies under the System state mutex. Only pointer
// presence is counted; no potentially retired map point is dereferenced.
static std::vector<unsigned long> workloadSnapshot(ORB_SLAM3::System& slam) {
    const auto points=slam.GetTrackedMapPoints();
    const auto keys=slam.GetTrackedKeyPointsUn();
    return {static_cast<unsigned long>(keys.size()),static_cast<unsigned long>(points.size()),
            static_cast<unsigned long>(std::count_if(points.begin(),points.end(),[](ORB_SLAM3::MapPoint* p){return p!=nullptr;}))};
}
int main(int argc,char** argv)
{
    if (argc < 8 || (argc-8)%2 != 0) {
        std::cerr << "usage: stereo_fixed_replay VOC SETTINGS DATA TIMES OUTPUT_PREFIX instrument|plain|selftest|native_selftest EVAL_FRAMES [--period-ns N --spin-us N --init-limit N --preload-limit N --offset N --cv-threads N --eigen-threads N --release-diagnostics 0|1|2 --prepare-before-wait 0|1 --workload-diagnostics 0|1 --tracking-diagnostics 0|1]\n";
        return 2;
    }
    const std::string kind=argv[6];
    if (kind!="instrument" && kind!="plain" && kind!="selftest" && kind!="native_selftest") return 2;
    int evaluation=0,initialLimit=100,preloadLimit=0,offset=0,cvThreads=0,eigenThreads=0,diagnostics=0,prepareBeforeWait=0,workloadDiagnostics=0,trackingDiagnostics=0;
    int workControl=0,keyframePeriod=0,maintenanceKeyframes=0,backendKeyframes=0,backendPoints=0,globalIterations=0,deferRoutine=0,fixedKeyframes=0,extractionCellCandidates=0; uint32_t policySeed=20261019;
    i64 h=50000000,spin=0;
    try {
        evaluation=std::stoi(argv[7]);
        for(int arg=8;arg<argc;arg+=2) {
            const std::string key=argv[arg]; const i64 value=std::stoll(argv[arg+1]);
            if(value<0 || value>10000000000LL) throw std::invalid_argument("option range");
            if(key=="--work-control") { if(value>7) throw std::invalid_argument("work control flag"); workControl=value; }
            else if(key=="--defer-routine-keyframes") { if(value>1) throw std::invalid_argument("routine deferral flag"); deferRoutine=value; }
            else if(key=="--global-ba-iterations") { if(value<1 || value>10) throw std::invalid_argument("global BA iterations"); globalIterations=value; }
            else if(key=="--extraction-cell-candidates") { if(value<4 || value>256) throw std::invalid_argument("extraction cell cap"); extractionCellCandidates=value; }
            else if(key=="--backend-keyframes") { if(value<2 || value>64) throw std::invalid_argument("backend keyframe cap"); backendKeyframes=value; }
            else if(key=="--backend-fixed-keyframes") { if(value<1 || value>64) throw std::invalid_argument("backend fixed observer cap"); fixedKeyframes=value; }
            else if(key=="--backend-points") { if(value<100 || value>100000) throw std::invalid_argument("backend point cap"); backendPoints=value; }
            else if(key=="--maintenance-keyframes") { if(value>64) throw std::invalid_argument("maintenance cap"); maintenanceKeyframes=value; }
            else if(key=="--keyframe-period") { if(value>64) throw std::invalid_argument("keyframe period"); keyframePeriod=value; }
            else if(key=="--policy-seed") { if(value>UINT32_MAX) throw std::invalid_argument("seed range");policySeed=value; }
            else if(key=="--workload-diagnostics") { if(value>1) throw std::invalid_argument("workload flag"); workloadDiagnostics=value; }
            else if(key=="--tracking-diagnostics") { if(value>1) throw std::invalid_argument("tracking flag"); trackingDiagnostics=value; }
            else if(key=="--period-ns") h=value;
            else if(key=="--spin-us") { if(value>5000) throw std::invalid_argument("spin max 5000 us"); spin=value*1000; }
            else if(value>1000000) throw std::invalid_argument("option range");
            else if(key=="--prepare-before-wait") prepareBeforeWait=value;
            else if(key=="--release-diagnostics") diagnostics=value;
            else if(key=="--init-limit") initialLimit=value;
            else if(key=="--preload-limit") preloadLimit=value;
            else if(key=="--offset") offset=value;
            else if(key=="--cv-threads") cvThreads=value;
            else if(key=="--eigen-threads") eigenThreads=value;
            else throw std::invalid_argument("unknown option");
        }
        if((workControl>=6 && keyframePeriod<2) || (workControl<6 && keyframePeriod))
            throw std::invalid_argument("keyframe period requires control 6/7 and period 2..64");
        if(extractionCellCandidates && !workControl) throw std::invalid_argument("extraction cap requires work control");
        if(fixedKeyframes && workControl!=7) throw std::invalid_argument("backend fixed observers require work control 7");
        if(bool(backendKeyframes)!=bool(backendPoints) || ((backendKeyframes || backendPoints) && workControl!=7))
            throw std::invalid_argument("explicit backend budget requires paired limits and backend control");
        if(workControl==7 && !backendKeyframes) {backendKeyframes=8;backendPoints=2400;}
        if(deferRoutine && workControl!=7) throw std::invalid_argument("routine deferral requires backend control");
        if(globalIterations && workControl!=7) throw std::invalid_argument("global BA policy requires backend control");
        if(maintenanceKeyframes && workControl!=7) throw std::invalid_argument("maintenance requires backend control");
        if(workControl && (!trackingDiagnostics || kind!="instrument")) throw std::invalid_argument("work control requires tracking instrument");
        if(trackingDiagnostics && kind!="instrument") throw std::invalid_argument("tracking diagnostics require instrument kind");
        if(workloadDiagnostics && kind!="instrument") throw std::invalid_argument("workload diagnostics require instrument kind");
        if (!preloadLimit) preloadLimit=evaluation+initialLimit+1;
        if(evaluation<1 || initialLimit<1 || evaluation>100000 || h<1000 || spin>h/10 ||
           preloadLimit<evaluation+initialLimit+1 || cvThreads>256 || eigenThreads>256 || diagnostics>2 ||
           (diagnostics && kind!="instrument") || prepareBeforeWait>1 ||
           (prepareBeforeWait && kind!="instrument"))
            throw std::invalid_argument("invalid replay limits");
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 2; }
    const std::string prefix=argv[5];
    std::ofstream summary(prefix+"-summary.json");
    int evaluated=0,initializedAt=-1, emptyRounds=0,keyframes=0,invalid=0,checks=0;
    int threadsAtStart=-1,threadsAtEnd=-1;
    i64 begin=0,end=0,clockMin=0,clockMax=0,cpuBegin=0,cpuEnd=0;
    int cvBefore=0,cvAfter=0,eigenBefore=0,eigenAfter=0;
    std::vector<Row> rows;
    rows.reserve(preloadLimit);
    try {
        // Explicit policy for this standalone process. Zero preserves host policy.
        if (cvThreads) cv::setNumThreads(cvThreads);
        if (eigenThreads) Eigen::setNbThreads(eigenThreads);
        // Clock-pair diagnostic only, not a proved bound on OS scheduling error.
        clockMin=1000000000;
        for (int i=0;i<10000;++i) {
            const auto first=nowNs(); const auto diff=nowNs()-first;
            clockMin=std::min(clockMin,diff);clockMax=std::max(clockMax,diff);
        }
        std::vector<std::string> timestamps;
        std::ifstream input(argv[4]);
        if (!input) throw std::runtime_error("missing timestamp file");
        std::string value;
        int skipped=0;
        while (std::getline(input,value) && timestamps.size()<static_cast<size_t>(preloadLimit)) {
            if (skipped<offset) { ++skipped; continue; }
            if (!value.empty() && value.back()=='\r') value.pop_back();
            if (!value.empty()) timestamps.push_back(value);
        }
        if (timestamps.size()<static_cast<size_t>(initialLimit+evaluation+1))
            throw std::runtime_error("insufficient input for initialization and evaluation");
        std::vector<cv::Mat> left,right;
        for (const auto& t:timestamps) {
            auto l=cv::imread(std::string(argv[3])+"/mav0/cam0/data/"+t+".png",cv::IMREAD_GRAYSCALE);
            auto r=cv::imread(std::string(argv[3])+"/mav0/cam1/data/"+t+".png",cv::IMREAD_GRAYSCALE);
            if (l.empty() || r.empty()) throw std::runtime_error("unreadable input image");
            left.push_back(l);right.push_back(r);
        }
        cvBefore=cv::getNumThreads();eigenBefore=Eigen::nbThreads();
        ORB_SLAM3::System slam(argv[1],argv[2],ORB_SLAM3::System::STEREO,false);
        cvAfter=cv::getNumThreads();eigenAfter=Eigen::nbThreads();
        if(cvBefore!=cvAfter || eigenBefore!=eigenAfter)
            throw std::runtime_error("System changed application thread policy");
        const bool fixed=slam.IsFixedStereo();
        if(workControl && !fixed) throw std::invalid_argument("work control requires fixed mode");
        // Precomputed exogenous mode tape: independent of SLAM outcomes/timing.
        // One-in-16 low-bit trigger, not a proof of random independence; repeatability is scoped
        // to this explicit xorshift32 implementation, not std distributions.
        if(policySeed==0) throw std::invalid_argument("policy seed must be nonzero");
        uint32_t rng=policySeed;int state=0;vector<int> workModes(preloadLimit);
        for(auto& m:workModes) {rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;if((rng&15)==0)state=1-state;m=state;}

        if(trackingDiagnostics) slam.SetFixedTrackingDiagnostics(true);
        if(workloadDiagnostics && !fixed) throw std::invalid_argument("workload diagnostics require fixed mode");
        if (kind=="native_selftest" && fixed) throw std::runtime_error("native_selftest needs native mode");
        if (kind=="selftest" && !fixed) throw std::runtime_error("selftest requires fixed mode");
        unsigned long round=0;
        i64 origin=0;

        for (size_t i=0;i<left.size() && evaluated<evaluation;++i,++round) {
            const double sensorTime=std::stod(timestamps[i])/1e9;
            if (kind=="selftest" && i==0) {
                bool rejected=false;
                try { slam.CompleteMappingRound(0); } catch (const std::logic_error&) { rejected=true; }
                if (!rejected) throw std::runtime_error("missing T accepted"); ++checks;
                rejected=false;
                try { slam.TrackStereo(left[i],right[i],sensorTime); } catch (const std::logic_error&) { rejected=true; }
                if (!rejected) throw std::runtime_error("legacy API accepted"); ++checks;
                bool ownerRejected=false;
                std::thread wrong([&] { try { slam.TrackStereoFixed(0,left[i],right[i],sensorTime); }
                    catch (const std::logic_error&) { ownerRejected=true; } });
                wrong.join();
                if (!ownerRejected) throw std::runtime_error("other owner accepted"); ++checks;
            }
            const bool evaluate=initializedAt>=0;
            const i64 release=evaluate ? origin+evaluated*h : nowNs();
            ReleaseTrace releaseTrace;
            const auto awaitRelease=[&] {
                if(evaluate) waitRelease(release,spin,diagnostics,releaseTrace);
                if(evaluate && evaluated==0) cpuBegin=cpuNs();
            };
            if(!prepareBeforeWait) awaitRelease();
            if (kind=="native_selftest") {
                if(i==10) {slam.ActivateLocalizationMode();++checks;}
                if(i==20) {slam.DeactivateLocalizationMode();++checks;}
                if(i==30) {slam.ResetActiveMap();++checks;}
                if(i==45) {slam.Reset();++checks;}
            }
            Row row;row.round=round;row.k=evaluate ? evaluated : -1;row.release=release;row.sensorTime=sensorTime;
            // Optional layout: prepare the record before waiting; retain actual aT.
            if(prepareBeforeWait) awaitRelease();
            if (fixed && kind!="plain") row.threadsBeforeT=threadCount();
            if(workloadDiagnostics) {
                row.probeBeforeBegin=nowNs();row.workloadBefore=workloadSnapshot(slam);
                switches(row.voluntaryBeforeT,row.involuntaryBeforeT);
                row.processCpuBeforeT=cpuNs();row.probeBeforeEnd=nowNs();
            }
            if(workControl) {
                // Controls 5/6 use the same high budget. Phase is fixed by
                // input index (including initialization), never current outcomes.
                row.workMode=workControl>=6 ? int(i%keyframePeriod) : (workControl==5 ? 0 : workModes.at(i));
                row.keyframeRequest=workControl>=6 && row.workMode==0;
                row.keyframeBudget=workControl>=5 ? 32 : (workControl>=2 ? (row.workMode ? 32 : 16) : 0);
                row.pointBudget=workControl>=5 ? 2400 : (workControl>=2 ? (row.workMode ? 2400 : 1200) : 0);
                slam.SetFixedWorkPolicy(true,row.keyframeBudget,row.pointBudget,workControl==3 || workControl>=5,workControl==4,row.keyframeRequest,deferRoutine!=0,extractionCellCandidates);
                slam.SetFixedBackendBudget(backendKeyframes,backendPoints,maintenanceKeyframes,globalIterations,fixedKeyframes);
            }
            if(trackingDiagnostics) {
                row.contextBegin=nowNs();row.context=slam.FixedTrackingContext();row.contextEnd=nowNs();
            }
            if (kind!="plain") row.aT=nowNs();
            auto pose=fixed ? slam.TrackStereoFixed(round,left[i],right[i],sensorTime)
                            : slam.TrackStereo(left[i],right[i],sensorTime);
            row.state=slam.GetTrackingState();
            row.frame=fixed ? slam.FixedFrameId() : round;
            row.resets=fixed ? slam.FixedResetCount() : 0;
            // Pose has returned to the caller's preallocated record scope.
            if (kind!="plain") row.eT=nowNs();
            if(workloadDiagnostics) {
                row.probeAfterBegin=nowNs();row.processCpuAfterT=cpuNs();
                switches(row.voluntaryAfterT,row.involuntaryAfterT);
                row.workloadAfter=workloadSnapshot(slam);row.probeAfterEnd=nowNs();
            }
            if(trackingDiagnostics) {
                row.stagesReadBegin=nowNs();row.stages=slam.FixedTrackingStages();row.stagesReadEnd=nowNs();
            }
            if (fixed && kind!="plain") row.threadsAfterT=threadCount();
            if (kind=="selftest" && i==0) {
                bool rejected=false;
                try { slam.TrackStereoFixed(round+1,left[i],right[i],sensorTime+0.05); }
                catch (const std::logic_error&) { rejected=true; }
                if (!rejected) throw std::runtime_error("missing B accepted"); ++checks;
                rejected=false;
                try { slam.CompleteMappingRound(round+1); } catch (const std::logic_error&) { rejected=true; }
                if (!rejected) throw std::runtime_error("wrong B round accepted"); ++checks;
            }
            if (kind!="plain") row.aB=nowNs();
            if (fixed) row.ids=slam.CompleteMappingRound(round);
            if (kind!="plain") row.eB=nowNs();
            if(trackingDiagnostics) row.backendStages=slam.FixedBackendStages();
            if (fixed && kind!="plain") {
                row.threadsAfterB=threadCount();
                row.backendCounts=slam.FixedBackendCounts();
            }
            if (fixed) { if (row.ids.empty()) ++emptyRounds;keyframes+=row.ids.size(); }
            if (kind=="selftest" && i==0) {
                bool rejected=false;
                try { slam.CompleteMappingRound(round); } catch (const std::logic_error&) { rejected=true; }
                if (!rejected) throw std::runtime_error("duplicate B accepted"); ++checks;
                rejected=false;
                try { slam.TrackStereoFixed(round+1,left[i],right[i],sensorTime); }
                catch (const std::invalid_argument&) { rejected=true; }
                if (!rejected) throw std::runtime_error("repeated timestamp accepted"); ++checks;
            }
            if (kind=="selftest" && i==10) { slam.ResetActiveMap();++checks; }
            if (kind=="selftest" && i==25) { slam.Reset();++checks; }
            // Store the pose returned online, before any later map correction.
            row.position=pose.inverse().translation();
            if (evaluate) {
                ++evaluated;
                if (row.state!=ORB_SLAM3::Tracking::OK || !pose.matrix().allFinite()) ++invalid;
            }
            row.releaseTrace=releaseTrace;
            rows.push_back(std::move(row));
            if (!evaluate && rows.back().state==ORB_SLAM3::Tracking::OK) {
                initializedAt=static_cast<int>(i);
                threadsAtStart=threadCount();
                origin=nowNs()+h;begin=origin;
            }
            if (initializedAt<0 && i+1==static_cast<size_t>(initialLimit)) throw std::runtime_error("initialization exceeded configured limit");
        }
        end=nowNs();cpuEnd=cpuNs();
        threadsAtEnd=threadCount();
        if (evaluated!=evaluation) throw std::runtime_error("evaluation incomplete");
        if (kind=="selftest") {
            const size_t next=rows.size();
            slam.TrackStereoFixed(round,left.at(next),right.at(next),std::stod(timestamps.at(next))/1e9);
            slam.Shutdown(); ++checks; // Completes the pending B before closing.
            slam.Shutdown(); ++checks; // Repeated shutdown is harmless.
            bool rejected=false;
            try { slam.TrackStereoFixed(round+1,left.at(next),right.at(next),std::stod(timestamps.at(next))/1e9+0.05); }
            catch (const std::logic_error&) { rejected=true; }
            if (!rejected) throw std::runtime_error("closed system accepted a new round"); ++checks;
        }
        if (kind=="native_selftest") {
            const size_t next=rows.size();
            slam.ActivateLocalizationMode();
            slam.TrackStereo(left.at(next),right.at(next),std::stod(timestamps.at(next))/1e9);
            ++checks; // Shutdown while mapper is stopped must terminate.
        }
        slam.Shutdown();
        slam.SaveTrajectoryEuRoC(prefix+"-frames.txt");
        slam.SaveKeyFrameTrajectoryEuRoC(prefix+"-keyframes.txt");
        std::ofstream csv(prefix+"-events.csv");
        csv << "round,k,frame,release_ns,aT_ns,eT_ns,aB_ns,eB_ns,state,resets,keyframes,ids\n";
        for (const auto& r:rows) {
            csv<<r.round<<','<<r.k<<','<<r.frame<<','<<r.release<<','<<r.aT<<','<<r.eT<<','<<r.aB<<','<<r.eB
               <<','<<r.state<<','<<r.resets<<','<<r.ids.size()<<',';
            for (auto id:r.ids) csv<<id<<';';
            csv<<'\n';
        }
        if (diagnostics) {
            std::ofstream trace(prefix+"-release.csv");
            trace<<"k,wait_enter_ns,sleep_return_ns,spin_begin_ns,spin_exit_ns,probe_end_ns,max_poll_gap_ns,max_poll_end_ns,polls,thread_cpu_begin_ns,thread_cpu_end_ns,voluntary_before,voluntary_after,involuntary_before,involuntary_after\n";
            for(const auto& r:rows) if(r.k>=0) {
                const auto& t=r.releaseTrace;
                trace<<r.k<<','<<t.enter<<','<<t.wake<<','<<t.spinBegin<<','<<t.spinExit<<','<<t.probeEnd<<','
                    <<t.maxPollGap<<','<<t.maxPollEnd<<','<<t.polls<<','<<t.cpuBegin<<','<<t.cpuEnd<<','
                    <<t.voluntaryBefore<<','<<t.voluntaryAfter<<','<<t.involuntaryBefore<<','<<t.involuntaryAfter<<'\n';
            }
        }
        if (fixed && kind!="plain") {
            std::ofstream backend(prefix+"-backend.csv");
            backend<<"round,k,threads_before_T,threads_after_T,threads_after_B,loop_processed,loop_corrected,maps_merged,gba_completed\n";
            for (const auto& r:rows) {
                backend<<r.round<<','<<r.k<<','<<r.threadsBeforeT<<','<<r.threadsAfterT<<','<<r.threadsAfterB;
                for (auto n:r.backendCounts) backend<<','<<n;
                backend<<'\n';
            }
        }
        if(workloadDiagnostics) {
            std::ofstream workload(prefix+"-workload.csv");
            workload<<"k,probe_before_begin_ns,probe_before_end_ns,probe_after_begin_ns,probe_after_end_ns,process_cpu_before_T_ns,process_cpu_after_T_ns,coordinator_voluntary_before,coordinator_voluntary_after,coordinator_involuntary_before,coordinator_involuntary_after,before_keypoints,before_point_slots,before_nonnull_points,after_keypoints,after_point_slots,after_nonnull_points\n";
            for(const auto& r:rows) {
                workload<<r.k<<','<<r.probeBeforeBegin<<','<<r.probeBeforeEnd<<','<<r.probeAfterBegin<<','<<r.probeAfterEnd<<','
                    <<r.processCpuBeforeT<<','<<r.processCpuAfterT<<','<<r.voluntaryBeforeT<<','<<r.voluntaryAfterT<<','<<r.involuntaryBeforeT<<','<<r.involuntaryAfterT;
                for(auto v:r.workloadBefore) workload<<','<<v;
                for(auto v:r.workloadAfter) workload<<','<<v;
                workload<<'\n';
            }
            if(!workload) throw std::runtime_error("workload log write failed");
        }
        if(trackingDiagnostics) {
            std::ofstream log(prefix+"-tracking.csv");
            const char* names[]={"extraction","stereo_match","initialization","pose_prediction","local_update","local_search","local_optimize","keyframe"};
            log<<"round,k,context_begin_ns,context_end_ns,read_begin_ns,read_end_ns,map_id,map_points,map_keyframes,before_keypoints,before_point_slots,before_nonnull_points,before_state,pending_reset";
            log<<",work_control,work_mode,keyframe_budget,point_budget,local_keyframes,local_points,point_slots_visited,observation_votes,ref_raw,ref_eligible,ref_used,match_inliers,close_tracked,close_untracked,keyframe_flags,projection_reference,projection_matched_slots,keyframe_period,keyframe_request,extraction_cell_cap,extraction_cells,extraction_candidates,extraction_retained,extraction_capped_cells,extraction_retained_cell_max";
            for(auto name:names) log<<','<<name<<"_ns,"<<name<<"_begin_ns,"<<name<<"_end_ns,"<<name<<"_calls";
            log<<'\n';
            for(const auto& r:rows) {
                const auto& c=r.context;
                log<<r.round<<','<<r.k<<','<<r.contextBegin<<','<<r.contextEnd<<','<<r.stagesReadBegin<<','<<r.stagesReadEnd<<','
                   <<c.mapId<<','<<c.mapPoints<<','<<c.mapKeyframes<<','<<c.keypoints<<','<<c.pointSlots<<','<<c.nonnullPoints<<','<<c.state<<','<<c.pendingReset;
                log<<','<<workControl<<','<<r.workMode<<','<<r.keyframeBudget<<','<<r.pointBudget
                   <<','<<r.stages.localKeyframes<<','<<r.stages.localPoints<<','<<r.stages.pointSlotsVisited<<','<<r.stages.observationVotes<<','<<r.stages.refRaw<<','<<r.stages.refEligible<<','<<r.stages.refUsed
                   <<','<<r.stages.inliers<<','<<r.stages.closeTracked<<','<<r.stages.closeUntracked<<','<<r.stages.keyframeFlags<<','<<r.stages.projectionReference<<','<<r.stages.projectionMatchedSlots<<','<<keyframePeriod<<','<<r.keyframeRequest
                   <<','<<extractionCellCandidates<<','<<r.stages.extractionCells<<','<<r.stages.extractionCandidates<<','<<r.stages.extractionRetained<<','<<r.stages.extractionCappedCells<<','<<r.stages.extractionRetainedCellMax;
                for(unsigned j=0;j<8;++j) log<<','<<r.stages.ns[j]<<','<<r.stages.begin[j]<<','<<r.stages.end[j]<<','<<r.stages.calls[j];
                log<<'\n';
            }
            if(!log) throw std::runtime_error("tracking log write failed");
        }
        if(trackingDiagnostics) {
            std::ofstream log(prefix+"-backend-stages.csv");
            const char* names[]={"insert","cull_points","create_points","fuse","local_ba","cull_keyframes","loop"};
            log<<"round,k,ba_calls,ba_keyframes_max,ba_points_max,ba_edges_max,ba_fixed_keyframes_max,ba_fixed_candidates_max,ba_dropped_points_max,ba_anchor_rejects,fuse_targets_max,cull_candidates_max,cull_selected_max,gba_calls,gba_requested_max,gba_actual_max,gba_iteration_errors,gba_optimization_ns";
            for(auto name:names) log<<','<<name<<"_ns,"<<name<<"_begin_ns,"<<name<<"_end_ns,"<<name<<"_calls";
            log<<'\n';
            for(const auto& row:rows) {
                const auto& r=row.backendStages;
                log<<row.round<<','<<row.k<<','<<r.baCalls<<','<<r.baKeyframesMax<<','<<r.baPointsMax<<','<<r.baEdgesMax<<','<<r.baFixedKeyframesMax<<','<<r.baFixedCandidatesMax<<','<<r.baDroppedPointsMax<<','<<r.baAnchorRejects<<','<<r.fuseTargetsMax<<','<<r.cullCandidatesMax<<','<<r.cullSelectedMax<<','<<r.globalBACalls<<','<<r.globalBARequestedMax<<','<<r.globalBAActualMax<<','<<r.globalBAIterationErrors<<','<<r.globalBAOptimizationNs;
                for(unsigned j=0;j<7;++j) log<<','<<r.ns[j]<<','<<r.begin[j]<<','<<r.end[j]<<','<<r.calls[j];
                log<<'\n';
            }
            if(!log) throw std::runtime_error("backend stage log write failed");
        }
        std::ofstream online(prefix+"-online.csv");
        online<<"k,timestamp_s,state,x,y,z\n"<<std::setprecision(17);
        for(const auto& r:rows) online<<r.k<<','<<r.sensorTime<<','<<r.state<<','
            <<r.position.x()<<','<<r.position.y()<<','<<r.position.z()<<'\n';
        summary<<"{\"status\":\"passed\",\"fixed\":"<<(fixed?"true":"false")
            <<",\"kind\":\""<<kind<<"\",\"evaluated\":"<<evaluated
            <<",\"initialization_frame\":"<<initializedAt<<",\"empty_rounds\":"<<emptyRounds
            <<",\"keyframes_processed\":"<<keyframes<<",\"invalid_pose_frames\":"<<invalid
            <<",\"self_checks\":"<<checks<<",\"evaluation_elapsed_ns\":"<<end-begin
            <<",\"threads_at_evaluation_start\":"<<threadsAtStart<<",\"threads_at_evaluation_end\":"<<threadsAtEnd
            <<",\"prepare_before_wait\":"<<prepareBeforeWait
            <<",\"work_control\":"<<workControl<<",\"policy_seed\":"<<policySeed<<",\"keyframe_period\":"<<keyframePeriod<<",\"maintenance_keyframes\":"<<maintenanceKeyframes<<",\"backend_keyframes\":"<<backendKeyframes<<",\"backend_points\":"<<backendPoints<<",\"backend_fixed_keyframes\":"<<fixedKeyframes<<",\"global_ba_iterations\":"<<globalIterations<<",\"defer_routine_keyframes\":"<<deferRoutine
            <<",\"tracking_diagnostics\":"<<trackingDiagnostics
            <<",\"workload_diagnostics\":"<<workloadDiagnostics
            <<",\"release_diagnostics\":"<<diagnostics
            <<",\"period_ns\":"<<h<<",\"spin_ns\":"<<spin<<",\"offset\":"<<offset
            <<",\"preload_limit\":"<<preloadLimit<<",\"initialization_limit\":"<<initialLimit
            <<",\"evaluation_cpu_ns\":"<<cpuEnd-cpuBegin
            <<",\"opencv_threads_before\":"<<cvBefore<<",\"opencv_threads_after\":"<<cvAfter
            <<",\"eigen_threads_before\":"<<eigenBefore<<",\"eigen_threads_after\":"<<eigenAfter
            <<",\"clock_pair_min_ns\":"<<clockMin<<",\"clock_pair_max_ns\":"<<clockMax<<"}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"REPLAY ERROR: "<<error.what()<<'\n';
        summary<<"{\"status\":\"error\",\"evaluated\":"<<evaluated<<"}\n";
        return 1;
    }
}
