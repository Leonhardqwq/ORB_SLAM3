// Native measurement harness derived from Examples/Stereo/stereo_kitti.cc.
// ORB-SLAM3 copyright 2017-2021 Carlos Campos et al., University of Zaragoza;
// ORB-SLAM2 copyright 2014-2016 Raul Mur-Artal et al. GPL-3.0-or-later.
// The linked algorithm and its concurrent backend are unchanged.
#include <System.h>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <chrono>
#include <thread>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>
#include <limits>
#include <unistd.h>

using Clock = std::chrono::steady_clock;
double seconds(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double>(a-b).count();
}

int main(int argc, char** argv) {
    if(argc != 8) {
        std::cerr << "native_kitti vocabulary config sequence upstream|periodic full|minimal max_frames output_dir\n";
        return 2;
    }
    const std::string seq=argv[3], mode=argv[4], observation=argv[5], out=argv[7];
    if((mode!="upstream" && mode!="periodic") || (observation!="full" && observation!="minimal")) return 2;
    std::ifstream times(seq+"/times.txt");
    std::vector<double> timestamps;
    double ts;
    while(times >> ts) timestamps.push_back(ts);
    if(timestamps.empty()) return 3;
    int n=timestamps.size(), cap=std::stoi(argv[6]);
    if(cap>0 && cap<n) n=cap;
    std::ofstream csv(out+"/frames.csv");
    csv << "frame,dataset_s,release_s,read_begin_s,read_end_s,track_begin_s,track_end_s,state,map_changed,probe_us,previous_write_us";
    for(int j=0;j<12;++j) csv << ",pose" << j;
    csv << '\n' << std::setprecision(12);
    if(!csv) return 4;
    ORB_SLAM3::System slam(argv[1],argv[2],ORB_SLAM3::System::STEREO,false);
    const float scale=slam.GetImageScale();
    const auto epoch=Clock::now();
    double previousWrite=0, totalWrite=0, totalProbe=0;
    for(int i=0;i<n;++i) {
        double release=timestamps[i]-timestamps[0];
        if(mode=="periodic")
            std::this_thread::sleep_until(epoch+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(release)));
        std::ostringstream name;
        name << std::setfill('0') << std::setw(6) << i << ".png";
        const auto readBegin=Clock::now();
        cv::Mat left=cv::imread(seq+"/image_0/"+name.str(),cv::IMREAD_UNCHANGED);
        cv::Mat right=cv::imread(seq+"/image_1/"+name.str(),cv::IMREAD_UNCHANGED);
        const auto readEnd=Clock::now();
        if(left.empty() || right.empty()) { csv.flush(); return 5; }
        if(scale!=1.f) {
            cv::Size shape(left.cols*scale,left.rows*scale);
            cv::resize(left,left,shape); cv::resize(right,right,shape);
        }
        const auto begin=Clock::now();
        auto tcw=slam.TrackStereo(left,right,timestamps[i]);
        const auto end=Clock::now();
        int state=-1, changed=-1;
        double pose[12];
        for(auto& x:pose) x=std::numeric_limits<double>::quiet_NaN();
        if(observation=="full") {
            state=slam.GetTrackingState();
            changed=slam.MapChanged();
            const auto twc=tcw.inverse().matrix();
            for(int r=0;r<3;++r) for(int c=0;c<4;++c) pose[4*r+c]=twc(r,c);
        }
        const auto probeEnd=Clock::now();
        const double probe=seconds(probeEnd,end)*1e6;
        totalProbe+=probe;
        csv << i << ',' << timestamps[i] << ',' << release << ',' << seconds(readBegin,epoch)
            << ',' << seconds(readEnd,epoch) << ',' << seconds(begin,epoch) << ',' << seconds(end,epoch)
            << ',' << state << ',' << changed << ',' << probe << ',' << previousWrite;
        for(auto x:pose) csv << ',' << x;
        csv << '\n';
        if(i%50==49) csv.flush();
        const auto writeEnd=Clock::now();
        previousWrite=seconds(writeEnd,probeEnd)*1e6;
        totalWrite+=previousWrite;
        if(mode=="upstream") {
            double interval=i+1<int(timestamps.size()) ? timestamps[i+1]-timestamps[i] : (i>0 ? timestamps[i]-timestamps[i-1] : 0);
            double call=seconds(end,begin);
            if(call<interval) usleep(static_cast<useconds_t>((interval-call)*1e6));
        }
    }
    const auto complete=Clock::now();
    csv.flush(); csv.close();
    // Online poses are already recorded; no post-hoc trajectory reconstruction.
    // Upstream Shutdown requests finish but does not join the backend threads.
    slam.Shutdown();
    std::ofstream meta(out+"/runner.json");
    meta << std::setprecision(12) << "{\"frames\":" << n << ",\"playback\":\"" << mode
         << "\",\"observation\":\"" << observation << "\",\"processing_wall_s\":" << seconds(complete,epoch)
         << ",\"probe_total_us\":" << totalProbe << ",\"csv_write_total_us\":" << totalWrite
         << ",\"viewer\":false,\"backend_drained\":false}\n";
    return 0;
}
