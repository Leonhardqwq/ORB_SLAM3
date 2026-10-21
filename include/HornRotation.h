// Robust Horn-quaternion conversion; GPL-3.0-or-later.
#ifndef ORB_HORN_ROTATION_H
#define ORB_HORN_ROTATION_H
#include <Eigen/Core>
#include <Eigen/Geometry>
#include <cmath>
namespace ORB_SLAM3 {
inline bool HornQuaternionRotation(const Eigen::Vector4f& wxyz,Eigen::Matrix3f& rotation) {
    if(!wxyz.allFinite()) return false;
    const float norm=wxyz.norm();
    if(!(norm>0) || !std::isfinite(norm)) return false;
    const Eigen::Vector4f q=wxyz/norm;
    rotation=Eigen::Quaternionf(q[0],q[1],q[2],q[3]).toRotationMatrix();
    return rotation.allFinite();
}
}
#endif
