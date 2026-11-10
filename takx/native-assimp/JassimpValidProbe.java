// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import jassimp.*;
import java.nio.file.*;
import java.util.*;
public final class JassimpValidProbe {
    static final AiBuiltInWrapperProvider PROVIDER=new AiBuiltInWrapperProvider();
    static void require(boolean value,String label){if(!value)throw new AssertionError(label);}
    static boolean near(double a,double b){return Math.abs(a-b)<0.0001;}
    static int nodes(AiScene scene,AiNode node,double[][] parent){
        AiMatrix4f local=node.getTransform(PROVIDER);double[][] world=new double[4][4];
        for(int r=0;r<4;r++)for(int c=0;c<4;c++)for(int k=0;k<4;k++)world[r][c]+=parent[r][k]*local.get(k,c);
        int references=0;
        for(int index:node.getMeshes()){
            AiMesh mesh=scene.getMeshes().get(index);
            for(int i=0;i<mesh.getNumVertices();i++){
                double[] p={mesh.getPositionX(i),mesh.getPositionY(i),mesh.getPositionZ(i),1};double[] value=new double[4];
                for(int r=0;r<4;r++)for(int k=0;k<4;k++)value[r]+=world[r][k]*p[k];
                require(near(value[0],10+2*p[0])&&near(value[1],20+3*p[1])&&near(value[2],30+4*p[2]),"nested transform");
            }
            references++;
        }
        for(AiNode child:node.getChildren())references+=nodes(scene,child,world);
        return references;
    }
    public static void main(String[] args)throws Exception{
        require(args.length==4,"arguments");Path library=Path.of(args[0]).toRealPath(),core=Path.of(args[1]).toRealPath(),jar=Path.of(args[3]).toRealPath();
        Path origin=Path.of(Jassimp.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();require(origin.equals(jar),"matching source jar origin");
        Jassimp.setWrapperProvider(PROVIDER);Jassimp.setLibraryLoader(new JassimpLibraryLoader(){@Override public void loadLibrary(){System.load(library.toString());}});
        AiScene scene=Jassimp.importFile(Path.of(args[2]).toRealPath().toString(),EnumSet.of(AiPostProcessSteps.TRIANGULATE,AiPostProcessSteps.VALIDATE_DATA_STRUCTURE));
        require(scene!=null&&scene.getMeshes().size()==1,"scene mesh count");AiMesh mesh=scene.getMeshes().get(0);
        require(mesh.getNumVertices()==3&&mesh.getNumFaces()==1&&mesh.getFaceNumIndices(0)==3,"geometry counts");boolean[] seen=new boolean[3];
        for(int j=0;j<3;j++){
            int i=mesh.getFaceVertex(0,j);require(i>=0&&i<3,"face index");double x=mesh.getPositionX(i),y=mesh.getPositionY(i),z=mesh.getPositionZ(i);int expected=near(x,4)?1:(near(y,6)?2:0);
            require(!seen[expected],"unique vertex");seen[expected]=true;require(near(x,expected==1?4:1)&&near(y,expected==2?6:2)&&near(z,3),"positions");
            require(near(mesh.getNormalX(i),0)&&near(mesh.getNormalY(i),0)&&near(mesh.getNormalZ(i),1),"normals");
            require(near(mesh.getTexCoordU(i,0),expected==1?0.75:0.125)&&near(mesh.getTexCoordV(i,0),expected==2?0.875:0.25),"uvs");
        }
        AiColor color=scene.getMaterials().get(mesh.getMaterialIndex()).getDiffuseColor(PROVIDER);require(near(color.getRed(),0.2)&&near(color.getGreen(),0.4)&&near(color.getBlue(),0.8)&&near(color.getAlpha(),1),"material color");
        double[][] identity=new double[4][4];for(int i=0;i<4;i++)identity[i][i]=1;require(nodes(scene,scene.getSceneRoot(PROVIDER),identity)==1,"scene references");
        require(Jassimp.getV3Dsize()==12&&Jassimp.getfloatsize()==4&&Jassimp.getintsize()==4&&Jassimp.getuintsize()==4&&Jassimp.getdoublesize()==8&&Jassimp.getlongsize()==8,"primitive sizes");
        require(Jassimp.getVKeysize()==24&&Jassimp.getQKeysize()==24,"animation struct sizes");
        Set<Path> mapped=new LinkedHashSet<>();for(String line:Files.readAllLines(Path.of("/proc/self/maps"))){String[] columns=line.trim().split("\\s+",6);if(columns.length==6&&(columns[5].endsWith("/libjassimp.so")||columns[5].endsWith("/libassimp.so.4.1.0")))mapped.add(Path.of(columns[5]).toRealPath());}
        require(mapped.equals(new LinkedHashSet<>(Arrays.asList(library,core))),"exact genuine native mappings");
        System.out.println("jar_origin="+origin);for(Path path:mapped)System.out.println("mapped_library="+path);
        System.out.println("valid_java_jni_geometry_material_transform_uv_normal_interop=true");
    }
}
