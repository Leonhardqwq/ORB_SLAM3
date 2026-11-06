cmake_minimum_required(VERSION 3.10)
project(native_timing LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 11)
if(NOT ORB_SOURCE)
  message(FATAL_ERROR "Pass -DORB_SOURCE=/absolute/path/to/untouched/native/source")
endif()
find_package(OpenCV 4.4 REQUIRED)
find_package(Eigen3 3.1 REQUIRED)
find_package(Pangolin REQUIRED)
add_executable(native_kitti native_kitti.cc)
target_compile_options(native_kitti PRIVATE -O3 -march=native)
target_include_directories(native_kitti PRIVATE ${ORB_SOURCE} ${ORB_SOURCE}/include
  ${ORB_SOURCE}/include/CameraModels ${ORB_SOURCE}/Thirdparty/Sophus
  ${EIGEN3_INCLUDE_DIR} ${Pangolin_INCLUDE_DIRS} ${OpenCV_INCLUDE_DIRS})
target_link_libraries(native_kitti PRIVATE ${ORB_SOURCE}/lib/libORB_SLAM3.so
  ${OpenCV_LIBS} ${Pangolin_LIBRARIES} pthread)
