// GPL-3.0-or-later. Standalone timing probe: no ORB-SLAM3/OpenCV dependency.
#include <chrono>
#include <thread>
#include <fstream>
#include <iostream>
#include <vector>
#include <string>
#include <stdexcept>
#include <algorithm>
#include <ctime>
#include <unistd.h>
#include <sched.h>
#include <sys/resource.h>
using Clock=std::chrono::steady_clock;
using NS=std::chrono::nanoseconds;
using I=long long;
static I now(){return std::chrono::duration_cast<NS>(Clock::now().time_since_epoch()).count();}
static I raw(){timespec t;if(clock_gettime(CLOCK_MONOTONIC_RAW,&t))throw std::runtime_error("raw clock");return I(t.tv_sec)*1000000000+t.tv_nsec;}
static I cpu(){timespec t;if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))throw std::runtime_error("thread clock");return I(t.tv_sec)*1000000000+t.tv_nsec;}
struct R{I release=0,enter=0,wake=0,exit=0,start=0,end=0,maxGap=0,maxGapEnd=0,rawWake=0,rawExit=0,cpuWake=0,cpuExit=0;long involBefore=0,involAfter=0;int coreWake=-1,coreExit=-1;};
static void invol(long& n){rusage u;if(getrusage(RUSAGE_THREAD,&u))throw std::runtime_error("rusage");n=u.ru_nivcsw;}
static void wait(I release,I spin,int probes,R& r){
    if(!probes){std::this_thread::sleep_until(Clock::time_point(NS(release-spin)));if(spin)while(now()<release){}return;}
    r.enter=now();std::this_thread::sleep_until(Clock::time_point(NS(release-spin)));r.wake=now();
    r.rawWake=raw();r.cpuWake=cpu();invol(r.involBefore);r.coreWake=sched_getcpu();
    I last=now(),current=last;
    if(spin)do{current=now();if(current-last>r.maxGap){r.maxGap=current-last;r.maxGapEnd=current;}last=current;}while(current<release);
    r.exit=current;r.coreExit=sched_getcpu();invol(r.involAfter);r.cpuExit=cpu();r.rawExit=raw();
}
int main(int argc,char** argv){
    try{
        if(argc<2||(argc-2)%2)throw std::invalid_argument("usage: wait_isolation_probe PREFIX [--rounds N --spin-us N --work-us N --probes 0|1 --cpu N --start-file PATH]");
        std::string prefix=argv[1],startFile;int n=800,probes=0,core=-1;I h=50000000,spin=500000,work=0;
        for(int k=2;k<argc;k+=2){std::string opt=argv[k];if(opt=="--start-file"){startFile=argv[k+1];continue;}size_t used=0;std::string arg=argv[k+1];I v=std::stoll(arg,&used);if(used!=arg.size())throw std::invalid_argument("integer");
            if(opt=="--rounds"&&v>=1&&v<=10000)n=static_cast<int>(v);
            else if(opt=="--spin-us"&&v>=0&&v<=5000)spin=v*1000;
            else if(opt=="--work-us"&&v>=0&&v<=40000)work=v*1000;
            else if(opt=="--probes"&&v>=0&&v<=1)probes=static_cast<int>(v);
            else if(opt=="--cpu"&&v>=-1&&v<CPU_SETSIZE)core=static_cast<int>(v);
            else throw std::invalid_argument("option or range");}
        if(n<1||n>10000||spin<0||spin>5000000||work<0||work>40000000||probes<0||probes>1||core<-1||core>=CPU_SETSIZE)throw std::invalid_argument("range");
        if(core>=0){cpu_set_t cpus;CPU_ZERO(&cpus);CPU_SET(core,&cpus);if(sched_setaffinity(0,sizeof(cpus),&cpus))throw std::runtime_error("affinity");}
        std::vector<R> rows(n);unsigned long long value=1;
        std::ofstream ready(prefix+"-ready.json");if(!ready)throw std::runtime_error("output directory");ready<<"{\"pid\":"<<getpid()<<"}\n";ready.close();
        if(!startFile.empty()){I limit=now()+15000000000LL;while(access(startFile.c_str(),F_OK)){if(now()>limit)throw std::runtime_error("start timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
        I origin=now()+100000000,cpuStart=cpu(),before=now();
        for(int k=0;k<n;++k){auto& r=rows[k];r.release=origin+k*h;wait(r.release,spin,probes,r);r.start=now();
            if(work){I until=r.start+work;do{for(int j=0;j<1024;++j)value=value*2862933555777941757ULL+3037000493ULL;}while(now()<until);}
            r.end=now();}
        I after=now(),cpuEnd=cpu();std::ofstream csv(prefix+"-events.csv");if(!csv)throw std::runtime_error("csv output");
        csv<<"k,release_ns,wait_enter_ns,sleep_return_ns,spin_exit_ns,start_ns,end_ns,max_poll_gap_ns,max_poll_end_ns,raw_wake_ns,raw_exit_ns,cpu_wake_ns,cpu_exit_ns,invol_before,invol_after,cpu_wake,cpu_exit\n";
        for(int k=0;k<n;++k){auto&r=rows[k];csv<<k<<','<<r.release<<','<<r.enter<<','<<r.wake<<','<<r.exit<<','<<r.start<<','<<r.end<<','<<r.maxGap<<','<<r.maxGapEnd<<','<<r.rawWake<<','<<r.rawExit<<','<<r.cpuWake<<','<<r.cpuExit<<','<<r.involBefore<<','<<r.involAfter<<','<<r.coreWake<<','<<r.coreExit<<'\n';}
        std::ofstream summary(prefix+"-summary.json");summary<<"{\"status\":\"passed\",\"pid\":"<<getpid()<<",\"rounds\":"<<n<<",\"h_ns\":"<<h<<",\"spin_ns\":"<<spin<<",\"work_ns\":"<<work<<",\"probes\":"<<probes<<",\"affinity_cpu\":"<<core<<",\"cpu_ns\":"<<cpuEnd-cpuStart<<",\"wall_ns\":"<<after-before<<",\"checksum\":"<<value<<"}\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}
}
