// Regression fixture for correspondences observed by a covisible keyframe.
#include "Sim3Solver.h"
#include "Frame.h"
#include "Map.h"
#include "MapPoint.h"
#include "CameraModels/Pinhole.h"
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <memory>
using namespace ORB_SLAM3;
class InspectSolver:public Sim3Solver {
public:
    using Sim3Solver::Sim3Solver;
    int correspondences() const {return N;}
};
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    const int expected=std::atoi(argv[1]), n=8;
    Pinhole camera(std::vector<float>{100,100,50,50});
    Frame f;f.mnId=0;f.mTimeStamp=0;f.N=n;f.mbf=10;f.mb=.1;f.mThDepth=40;
    f.fx=f.fy=100;f.cx=f.cy=50;f.invfx=f.invfy=.01;
    f.mnMinX=f.mnMinY=0;f.mnMaxX=f.mnMaxY=100;
    f.mfGridElementWidthInv=f.mfGridElementHeightInv=1;
    f.mvKeysUn.assign(n,cv::KeyPoint(50,50,1));f.mvKeys=f.mvKeysUn;
    f.mvuRight.assign(n,-1);f.mvDepth.assign(n,4);f.mDescriptors=cv::Mat::zeros(n,32,CV_8U);
    f.mnScaleLevels=1;f.mfScaleFactor=1;f.mfLogScaleFactor=0;
    f.mvScaleFactors={1};f.mvLevelSigma2={1};f.mvInvLevelSigma2={1};
    f.mK_=Eigen::Matrix3f::Identity();f.mpORBvocabulary=nullptr;f.mnDataset=0;
    f.mpCamera=&camera;f.mpCamera2=nullptr;f.Nleft=f.Nright=-1;
    f.mvpMapPoints.assign(n,nullptr);f.SetPose(Sophus::SE3f());
    Map map(0);KeyFrame first(f,&map,nullptr),reference(f,&map,nullptr),observer(f,&map,nullptr);
    std::vector<std::unique_ptr<MapPoint>> owned;
    std::vector<MapPoint*> matches;
    for(int i=0;i<n;++i) {
        Eigen::Vector3f xyz(.1f*i,.1f*((i*i)%5),4+.2f*(i%3));
        owned.emplace_back(new MapPoint(xyz,&first,&map));auto p1=owned.back().get();
        p1->AddObservation(&first,i);first.AddMapPoint(p1,i);
        owned.emplace_back(new MapPoint(xyz,&observer,&map));auto p2=owned.back().get();
        p2->AddObservation(&observer,i);observer.AddMapPoint(p2,i);matches.push_back(p2);
    }
    InspectSolver provided(&first,&reference,matches,true,std::vector<KeyFrame*>(n,&observer));
    InspectSolver omitted(&first,&reference,matches,true);
    std::cout<<"provided_observer="<<provided.correspondences()<<" omitted="<<omitted.correspondences()<<std::endl;
    assert(provided.correspondences()==expected && omitted.correspondences()==0);
    if(expected==n) {
        provided.SetRansacParameters(.99,6,300);bool done=false,converged=false;std::vector<bool> inliers;int count=0;
        auto transform=provided.iterate(300,done,inliers,count,converged);
        assert(converged && count==n && transform.allFinite());
        assert((transform-Eigen::Matrix4f::Identity()).norm()<1e-4f);
        bool rejected=false;
        try {InspectSolver wrong(&first,&reference,matches,true,std::vector<KeyFrame*>(n-1,&observer));}
        catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
        InspectSolver missing(&first,&reference,matches,true,std::vector<KeyFrame*>(n,nullptr));
        assert(missing.correspondences()==0);
    }
    for(int i=0;i<n;++i) {matches[i]->AddObservation(&reference,i);reference.AddMapPoint(matches[i],i);}
    InspectSolver normal(&first,&reference,matches,true);
    assert(normal.correspondences()==n);
    std::cout<<"reference-only/default path preserved; all fixture checks passed"<<std::endl;
}
