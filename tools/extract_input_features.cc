// Optional offline input characterization. GPL-3.0-or-later (ORB-SLAM3 tools).
// Not called by System, Tracking, or the timed replay. No look-ahead features.
#include <opencv2/opencv.hpp>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>
#include <string>
#include <vector>
int main(int argc, char** argv) {
  if(argc != 5) { std::cerr << "DATA TIMES OUTPUT COUNT\n"; return 2; }
  try {
    int count=std::stoi(argv[4]); if(count<=0) throw std::runtime_error("invalid count");
    std::ifstream existing(argv[3]); if(existing.good()) throw std::runtime_error("output exists");
    std::ifstream times(argv[2]); if(!times) throw std::runtime_error("missing timestamps");
    std::ofstream out(argv[3]); if(!out) throw std::runtime_error("output unavailable");
    out << "image_index,timestamp_ns,brightness,contrast,gradient,laplacian_variance,FAST_count,stereo_difference,previous_image_difference\n" << std::setprecision(17);
    cv::setNumThreads(1); cv::Mat previous; std::string stamp; int i=0;
    while(i<count && std::getline(times,stamp)) {
      if(!stamp.empty() && stamp.back()=='\r') stamp.pop_back();
      if(stamp.empty()) continue;
      if(stamp.find_first_not_of("0123456789")!=std::string::npos) throw std::runtime_error("invalid timestamp");
      auto l=cv::imread(std::string(argv[1])+"/mav0/cam0/data/"+stamp+".png",cv::IMREAD_GRAYSCALE);
      auto r=cv::imread(std::string(argv[1])+"/mav0/cam1/data/"+stamp+".png",cv::IMREAD_GRAYSCALE);
      if(l.empty()||r.empty()||l.size()!=r.size()) throw std::runtime_error("invalid stereo pair");
      cv::Mat small,rs,dx,dy,lap,diff; cv::resize(l,small,{188,120},0,0,cv::INTER_AREA);
      cv::resize(r,rs,small.size(),0,0,cv::INTER_AREA);
      cv::Scalar mean,sd,lm,ls; cv::meanStdDev(small,mean,sd);
      cv::Sobel(small,dx,CV_32F,1,0); cv::Sobel(small,dy,CV_32F,0,1);
      cv::Laplacian(small,lap,CV_32F); cv::meanStdDev(lap,lm,ls);
      std::vector<cv::KeyPoint> kp; cv::FAST(l,kp,20,true);
      cv::absdiff(small,rs,diff); double stereo=cv::mean(diff)[0];
      double motion=0; if(!previous.empty()){cv::absdiff(small,previous,diff);motion=cv::mean(diff)[0];}
      out<<i<<','<<stamp<<','<<mean[0]<<','<<sd[0]<<','<<(cv::mean(cv::abs(dx))[0]+cv::mean(cv::abs(dy))[0])/2
         <<','<<ls[0]*ls[0]<<','<<kp.size()<<','<<stereo<<','<<motion<<'\n';
      previous=small.clone(); ++i;
    }
    if(i!=count || !out) throw std::runtime_error("incomplete feature output");
    std::cout << "features=" << i << " OpenCV=" << CV_VERSION << '\n';
  } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
