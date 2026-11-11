/* Copyright 2026 uds-takserver authors */
/* SPDX-License-Identifier: GPL-3.0-only */
#ifdef NDEBUG
#error Positive coordinate assertions must stay enabled
#endif
#include <proj_api.h>
#include <assert.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
int main(void){
    assert(PJ_VERSION==491);assert(strstr(pj_get_release(),"4.9.1")!=NULL);
    projPJ geographic=pj_init_plus("+proj=longlat +datum=WGS84 +no_defs");
    projPJ mercator=pj_init_plus("+proj=merc +a=6378137 +b=6378137 +units=m +no_defs");
    assert(geographic&&mercator&&pj_is_latlong(geographic)&&!pj_is_latlong(mercator));
    const double pi=3.14159265358979323846;
    double x[3]={0,10*pi/180,-10*pi/180},y[3]={0,45*pi/180,-45*pi/180},z[3]={12.5,100,-7};
    assert(pj_transform(geographic,mercator,3,1,x,y,z)==0);
    const double expected_x[3]={0,1113194.9079327357,-1113194.9079327357};
    const double expected_y[3]={0,5621521.486192066,-5621521.486192066};
    for(int i=0;i<3;i++){assert(fabs(x[i]-expected_x[i])<0.00001);assert(fabs(y[i]-expected_y[i])<0.00001);}
    assert(z[0]==12.5&&z[1]==100&&z[2]==-7);
    assert(pj_transform(mercator,geographic,3,1,x,y,z)==0);
    for(int i=0;i<3;i++){assert(fabs(x[i]-(i==0?0:(i==1?10:-10))*pi/180)<1e-12);assert(fabs(y[i]-(i==0?0:(i==1?45:-45))*pi/180)<1e-12);}
    pj_free(geographic);pj_free(mercator);
    printf("actual_release=%s\nknown_spherical_mercator_positive_coordinates_and_inverse=true\n",pj_get_release());return 0;
}
