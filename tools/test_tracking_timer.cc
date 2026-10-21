// Standalone tests for default off, unwinding, TLS isolation and reused records.
#include "TrackingDiagnostics.h"
#include <cassert>
#include <thread>
#include <stdexcept>
using namespace ORB_SLAM3;
int main() {
    assert(CurrentFixedWorkPolicy()==nullptr);
    FixedWorkPolicy p;assert(!p.enabled && !p.keyframeRequest);p.enabled=true;p.keyframes=16;p.points=1200;
    assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,false,false,100));
    p.budgetReference=true;p.deferRoutineKeyframes=true;
    assert(ShouldDeferRoutineKeyframe(&p,true,true,true,false,false,75));
    assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,false,false,74));
    assert(!ShouldDeferRoutineKeyframe(&p,false,true,true,false,false,100));
    assert(!ShouldDeferRoutineKeyframe(&p,true,false,true,false,false,100));
    assert(!ShouldDeferRoutineKeyframe(&p,true,true,false,false,false,100));
    assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,true,false,100));
    assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,false,true,100));
    assert(!ShouldDeferRoutineKeyframe(nullptr,true,true,true,false,false,100));
    p.keyframeRequest=true;assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,false,false,100));
    p.keyframeRequest=false;p.enabled=false;assert(!ShouldDeferRoutineKeyframe(&p,true,true,true,false,false,100));
    p.enabled=true;p.budgetReference=false;p.deferRoutineKeyframes=false;
    try {
        ActiveFixedWorkPolicy scope(&p);assert(CurrentFixedWorkPolicy()==&p);
        std::thread other([] {assert(CurrentFixedWorkPolicy()==nullptr);});other.join();
        {ActiveFixedWorkPolicy nested(nullptr);assert(CurrentFixedWorkPolicy()==nullptr);}
        assert(CurrentFixedWorkPolicy()==&p);throw std::runtime_error("expected");
    } catch(const std::runtime_error&) {}
    assert(CurrentFixedWorkPolicy()==nullptr);
    FixedBackendPolicy bp;assert(bp.keyframes==0 && bp.points==0);
    BackendStageRecord br;assert(CurrentFixedBackendPolicy()==nullptr);
    { ActiveBackendScope scope(&bp,&br);
      std::thread other([] {assert(CurrentFixedBackendPolicy()==nullptr);});other.join();
      { ScopedBackendStage timer(BackendStage::LocalBA);timer.stop();timer.stop(); }
      RecordBackendWork(8,2400,9000);assert(br.calls[4]==1 && br.baCalls==1 && br.baKeyframesMax==8);
    }
    assert(CurrentFixedBackendPolicy()==nullptr);
    { ActiveBackendScope scope(&bp,&br);
      { ScopedGlobalBAOptimization measured(3);RecordGlobalBAIterations(2);
        std::thread other([] {RecordGlobalBAIterations(10);});other.join();
      }
      assert(br.globalBACalls==1 && br.globalBARequestedMax==3 && br.globalBAActualMax==2 && br.globalBAIterationErrors==0);
      RecordGlobalBAIterations(9);assert(br.globalBAActualMax==2);
      try {ScopedGlobalBAOptimization unwind(3);throw std::runtime_error("expected");}catch(const std::runtime_error&) {}
      RecordGlobalBAIterations(9);assert(br.globalBAActualMax==2);
      {ScopedGlobalBAOptimization failed(3);RecordGlobalBAIterations(-1);}
      assert(br.globalBAIterationErrors==1 && br.globalBAActualMax==2);
    }
    { ScopedBackendStage timer(BackendStage::Loop); }
    assert(br.calls[6]==0);
    { ActiveBackendScope scope(nullptr,&br);assert(br.baCalls==0 && br.calls[4]==0); }
    TrackingStageRecord r;
    { ScopedTrackingStage off(TrackingStage::Extraction); }
    assert(r.calls[0]==0);
    {
        ActiveTrackingRecord active(&r);
        { ScopedTrackingStage once(TrackingStage::Extraction);once.stop();once.stop(); }
        assert(r.calls[0]==1 && r.ns[0]>=0);
        std::thread other([] { ScopedTrackingStage ignored(TrackingStage::Extraction); });other.join();
        assert(r.calls[0]==1);
        try { ScopedTrackingStage unwind(TrackingStage::StereoMatch);throw std::runtime_error("expected"); }
        catch(const std::runtime_error&) {}
        assert(r.calls[1]==1);
    }
    { ScopedTrackingStage off(TrackingStage::Extraction); }
    assert(r.calls[0]==1);
    { ActiveTrackingRecord reset(&r);assert(r.calls[0]==0 && r.ns[1]==0); }
}
