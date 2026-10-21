// GPL-3.0-or-later. Explicit standalone image-processing co-load, no affinity.
#include <opencv2/opencv.hpp>
#include <chrono>
#include <thread>
#include <csignal>
#include <fstream>
#include <iostream>
#include <ctime>
static volatile std::sig_atomic_t stopRequested=0;
static void stop(int) { stopRequested=1; }
using Clock=std::chrono::steady_clock;
static long long ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}
int main(int argc,char** argv){
    if(argc!=4) return 2;
    cv::setNumThreads(1);
    cv::Mat input=cv::imread(argv[1],cv::IMREAD_GRAYSCALE),smooth,desc;
    if(input.empty()) return 2;
    std::ofstream out(argv[2]); if(!out) return 2;
    const int seconds=std::stoi(argv[3]);
    std::signal(SIGTERM,stop);std::signal(SIGINT,stop);
    auto orb=cv::ORB::create(1200);std::vector<cv::KeyPoint> keys;
    out<<"k,release_ns,start_ns,end_ns,keypoints\n";
    const auto origin=ns()+50000000;
    for(int k=0;k<seconds*20 && !stopRequested;++k){
        const auto release=origin+k*50000000LL;
        std::this_thread::sleep_until(Clock::time_point(std::chrono::nanoseconds(release)));
        if(stopRequested) break;
        auto start=ns();
        cv::GaussianBlur(input,smooth,cv::Size(5,5),1.2);
        orb->detectAndCompute(smooth,cv::noArray(),keys,desc);
        auto end=ns();
        out<<k<<','<<release<<','<<start<<','<<end<<','<<keys.size()<<'\n';
    }
    return 0;
}
