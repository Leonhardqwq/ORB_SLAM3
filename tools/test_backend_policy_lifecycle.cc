// Real stereo frames exercise budgeted mapping across both reset APIs.
// This is an API/lifecycle regression, not timed or scored research evidence.
#include "System.h"
#include <opencv2/imgcodecs.hpp>
#include <fstream>
#include <string>
#include <cassert>
#include <stdexcept>
using namespace ORB_SLAM3;
int main(int argc,char** argv) {
    if(argc!=5) return 2;
    cv::setNumThreads(1);Eigen::setNbThreads(1);
    System slam(argv[1],argv[2],System::STEREO,false);
    assert(slam.IsFixedStereo());slam.SetFixedTrackingDiagnostics(true);
    std::ifstream input(argv[4]);std::string timestamp;unsigned count=0;uint64_t baCalls=0;
    while(count<80 && std::getline(input,timestamp)) {
        if(!timestamp.empty() && timestamp.back()=='\r') timestamp.pop_back();
        if(timestamp.empty()) continue;
        if(count==30) slam.ResetActiveMap();
        if(count==55) slam.Reset();
        slam.SetFixedWorkPolicy(true,32,2400,true,false,count%8==0);
        // Exercise the smallest allowed keyframe graph, not just the study cap.
        slam.SetFixedBackendBudget(2,1000,2);
        auto left=cv::imread(std::string(argv[3])+"/mav0/cam0/data/"+timestamp+".png",cv::IMREAD_GRAYSCALE);
        auto right=cv::imread(std::string(argv[3])+"/mav0/cam1/data/"+timestamp+".png",cv::IMREAD_GRAYSCALE);
        assert(!left.empty() && !right.empty());
        auto pose=slam.TrackStereoFixed(count,left,right,std::stod(timestamp)/1e9);
        assert(pose.matrix().allFinite());slam.CompleteMappingRound(count);
        auto b=slam.FixedBackendStages();assert(b.baKeyframesMax<=2 && b.baPointsMax<=1000);
        assert(b.fuseTargetsMax<=2 && b.cullSelectedMax<=2 && b.cullSelectedMax<=b.cullCandidatesMax);
        baCalls+=b.baCalls;++count;
        assert(CurrentFixedBackendPolicy()==nullptr);
    }
    assert(count==80 && baCalls>0 && slam.FixedResetCount()>=2);
    slam.SetFixedBackendBudget();slam.SetFixedWorkPolicy(false);
    slam.SetFixedTrackingDiagnostics(false);slam.Shutdown();
}
