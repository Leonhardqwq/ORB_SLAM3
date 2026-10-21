// Paired-image extraction mechanism probe; excludes SLAM/map and image I/O.
#include "System.h"
#include "Settings.h"
#include "ORBextractor.h"
#include "TrackingDiagnostics.h"
#include <fstream>
#include <chrono>
#include <cassert>
using namespace ORB_SLAM3;
using Clock=std::chrono::steady_clock;
int main(int argc,char** argv) {
    if(argc!=7) return 2;
    const unsigned cap=std::stoul(argv[5]);const bool identity=std::stoi(argv[6]);
    if(cap!=0 && cap!=16) return 2;
    cv::setNumThreads(1);Eigen::setNbThreads(1);
    Settings settings(argv[1],System::STEREO);
    if(settings.needToResize()) throw std::runtime_error("Unexpected resizing");
    std::ifstream times(argv[3]);std::string stamp;
    std::vector<cv::Mat> left,right;std::vector<std::string> stamps;
    for(unsigned i=0;i<1600;++i) {
        if(!std::getline(times,stamp)) throw std::runtime_error("Short input");
        if(!stamp.empty() && stamp.back()=='\r') stamp.pop_back();
        if(i%20) continue;
        auto l=cv::imread(std::string(argv[2])+"/mav0/cam0/data/"+stamp+".png",0);
        auto r=cv::imread(std::string(argv[2])+"/mav0/cam1/data/"+stamp+".png",0);
        if(l.empty() || r.empty()) throw std::runtime_error("Missing image");
        if(settings.needToRectify()) {
            cv::Mat a,b;cv::remap(l,a,settings.M1l(),settings.M2l(),cv::INTER_LINEAR);
            cv::remap(r,b,settings.M1r(),settings.M2r(),cv::INTER_LINEAR);l=a;r=b;
        }
        left.push_back(l);right.push_back(r);stamps.push_back(stamp);
    }
    ORBextractor el(settings.nFeatures(),settings.scaleFactor(),settings.nLevels(),settings.initThFAST(),settings.minThFAST());
    ORBextractor er(settings.nFeatures(),settings.scaleFactor(),settings.nLevels(),settings.initThFAST(),settings.minThFAST());
    ORBextractor reference(settings.nFeatures(),settings.scaleFactor(),settings.nLevels(),settings.initThFAST(),settings.minThFAST());
    std::ofstream out(argv[4]);out<<"index,timestamp_ns,cap,ns,cells,candidates,retained,capped_cells,retained_max,left_features,right_features,identity\n";
    FixedWorkPolicy policy;policy.enabled=true;policy.extractionCellCandidates=cap;
    std::vector<int> lap={0,0};
    for(unsigned i=0;i<left.size();++i) {
        TrackingStageRecord rec;std::vector<cv::KeyPoint> kl,kr;cv::Mat dl,dr;
        long long ns;
        {
            ActiveFixedWorkPolicy ps(&policy);ActiveTrackingRecord rs(&rec);
            auto start=Clock::now();el(left[i],cv::Mat(),kl,dl,lap);er(right[i],cv::Mat(),kr,dr,lap);
            ns=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
        }
        bool equal=true;
        if(identity) {
            if(cap) throw std::runtime_error("Identity requires disabled cap");
            for(unsigned camera=0;camera<2;++camera) {
                std::vector<cv::KeyPoint> k;cv::Mat d;
                reference(camera?right[i]:left[i],cv::Mat(),k,d,lap);
                const auto& kk=camera?kr:kl;const auto& dd=camera?dr:dl;
                if(k.size()!=kk.size() || d.size()!=dd.size()) equal=false;
                else {
                    if(!d.empty() && cv::norm(d,dd,cv::NORM_INF)!=0) equal=false;
                    for(unsigned j=0;j<k.size();++j)
                        if(k[j].pt!=kk[j].pt || k[j].angle!=kk[j].angle || k[j].octave!=kk[j].octave || k[j].response!=kk[j].response) equal=false;
                }
            }
            if(!equal) throw std::runtime_error("Disabled path changed features");
        }
        if(cap && (rec.extractionRetainedCellMax>cap || rec.extractionRetained>cap*rec.extractionCells)) throw std::runtime_error("Cap violated");
        out<<i*20<<','<<stamps[i]<<','<<cap<<','<<ns<<','<<rec.extractionCells<<','<<rec.extractionCandidates<<','<<rec.extractionRetained<<','<<rec.extractionCappedCells<<','<<rec.extractionRetainedCellMax<<','<<kl.size()<<','<<kr.size()<<','<<(identity?1:0)<<'\n';
    }
    if(!out) throw std::runtime_error("Output failed");
}
