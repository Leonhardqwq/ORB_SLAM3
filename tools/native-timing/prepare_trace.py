"""Create an isolated, optionally traced native ORB-SLAM3 source tree."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

HEADER = r'''#pragma once
#include <cstdint>
#include <string>
namespace NativeTrace {
bool enabled();
long long now();
void event(const char* kind, long long id=-1, long long aux=-1, long long map=-1, long long stamp=0);
void flush();
struct Span {
    const char* name; long long id, aux; bool on;
    Span(const char* n,long long i=-1,long long a=-1,long long start=0):name(n),id(i),aux(a),on(enabled()) {
        if(on) event((std::string(name)+"_begin").c_str(),id,aux,-1,start);
    }
    ~Span() { if(on) event((std::string(name)+"_end").c_str(),id,aux); }
};
}
'''
SOURCE = r'''#include "NativeTrace.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <sys/syscall.h>
#include <unistd.h>
namespace NativeTrace {
struct Sink {
    std::mutex mutex; FILE* file=nullptr; unsigned count=0;
    Sink() {
        const char* path=std::getenv("ORB_NATIVE_TRACE");
        if(path && *path) { file=std::fopen(path,"w"); if(file) std::fprintf(file,"ns,thread,event,id,aux,map\n"); }
    }
};
Sink& sink() { static Sink* p=new Sink(); return *p; }
bool enabled() { static const bool on=[](){ const char* p=std::getenv("ORB_NATIVE_TRACE"); return p&&*p; }(); return on; }
long long now() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
void event(const char* kind,long long id,long long aux,long long map,long long stamp) {
    if(!enabled()) return;
    if(!stamp) stamp=now();
    auto& s=sink(); std::lock_guard<std::mutex> guard(s.mutex);
    if(s.file) { std::fprintf(s.file,"%lld,%ld,%s,%lld,%lld,%lld\n",stamp,syscall(SYS_gettid),kind,id,aux,map);
        if(++s.count%256==0) std::fflush(s.file); }
}
void flush() { if(!enabled()) return; auto& s=sink(); std::lock_guard<std::mutex> guard(s.mutex); if(s.file) std::fflush(s.file); }
}
'''


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    shutil.copytree(a.base,a.output,ignore=shutil.ignore_patterns('build','.git','*.o'))
    before={}
    def edit(name,old,new,count=1):
        p=a.output/name;s=p.read_text();before.setdefault(name,hashlib.sha256(s.encode()).hexdigest())
        if s.count(old)!=count: raise ValueError(f'{name}: expected {count} copies of {old[:70]!r}, found {s.count(old)}')
        p.write_text(s.replace(old,new))
    for name in ['System','Tracking','Frame','LocalMapping','LoopClosing','Map']:
        p=a.output/f'src/{name}.cc';s=p.read_text();before[str(p.relative_to(a.output))]=hashlib.sha256(s.encode()).hexdigest()
        s=s.replace('#include', '#include "NativeTrace.h"\n#include',1);p.write_text(s)
    (a.output/'include/NativeTrace.h').write_text(HEADER)
    (a.output/'src/NativeTrace.cc').write_text(SOURCE)
    edit('CMakeLists.txt','src/System.cc','src/System.cc\nsrc/NativeTrace.cc')
    edit('src/Tracking.cc','    Track();\n    //cout << "Tracking end"',
         '    NativeTrace::event("frame_identity", mCurrentFrame.mnId, -1);\n    Track();\n    //cout << "Tracking end"')
    for signature,name in [('void Tracking::Track()','tracking'),('bool Tracking::TrackReferenceKeyFrame()','reference'),
                           ('bool Tracking::TrackWithMotionModel()','motion'),('bool Tracking::TrackLocalMap()','local_track'),
                           ('bool Tracking::Relocalization()','relocalize'),('void Tracking::CreateNewKeyFrame()','new_keyframe')]:
        edit('src/Tracking.cc',signature+'\n{',signature+'\n{\n    NativeTrace::Span ntSpan("'+name+'", mCurrentFrame.mnId);')
    edit('src/Tracking.cc','    unique_lock<mutex> lock(pCurrentMap->mMutexMapUpdate);',
         '    auto ntWaitStart=NativeTrace::enabled()?NativeTrace::now():0;\n    unique_lock<mutex> lock(pCurrentMap->mMutexMapUpdate);\n'
         '    NativeTrace::event("map_wait_begin",mCurrentFrame.mnId,-1,pCurrentMap->GetId(),ntWaitStart);\n'
         '    NativeTrace::event("map_wait_end",mCurrentFrame.mnId,-1,pCurrentMap->GetId());\n'
         '    NativeTrace::Span ntMapHeld("map_held",mCurrentFrame.mnId,pCurrentMap->GetId());')
    edit('src/Tracking.cc','    int nCurMapChangeIndex = pCurrentMap->GetMapChangeIndex();',
         '    int nCurMapChangeIndex = pCurrentMap->GetMapChangeIndex();\n'
         '    NativeTrace::event("map_seen",mCurrentFrame.mnId,nCurMapChangeIndex,pCurrentMap->GetId());')
    edit('src/Frame.cc','void Frame::ExtractORB(int flag, const cv::Mat &im, const int x0, const int x1)\n{',
         'void Frame::ExtractORB(int flag, const cv::Mat &im, const int x0, const int x1)\n{\n    NativeTrace::Span ntExtract("extract",mnId,flag);')
    edit('src/Frame.cc','void Frame::ComputeStereoMatches()\n{',
         'void Frame::ComputeStereoMatches()\n{\n    NativeTrace::Span ntStereo("stereo_match",mnId);')
    edit('src/LocalMapping.cc','            ProcessNewKeyFrame();',
         '            auto ntLMStart=NativeTrace::enabled()?NativeTrace::now():0;\n            ProcessNewKeyFrame();\n'
         '            NativeTrace::Span ntLM("local_mapping",mpCurrentKeyFrame->mnId,mpCurrentKeyFrame->mnFrameId,ntLMStart);')
    edit('src/LocalMapping.cc','    mlNewKeyFrames.push_back(pKF);',
         '    mlNewKeyFrames.push_back(pKF);\n    NativeTrace::event("lm_enqueue",pKF->mnId,pKF->mnFrameId,pKF->GetMap()->GetId());')
    edit('src/LocalMapping.cc','        mlNewKeyFrames.pop_front();',
         '        mlNewKeyFrames.pop_front();\n        NativeTrace::event("lm_dequeue",mpCurrentKeyFrame->mnId,mpCurrentKeyFrame->mnFrameId,mpCurrentKeyFrame->GetMap()->GetId());')
    edit('src/LocalMapping.cc','                        Optimizer::LocalBundleAdjustment(mpCurrentKeyFrame,&mbAbortBA, mpCurrentKeyFrame->GetMap(),num_FixedKF_BA,num_OptKF_BA,num_MPs_BA,num_edges_BA);',
         '                        { NativeTrace::Span ntBA("local_ba",mpCurrentKeyFrame->mnId,mpCurrentKeyFrame->mnFrameId);\n'
         '                        Optimizer::LocalBundleAdjustment(mpCurrentKeyFrame,&mbAbortBA, mpCurrentKeyFrame->GetMap(),num_FixedKF_BA,num_OptKF_BA,num_MPs_BA,num_edges_BA); }')
    edit('src/LoopClosing.cc','    if(pKF->mnId!=0)\n        mlpLoopKeyFrameQueue.push_back(pKF);',
         '    if(pKF->mnId!=0) {\n        mlpLoopKeyFrameQueue.push_back(pKF);\n        NativeTrace::event("lc_enqueue",pKF->mnId,pKF->mnFrameId,pKF->GetMap()->GetId());\n    }')
    edit('src/LoopClosing.cc','        mlpLoopKeyFrameQueue.pop_front();',
         '        mlpLoopKeyFrameQueue.pop_front();\n        NativeTrace::event("lc_dequeue",mpCurrentKF->mnId,mpCurrentKF->mnFrameId,mpCurrentKF->GetMap()->GetId());')
    edit('src/LoopClosing.cc','            bool bFindedRegion = NewDetectCommonRegions();',
         '            auto ntLCStart=NativeTrace::enabled()?NativeTrace::now():0;\n            bool bFindedRegion = NewDetectCommonRegions();\n'
         '            NativeTrace::Span ntLC("loop_closing",mpCurrentKF?mpCurrentKF->mnId:0,mpCurrentKF?mpCurrentKF->mnFrameId:0,ntLCStart);')
    edit('src/LoopClosing.cc','void LoopClosing::CorrectLoop()\n{',
         'void LoopClosing::CorrectLoop()\n{\n    NativeTrace::Span ntCorrect("loop_correct",mpCurrentKF->mnId,mpCurrentKF->mnFrameId);')
    edit('src/LoopClosing.cc','void LoopClosing::RunGlobalBundleAdjustment(Map* pActiveMap, unsigned long nLoopKF)\n{',
         'void LoopClosing::RunGlobalBundleAdjustment(Map* pActiveMap, unsigned long nLoopKF)\n{\n    NativeTrace::Span ntGBA("global_ba",nLoopKF,pActiveMap->GetId());')
    anchor='void Map::IncreaseChangeIndex()\n{\n    unique_lock<mutex> lock(mMutexMap);\n    mnMapChange++;'
    edit('src/Map.cc',anchor,anchor+'\n    NativeTrace::event("map_publish",mnMapChange,-1,mnId);')
    tools=a.output.parent/'tools'
    tools.mkdir(exist_ok=True)
    original=Path(__file__).parent
    shutil.copy2(original/'CMakeLists.txt',tools/'CMakeLists.txt')
    harness=(original/'native_kitti.cc').read_text()
    harness=harness.replace('#include <System.h>','#include <System.h>\n#include "NativeTrace.h"')
    harness=harness.replace('    const auto epoch=Clock::now();','    const auto epoch=Clock::now();\n    NativeTrace::event("epoch",-1,-1,-1,std::chrono::duration_cast<std::chrono::nanoseconds>(epoch.time_since_epoch()).count());')
    anchor='        const auto end=Clock::now();'
    events=''
    for label,var in [('input_begin','readBegin'),('input_end','readEnd'),('call_begin','begin'),('call_end','end')]:
        events+='\n        NativeTrace::event("'+label+'",i,-1,-1,std::chrono::duration_cast<std::chrono::nanoseconds>('+var+'.time_since_epoch()).count());'
    harness=harness.replace(anchor,anchor+events)
    harness=harness.replace('    slam.Shutdown();','    slam.Shutdown();\n    NativeTrace::flush();')
    (tools/'native_kitti.cc').write_text(harness)
    manifest={name:{'base':h,'traced':hashlib.sha256((a.output/name).read_bytes()).hexdigest()} for name,h in before.items()}
    (a.output/'native-trace-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Prepared isolated trace source',a.output)


if __name__=='__main__':main()
