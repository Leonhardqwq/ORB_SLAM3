// Runtime contracts, including real feature-empty early return; no data fitting.
#include "System.h"
#include <cassert>
#include <thread>
#include <stdexcept>
using namespace ORB_SLAM3;
int main(int argc,char** argv) {
    if(argc!=3) return 2;
    System slam(argv[1],argv[2],System::STEREO,false);
    assert(slam.IsFixedStereo());
    auto context=slam.FixedTrackingContext();assert(context.mapPoints==0 && context.nonnullPoints==0);
    bool rejected=false;
    try { slam.FixedTrackingStages(); } catch(const std::logic_error&) {rejected=true;}
    assert(rejected);
    bool otherRejected=false;
    std::thread other([&] {try {slam.SetFixedTrackingDiagnostics(true);}catch(const std::logic_error&) {otherRejected=true;}});
    other.join();assert(otherRejected);
    otherRejected=false;
    std::thread wrong([&] {try {slam.SetFixedWorkPolicy(true,16,1200);}catch(const std::logic_error&) {otherRejected=true;}});
    wrong.join();assert(otherRejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,1,1200);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(false,16,1200);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(false,0,0,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,16,0,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    slam.SetFixedWorkPolicy(true,16,1200,true);
    rejected=false;try {slam.SetFixedWorkPolicy(true,16,1200,true,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(false,0,0,false,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,16,0,false,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    slam.SetFixedWorkPolicy(true,16,1200,false,true);
    rejected=false;try {slam.SetFixedWorkPolicy(false,0,0,false,false,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(false,0,0,false,false,false,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,32,2400,false,false,false,true);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    slam.SetFixedWorkPolicy(true,32,2400,true,false,true,true);
    rejected=false;try {slam.SetFixedBackendBudget(1,2400);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(8,0);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    otherRejected=false;
    std::thread wrongBackend([&] {try {slam.SetFixedBackendBudget(8,2400);}catch(const std::logic_error&) {otherRejected=true;}});
    wrongBackend.join();assert(otherRejected);
    rejected=false;try {slam.SetFixedBackendBudget(0,0,8);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(8,2400,65);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(0,0,0,3);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(8,2400,8,11);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(0,0,0,0,4);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedBackendBudget(4,1200,8,10,65);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    slam.SetFixedBackendBudget(4,1200,8,10,4);
    slam.SetFixedBackendBudget(8,2400,8,3);
    rejected=false;try {slam.SetFixedWorkPolicy(true,32,2400,true,false,false,false,3);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,32,2400,true,false,false,false,257);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(false,0,0,false,false,false,false,16);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    if(!slam.SerialStereoFeatures()) {
        rejected=false;try {slam.SetFixedWorkPolicy(true,32,2400,true,false,false,false,16);}catch(const std::invalid_argument&) {rejected=true;}assert(rejected);
    } else slam.SetFixedWorkPolicy(true,32,2400,true,false,false,false,16);
    slam.SetFixedTrackingDiagnostics(true);
    cv::Mat blank(480,752,CV_8UC1,cv::Scalar(0));
    slam.TrackStereoFixed(0,blank,blank,1.0);
    auto record=slam.FixedTrackingStages();
    assert(record.calls[0]==1 && record.calls[1]==0 && record.calls[2]==1 && record.calls[3]==0);
    rejected=false;
    try {slam.FixedTrackingContext();}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    rejected=false;
    try {slam.SetFixedTrackingDiagnostics(false);}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.SetFixedWorkPolicy(true,32,2400);}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    assert(CurrentFixedWorkPolicy()==nullptr && CurrentFixedBackendPolicy()==nullptr);
    rejected=false;try {slam.SetFixedBackendBudget(0,0);}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    rejected=false;try {slam.FixedBackendStages();}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    assert(record.keyframeFlags==0);
    assert(slam.CompleteMappingRound(0).empty());
    auto backend=slam.FixedBackendStages();assert(backend.baCalls==0 && backend.calls[6]==1);
    assert(CurrentFixedBackendPolicy()==nullptr);
    slam.SetFixedBackendBudget(0,0);
    slam.SetFixedWorkPolicy(false);
    slam.SetFixedTrackingDiagnostics(false);
    slam.TrackStereoFixed(1,blank,blank,1.05);
    rejected=false;
    try {slam.FixedTrackingStages();}catch(const std::logic_error&) {rejected=true;}assert(rejected);
    slam.Shutdown();
}
