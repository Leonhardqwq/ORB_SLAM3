// Real-image lifecycle exercise, not a timed reliability or trajectory experiment.
#include "System.h"
#include <opencv2/imgcodecs.hpp>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <string>
int main(int argc,char** argv) {
    if(argc!=7) {std::cerr<<"VOC SETTINGS DATA TIMES FRAMES active|full\n";return 2;}
    try {
        cv::setNumThreads(1);Eigen::setNbThreads(1);
        std::ifstream input(argv[4]);std::vector<std::string> stamps;std::string line;
        while(input>>line) stamps.push_back(line);
        const unsigned long n=std::stoul(argv[5]);
        if(stamps.size()<n+3) throw std::runtime_error("insufficient images");
        const std::string kind=argv[6];
        if(kind!="active" && kind!="full") throw std::runtime_error("invalid reset kind");
        ORB_SLAM3::System slam(argv[1],argv[2],ORB_SLAM3::System::STEREO,false);
        if(!slam.IsFixedStereo()) throw std::runtime_error("fixed mode required");
        auto track=[&](unsigned long i) {
            const std::string base=argv[3];
            auto left=cv::imread(base+"/mav0/cam0/data/"+stamps[i]+".png",cv::IMREAD_UNCHANGED);
            auto right=cv::imread(base+"/mav0/cam1/data/"+stamps[i]+".png",cv::IMREAD_UNCHANGED);
            return slam.TrackStereoFixed(i,left,right,std::stod(stamps[i])/1e9);
        };
        for(unsigned long i=0;i<n;++i) {track(i);slam.CompleteMappingRound(i);}
        const auto counts=slam.FixedBackendCounts();
        if(counts[1]==0 || counts[3]==0) throw std::runtime_error("real loop/GBA branch not exercised");
        std::cout<<"BEFORE_RESET corrections="<<counts[1]<<" gba="<<counts[3]<<std::endl;
        if(kind=="active") slam.ResetActiveMap(); else slam.Reset();
        track(n);slam.CompleteMappingRound(n);
        track(n+1);slam.CompleteMappingRound(n+1);
        track(n+2); // Shutdown must complete this pending B, then close.
        slam.Shutdown();slam.Shutdown();
        bool rejected=false;
        try {slam.CompleteMappingRound(n+2);} catch(const std::logic_error&) {rejected=true;}
        if(!rejected) throw std::runtime_error("closed API accepted work");
        std::cout<<"REAL_LOOP_LIFECYCLE_PASSED reset="<<kind<<std::endl;
        return 0;
    } catch(const std::exception& e) {std::cerr<<"LIFECYCLE ERROR: "<<e.what()<<std::endl;return 1;}
}
