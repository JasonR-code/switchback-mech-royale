// Geometry for the Mech Royale map. All inputs and return values use map meters.
// Each Arena instance owns its terrain, solid prisms, and navigation graph.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <queue>
#include <vector>

namespace {
constexpr double cell = 0.5, stride = 4.0, bin_size = 16.0;
// Navigation stores clearance for progressively larger cylinders at hello. At a
// new cube count selecting a tier costs no graph rebuild or per-edge collision tests.
constexpr std::array<double,12> body_scales{1.,1.05,1.15,1.25,1.4,1.55,1.75,2.,2.5,3.,4.,8.};
constexpr float infinity = std::numeric_limits<float>::infinity();
struct Point { double x,y; };
struct Prism {
    double base,top,l=1e9,r=-1e9,b=1e9,t=-1e9;
    std::vector<std::vector<Point>> rings;
};
struct Slab { int next, id; };
struct Link { int to; float cost; bool climb; unsigned char clearance=0; };
struct Node {
    int x,y; float z, shelter=0;
    std::vector<Link> links;
    unsigned char clearance=0;
};
double squared(double x,double y) { return x*x+y*y; }
double cross(Point a,Point b,Point c) {
    return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
}
bool intersects(Point a,Point b,Point c,Point d) {
    if(std::max(a.x,b.x)<std::min(c.x,d.x) || std::max(c.x,d.x)<std::min(a.x,b.x)
      || std::max(a.y,b.y)<std::min(c.y,d.y) || std::max(c.y,d.y)<std::min(a.y,b.y)) return false;
    return cross(a,b,c)*cross(a,b,d)<=0 && cross(c,d,a)*cross(c,d,b)<=0;
}
bool inside(Point a,const Prism& p) {
    if(a.x<p.l || a.x>p.r || a.y<p.b || a.y>p.t) return false;
    bool in=false;
    for(auto& ring:p.rings) {
        Point v=ring.back();
        for(auto u:ring) {
            if((u.y>a.y)!=(v.y>a.y) && a.x<(v.x-u.x)*(a.y-u.y)/(v.y-u.y)+u.x) in=!in;
            v=u;
        }
    }
    return in;
}
struct Map {
    double l,b,r,t,ox,oy,step,rad,height,ledge,maxgrad;
    double base_radius,base_height;
    unsigned active_tier=0;
    int nx,ny,cx,cy,gx,gy,bx,by;
    std::vector<int16_t> terrain;
    std::vector<Prism> polys;
    std::vector<int> first;
    std::vector<Slab> slabs;
    std::vector<std::vector<int>> bins, sites;
    std::vector<Node> nodes;
    std::vector<int> route;
    std::vector<float> costs;
    std::vector<int> parent;
    size_t cursor=0;
    int last_goal=-1, reuse=0;
    std::array<double,12> last_threats{};
    int last_n=0;
    double last_climb=-1e6, climb_x=0, climb_y=0, climb_goal_x=0, climb_goal_y=0;
    Map(const double* a,const int16_t* terrain_data,int width,int h)
      :l(a[0]),b(a[1]),r(a[2]),t(a[3]),ox(a[4]),oy(a[5]),step(a[6]),
       rad(a[7]),height(a[8]),ledge(a[9]),maxgrad(std::tan(a[10]*0.01745329252)),nx(width),ny(h) {
        base_radius=rad; base_height=height;
        terrain.assign(terrain_data,terrain_data+nx*ny);
        cx=int(std::ceil((r-l)/cell))+1;cy=int(std::ceil((t-b)/cell))+1;
        gx=int(std::ceil((r-l)/stride));gy=int(std::ceil((t-b)/stride));
        bx=int(std::ceil((r-l)/bin_size))+1;by=int(std::ceil((t-b)/bin_size))+1;
        first.assign(cx*cy,-1);bins.resize(bx*by);sites.resize(gx*gy);
    }
    double ground(double x,double y) const {
        double u=std::clamp((x-ox)/step,0.,double(nx-1)), v=std::clamp((y-oy)/step,0.,double(ny-1));
        int i=std::min(int(u),nx-2), j=std::min(int(v),ny-2), k=j*nx+i;
        u-=i;v-=j;
        return .01*((1-v)*(terrain[k]+u*(terrain[k+1]-terrain[k]))
                    +v*(terrain[k+nx]+u*(terrain[k+nx+1]-terrain[k+nx])));
    }
    int col(double x,double y) const {
        int i=int((x-l)/cell),j=int((y-b)/cell);
        return (i<0||i>=cx||j<0||j>=cy)?-1:first[j*cx+i];
    }
    double surface(double x,double y,double z) const {
        double floor=ground(x,y);
        for(int k=col(x,y);k>=0;k=slabs[k].next) {
            double f=polys[slabs[k].id].top;
            if(f<=z+ledge+.015) floor=std::max(floor,f);
        }
        return floor;
    }
    bool free_column(double x,double y,double feet) const {
        for(int k=col(x,y);k>=0;k=slabs[k].next) {
            const auto& p=polys[slabs[k].id];
            if(p.top>feet+.07 && p.base<feet+height-.03) return false;
        }
        return true;
    }
    bool fits(double x,double y,double z,double radius) const {
        if (x<l+radius || x>r-radius || y<b+radius || y>t-radius || !free_column(x,y,z)) return false;
        // Raster precision is half a meter. Sample both the perimeter and the middle.
        constexpr double diag=.70710678118655;
        constexpr double dx[]={1,diag,0,-diag,-1,-diag,0,diag};
        constexpr double dy[]={0,diag,1,diag,0,-diag,-1,-diag};
        for(int i=0;i<8;i++)
            if(!free_column(x+radius*dx[i],y+radius*dy[i],z)) return false;
        return true;
    }
    unsigned clearance(double x,double y,double z,unsigned maximum) {
        // Search the monotone clearance of a complete cylinder. For normal
        // cube counts the largest rounding step is three cubes.
        unsigned lo=0,hi=maximum;
        while(lo<hi){
            unsigned mid=(lo+hi+1)/2;
            height=base_height*body_scales[mid];
            if(fits(x,y,z,base_radius*body_scales[mid]+.23)) lo=mid;
            else hi=mid-1;
        }
        height=base_height;
        return lo;
    }
    void set_body(double radius,double h){
        rad=radius; height=h;
        double scale=std::max(rad/base_radius,height/base_height);
        auto pos=std::lower_bound(body_scales.begin(),body_scales.end(),scale-1e-5);
        unsigned tier=std::min(size_t(pos-body_scales.begin()),body_scales.size()-1);
        if(tier!=active_tier){active_tier=tier;route.clear();last_climb=-1e6;}
    }
    void index_prism(int id) {
        const Prism& p=polys[id];
        for(int j=std::max(0,int((p.b-b)/bin_size));j<=std::min(by-1,int((p.t-b)/bin_size));j++)
            for(int i=std::max(0,int((p.l-l)/bin_size));i<=std::min(bx-1,int((p.r-l)/bin_size));i++)
                bins[j*bx+i].push_back(id);
        std::vector<double> cuts;
        int j0=std::max(0,int((p.b-b)/cell)),j1=std::min(cy-1,int((p.t-b)/cell));
        for(int j=j0;j<=j1;j++) {
            double y=b+(j+.5)*cell;
            cuts.clear();
            for(auto& ring:p.rings) {
                Point v=ring.back();
                for(auto u:ring) {
                    if((u.y>y)!=(v.y>y)) cuts.push_back((v.x-u.x)*(y-u.y)/(v.y-u.y)+u.x);
                    v=u;
                }
            }
            std::sort(cuts.begin(),cuts.end());
            for(size_t m=1;m<cuts.size();m+=2) {
                int i0=std::max(0,int(std::ceil((cuts[m-1]-l)/cell-.5)));
                int i1=std::min(cx,int(std::ceil((cuts[m]-l)/cell-.5)));
                for(int i=i0;i<i1;i++){
                    auto& head=first[j*cx+i];
                    slabs.push_back({head,id});
                    head=int(slabs.size()-1);
                }
            }
        }
    }
    bool clear(double x,double y,double z,double u,double v,double w) const {
        double dx=u-x,dy=v-y,dz=w-z;
        // Check all polygons in the crossed 16 m bins. Height-clipping first also
        // handles vertical shots through roofs and shots entirely inside a footprint.
        std::vector<unsigned char> seen(polys.size());
        const int i0=std::clamp(int((std::min(x,u)-l)/bin_size),0,bx-1), i1=std::clamp(int((std::max(x,u)-l)/bin_size),0,bx-1);
        const int j0=std::clamp(int((std::min(y,v)-b)/bin_size),0,by-1), j1=std::clamp(int((std::max(y,v)-b)/bin_size),0,by-1);
        for(int j=j0;j<=j1;j++) for(int i=i0;i<=i1;i++) for(int id:bins[j*bx+i]) {
            if(seen[id]) continue;
            seen[id]=1;
            const auto& p=polys[id];
            double lo=0,hi=1;
            auto clip=[&](double q,double d,double a,double h){
                if(std::abs(d)<1e-10) return q>=a && q<=h;
                double m=(a-q)/d,n=(h-q)/d;
                if(m>n) std::swap(m,n);
                lo=std::max(lo,m);hi=std::min(hi,n);return lo<=hi;
            };
            if(!clip(z,dz,p.base,p.top)||!clip(x,dx,p.l,p.r)||!clip(y,dy,p.b,p.t)) continue;
            Point a{x+dx*lo,y+dy*lo},e{x+dx*hi,y+dy*hi};
            if(inside(a,p)||inside(e,p)) return false;
            for(auto& ring:p.rings) {
                Point c=ring.back();
                for(auto d:ring) {if(intersects(a,e,c,d)) return false;c=d;}
            }
        }
        // At half-grid spacing the height error along a terrain ridge is small.
        int n=std::max(1,int(std::ceil(std::max(std::abs(dx),std::abs(dy))/(step*.5))));
        for(int k=0;k<=n;k++) {
            double s=double(k)/n;
            if(z+dz*s<ground(x+dx*s,y+dy*s)-.015) return false;
        }
        return true;
    }
    bool move(double x,double y,double z,double u,double v,double radius) const {
        double len=std::hypot(u-x,v-y);
        int n=std::max(1,int(std::ceil(len/.48)));
        double step_length=len/n, feet=z, old_ground=ground(x,y);
        // Descending past a lip temporarily keeps feet on the lip while the body
        // overhangs it. Once the complete cylinder clears it, use the lower support.
        for(int i=1;i<=n;i++) {
            double s=double(i)/n,a=x+(u-x)*s,b_=y+(v-y)*s;
            double floor=surface(a,b_,feet), terrain_z=ground(a,b_);
            if(floor<=terrain_z+.03 && feet<=old_ground+.12 &&
               terrain_z-old_ground>step_length*maxgrad+.016) return false;
            old_ground=terrain_z;
            if(floor-feet>std::max(ledge,step_length*maxgrad)+.03) return false;
            if(!fits(a,b_,floor,radius)) {
                if(floor<feet-.05 && fits(a,b_,feet,radius)) continue;
                // The server steps a cylinder onto a low ledge when its edge
                // touches, before its center reaches the higher footprint.
                double raised=std::max(floor,feet)+ledge;
                if(!fits(a,b_,raised,radius)) return false;
                feet=std::max(floor,feet);
            } else feet=floor;
        }
        return true;
    }
    double wx(int i)const{return l+(i+.5)*stride;}
    double wy(int j)const{return b+(j+.5)*stride;}
    void build(){
        for(int id=0;id<int(polys.size());id++) index_prism(id);
        for(int j=0;j<gy;j++)for(int i=0;i<gx;i++){
            double x=wx(i),y=wy(j);
            std::vector<double> heights{ground(x,y)};
            for(int k=col(x,y);k>=0;k=slabs[k].next) {
                double h=polys[slabs[k].id].top;
                if(h>heights[0]+.05) heights.push_back(h);
            }
            std::sort(heights.begin(),heights.end());
            double last=-1e6;
            for(double h:heights) if(h-last>.1 && fits(x,y,h,rad+.62)) {
                sites[j*gx+i].push_back(int(nodes.size()));
                nodes.push_back({i,j,float(h),0,{}});
                last=h;
            }
        }
        constexpr int dir[][2]={{1,0},{1,1},{0,1},{-1,1},{-1,0},{-1,-1},{0,-1},{1,-1}};
        for(auto& a:nodes) {
            int blocked=0;
            for(auto& d:dir){
                bool linked=false;
                for(int jump=1;jump<=2 && !linked;jump++){
                    int i=a.x+d[0]*jump,j=a.y+d[1]*jump;
                    if(i<0||i>=gx||j<0||j>=gy) break;
                    double x=wx(a.x),y=wy(a.y),u=wx(i),v=wy(j),length=std::hypot(u-x,v-y);
                    for(int id:sites[j*gx+i]) {
                        auto& target=nodes[id];
                        double dz=target.z-a.z;
                        bool jet=dz>ledge+.05 && target.z>ground(u,v)+.45;
                        if(jet){
                            if(dz>45 || !fits(x,y,target.z,rad)) continue;
                            bool open=true;
                            for(int s=1;s<=12;s++) {
                                double f=s/12.;
                                if(!fits(x+(u-x)*f,y+(v-y)*f,target.z,rad+.35)) {open=false;break;}
                            }
                            if(!open)continue;
                            // The departure column must be open to above head height.
                            bool ceiling=false;
                            for(int k=col(x,y);k>=0;k=slabs[k].next){
                                const auto& p=polys[slabs[k].id];
                                if(p.base>a.z+.1 && p.base<target.z+height && p.top>a.z+.1) ceiling=true;
                            }
                            if(ceiling) continue;
                        }else if(!move(x,y,a.z,u,v,rad+.62)) continue;
                        // Avoid edges to a support the mech cannot reach, e.g. through a bridge deck.
                        if(!jet && dz>ledge+.05 && std::abs(surface(u,v,a.z)-target.z)>.5) continue;
                        if(dz < -ledge && surface(u,v,a.z)>target.z+.4) continue;
                        float cost=float(length+(jet?55+5.1*dz:std::max(0.,-dz-2)*.38));
                        a.links.push_back({id,cost,jet}); linked=true;
                    }
                    if(jump==1 && !linked) blocked++;
                }
            }
            a.shelter=blocked/8.f;
        }
        // Directional cover and exit count on the 4 m navigation graph. Nearby
        // high solids count, map boundary and isolated pockets do not.
        for(auto& n:nodes){
            double x=wx(n.x),y=wy(n.y);
            int walls=0;
            for(auto& d:dir){
                for(double f: {1.5,3.0,5.0}) {
                    double px=x+stride*f*d[0],py=y+stride*f*d[1];
                    if(!free_column(px,py,n.z+2.0)){walls++;break;}
                }
            }
            n.shelter=std::min(1.f,walls/5.f) * (n.links.size()<3?.4f:1.f);
        }
        for(auto& n:nodes)
            n.clearance=clearance(wx(n.x),wy(n.y),n.z,body_scales.size()-1);
        for(auto& n:nodes){
            double x=wx(n.x), y=wy(n.y);
            for(auto& edge:n.links){
                const auto& target=nodes[edge.to];
                unsigned cap=std::min(n.clearance,target.clearance);
                double u=wx(target.x),v=wy(target.y), feet=edge.climb?target.z:n.z;
                for(double f: {.25,.5,.75}){
                    if(!cap)break;
                    double a=x+(u-x)*f,b_=y+(v-y)*f;
                    if(!edge.climb) feet=surface(a,b_,feet);
                    cap=clearance(a,b_,feet,cap);
                }
                edge.clearance=cap;
            }
        }
        costs.resize(nodes.size());parent.resize(nodes.size());
    }
    int nearest(double x,double y,double z,bool start) const {
        int i=std::clamp(int((x-l)/stride),0,gx-1),j=std::clamp(int((y-b)/stride),0,gy-1);
        int best=-1;double score=1e20;
        for(int ring=0;ring<=9;ring++){
            for(int v=std::max(0,j-ring);v<=std::min(gy-1,j+ring);v++)
                for(int u=std::max(0,i-ring);u<=std::min(gx-1,i+ring);u++){
                    if(std::max(std::abs(u-i),std::abs(v-j))!=ring) continue;
                    for(int id:sites[v*gx+u]){
                        if(nodes[id].clearance<active_tier) continue;
                        double dz=nodes[id].z-z;
                        double s=squared(wx(u)-x,wy(v)-y)+dz*dz*(dz>ledge && start?14.:1.75);
                        if(s<score && (!start || ring<1 || move(x,y,z,wx(u),wy(v),rad))) {score=s;best=id;}
                    }
                }
            if(best>=0 && score<(ring+.4)*(ring+.4)*stride*stride) break;
        }
        return best;
    }
    int nearest_column(double x,double y,double z) const {
        int i=std::clamp(int((x-l)/stride),0,gx-1),j=std::clamp(int((y-b)/stride),0,gy-1);
        int best=-1;double d=1e30;
        for(int id:sites[j*gx+i]) if(std::abs(nodes[id].z-z)<d){d=std::abs(nodes[id].z-z);best=id;}
        return best;
    }
    bool plan(int start,int goal,const double* threats,int nt) {
        route.clear();cursor=0;last_goal=goal;reuse=0;
        last_n=nt;
        for(int i=0;i<nt*3;i++) last_threats[i]=threats[i];
        std::fill(costs.begin(),costs.end(),infinity);
        std::fill(parent.begin(),parent.end(),-1);
        using Entry=std::pair<float,int>;
        std::priority_queue<Entry,std::vector<Entry>,std::greater<Entry>> open;
        auto& g=nodes[goal];
        auto h=[&](int id){auto& n=nodes[id];return std::hypot(float(n.x-g.x),float(n.y-g.y))*float(stride);};
        costs[start]=0;open.push({h(start),start});
        int best=start, expanded=0;
        while(!open.empty() && expanded<12500) {
            auto [f,id]=open.top();open.pop();
            if(id==goal){best=id;break;}
            if(f>costs[id]+h(id)*1.14f+.01f)continue;
            if(h(id)<h(best))best=id;
            expanded++;
            for(auto& edge:nodes[id].links){
                if(edge.clearance<active_tier) continue;
                auto& n=nodes[edge.to];double x=wx(n.x),y=wy(n.y),risk=0;
                for(int k=0;k<nt;k++){
                    double d2=squared(x-threats[3*k],y-threats[3*k+1]);
                    if(d2<170*170) risk+=threats[3*k+2]*1450/(700+d2)*(1-.48*n.shelter);
                }
                float c=costs[id]+edge.cost*(1+std::min(4.,risk));
                if(c>=costs[edge.to])continue;
                costs[edge.to]=c; parent[edge.to]=id;
                open.push({c+1.14f*h(edge.to),edge.to});
            }
        }
        if(best==start && start!=goal)return false;
        for(int id=best;id>=0;id=parent[id])route.push_back(id);
        std::reverse(route.begin(),route.end());
        return true;
    }
    void waypoint(const double* pos,const double* dest,const double* threats,int nt,double* out){
        double x=pos[0],y=pos[1],z=pos[2],u=dest[0],v=dest[1],w=dest[2];
        out[0]=x;out[1]=y;out[2]=-1e6;
        // Hold the same landing spot while the bot is jetting up its wall.
        if(last_climb>-1e5 && std::hypot(x-climb_x,y-climb_y)<13 &&
          (z<last_climb-.05 || surface(x,y,z)<last_climb-.22) &&
          std::hypot(u-climb_goal_x,v-climb_goal_y)<20 && reuse++<85){
            out[0]=climb_x;out[1]=climb_y;out[2]=last_climb;return;
        }
        last_climb=-1e6;
        if(std::hypot(x-u,y-v)<22 && w<=z+ledge+2 && move(x,y,z,u,v,rad)){
            out[0]=u;out[1]=v;return;
        }
        int goal=nearest(u,v,w,false);
        if(goal<0)return;
        bool rebuild=route.empty() || (goal!=last_goal &&
            (last_goal<0 || std::hypot(nodes[goal].x-nodes[last_goal].x,nodes[goal].y-nodes[last_goal].y)>1.5 ||
             std::abs(nodes[goal].z-nodes[last_goal].z)>3));
        if(!rebuild){
            size_t best=cursor;double score=1e20;
            for(size_t k=cursor;k<std::min(route.size(),cursor+8);k++){
                auto& n=nodes[route[k]];double dz=n.z-z;
                double d=squared(wx(n.x)-x,wy(n.y)-y)+.13*std::min(9.,std::abs(dz))*std::min(9.,std::abs(dz));
                if(d<score){score=d;best=k;}
            }
            cursor=best;
            if(score>13*13 || (cursor+1==route.size() && route.back()!=goal && score<16)) rebuild=true;
            bool riskchange=last_n!=nt;
            for(int i=0;i<nt && !riskchange;i++)
                riskchange=squared(last_threats[3*i]-threats[3*i],last_threats[3*i+1]-threats[3*i+1])>26*26;
            if(reuse>=12 && riskchange) rebuild=true;
        }
        if(rebuild){
            int start=nearest(x,y,z,true);
            if(start<0 || !plan(start,goal,threats,nt))return;
        }
        reuse++;
        size_t chosen=cursor;
        for(size_t k=cursor;k<std::min(route.size(),cursor+7);k++){
            auto& n=nodes[route[k]];
            double nx=wx(n.x),ny=wy(n.y);
            if(n.z>std::min(z,surface(x,y,z))+ledge+.05 && n.z>ground(nx,ny)+.45){
                // Approach the launch node before turning into the wall.
                if(k<=cursor+1 && n.z>z+.06 && std::hypot(nx-x,ny-y)<12){
                    out[0]=climb_x=nx;out[1]=climb_y=ny;out[2]=last_climb=n.z;
                    climb_goal_x=u;climb_goal_y=v;
                    reuse=0;return;
                }
                break;
            }
            if(!move(x,y,z,nx,ny,rad+.43))continue;
            chosen=k;
        }
        const auto& n=nodes[route[chosen]];
        out[0]=wx(n.x);out[1]=wy(n.y);
        if(chosen+1==route.size() && route.back()==goal && w<=z+ledge+2 && move(x,y,z,u,v,rad)){
            out[0]=u;out[1]=v;
        }
    }
};
}
extern "C" {
void* ar_new(const double* a,const int16_t* data,int nx,int ny) {
    try{return new Map(a,data,nx,ny);}catch(...){return nullptr;}
}
void ar_free(void* m){delete static_cast<Map*>(m);}
void ar_prism(Map* m,double lo,double hi,const double* xy,const int* sizes,int count){
    Prism p;p.base=lo;p.top=hi;
    for(int j=0;j<count;j++){
        std::vector<Point> ring;
        for(int k=0;k<sizes[j];k++){
            Point q{xy[0],xy[1]};xy+=2;ring.push_back(q);
            p.l=std::min(p.l,q.x);p.r=std::max(p.r,q.x);p.b=std::min(p.b,q.y);p.t=std::max(p.t,q.y);
        }
        if(ring.size()>=3)p.rings.push_back(std::move(ring));
    }
    if(!p.rings.empty())m->polys.push_back(std::move(p));
}
void ar_build(Map* m){m->build();}
void ar_body(Map* m,double radius,double height){m->set_body(radius,height);}
double ar_ground(Map* m,double x,double y){return m->ground(x,y);}
double ar_surface(Map* m,double x,double y,double z){return m->surface(x,y,z);}
int ar_fits(Map* m,double x,double y,double z){return m->fits(x,y,m->surface(x,y,z),m->rad);}
int ar_move(Map* m,double x,double y,double z,double u,double v,double rad){return m->move(x,y,z,u,v,rad);}
int ar_clear(Map* m,double x,double y,double z,double u,double v,double w){return m->clear(x,y,z,u,v,w);}
double ar_cover(Map* m,double x,double y,double z){
    int i=m->nearest_column(x,y,z);
    return i>=0?m->nodes[i].shelter:0;
}
void ar_waypoint(Map* m,const double* pos,const double* dest,const double* threats,int nt,double* out){
    m->waypoint(pos,dest,threats,nt,out);
}
}
