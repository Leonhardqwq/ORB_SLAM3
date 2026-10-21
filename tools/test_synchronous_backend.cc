// Regression for the optional synchronous lifecycle; no synthetic SLAM results.
#include "LocalMapping.h"
#include "LoopClosing.h"
#include <iostream>
#include <stdexcept>
static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
int main() {
    try {
        ORB_SLAM3::LocalMapping mapper(nullptr,nullptr,0.0f,false,"");
        mapper.SetSynchronous(true);
        require(mapper.ProcessRound(0).empty(),"empty round failed");
        require(!mapper.isFinished(),"synchronous mapper still marked finished");
        mapper.StopForLoopCorrection();
        require(mapper.isStopped(),"mapper did not stop at safe boundary");
        // GBA may request the same stop again before map commit.
        mapper.StopForLoopCorrection();
        mapper.Release();
        require(!mapper.isStopped() && !mapper.stopRequested(),"mapper did not release");
        mapper.Release();
        mapper.ProcessRound(1);
        mapper.RequestFinish();
        bool rejected=false;
        try {mapper.ProcessRound(2);} catch(const std::logic_error&) {rejected=true;}
        require(rejected,"finish request was ignored");
        mapper.FinishSynchronously();
        require(mapper.isFinished(),"finish did not complete");
        ORB_SLAM3::LocalMapping native(nullptr,nullptr,0.0f,false,"");
        native.StopForLoopCorrection();
        require(native.stopRequested() && !native.isStopped(),"native async stop semantics changed");
        ORB_SLAM3::LoopClosing loop(nullptr,nullptr,nullptr,true,false);
        loop.SetSynchronous(true);loop.ProcessRound();
        require(!loop.isFinished(),"synchronous loop still marked finished");
        loop.RequestReset();loop.ProcessRound();
        loop.RequestFinish();rejected=false;
        try {loop.ProcessRound();} catch(const std::logic_error&) {rejected=true;}
        require(rejected,"loop finish request was ignored");
        loop.FinishSynchronously();require(loop.isFinished(),"loop did not finish");
        std::cout<<"synchronous lifecycle regression passed\n";return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
