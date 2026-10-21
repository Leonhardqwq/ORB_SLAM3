// Identity/near-identity rotations must remain valid loop hypotheses.
#include "HornRotation.h"
#include <Eigen/Eigenvalues>
#include <cassert>
#include <limits>
#include <iostream>
using namespace ORB_SLAM3;
int main() {
    Eigen::Matrix3f r;
    // Deterministic reproduction of the original zero-angle division.
    Eigen::Vector3f zero=Eigen::Vector3f::Zero();
    const Eigen::Vector3f old=2*std::atan2(zero.norm(),1.f)*zero/zero.norm();
    assert(!old.allFinite());
    for(float sign:{-1.f,1.f}) {
        assert(HornQuaternionRotation(Eigen::Vector4f(sign,0,0,0),r));
        assert(r.isApprox(Eigen::Matrix3f::Identity(),1e-6f));
    }
    for(int i=0;i<1000;++i) {
        float angle=(i-500)*.006f;
        Eigen::Vector3f axis(1.f,2.f,.5f);axis.normalize();
        Eigen::Quaternionf q(Eigen::AngleAxisf(angle,axis));
        Eigen::Vector4f w(q.w(),q.x(),q.y(),q.z());
        assert(HornQuaternionRotation(w,r));
        assert(r.isApprox(q.toRotationMatrix(),1e-5f));
        assert((r*r.transpose()).isApprox(Eigen::Matrix3f::Identity(),1e-5f));
    }
    assert(HornQuaternionRotation(Eigen::Vector4f(1.f,1e-12f,0,0),r));
    assert(r.allFinite());
    assert(!HornQuaternionRotation(Eigen::Vector4f::Zero(),r));
    assert(!HornQuaternionRotation(Eigen::Vector4f(std::numeric_limits<float>::quiet_NaN(),0,0,0),r));
    std::cout<<"PASS: original identity NaN reproduced; both signs, 1000 rotations, tiny angle and invalid input checked\n";
}
