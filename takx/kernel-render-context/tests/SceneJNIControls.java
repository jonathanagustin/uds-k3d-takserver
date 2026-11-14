// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.layer.model.SceneLayer;
import com.atakmap.map.layer.feature.FeatureCursor;
import com.atakmap.map.layer.feature.FeatureDataStore2;
import java.nio.file.*;

public final class SceneJNIControls {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        Path root=Path.of(args[1]);Files.createDirectories(root);SceneLayer scene=new SceneLayer("owned-scene-query",root.resolve("cache").toString());
        try {
            try(FeatureCursor cursor=scene.query(new FeatureDataStore2.FeatureQueryParameters())) {check(!cursor.moveToNext(),"new scene not empty");}
            System.out.println("SCENE_QUERY_EMPTY_PASS");
            Path model=root.resolve("triangle.obj");Files.writeString(model,"o owned_triangle\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");String uri=model.toString();
            Files.writeString(root.resolve("triangle_offset.xyz"), "0 0 0\n");
            Files.writeString(root.resolve("triangle_wkt.prj"), "GEOGCS[\"WGS 84\",DATUM[\"WGS_1984\",SPHEROID[\"WGS 84\",6378137,298.257223563]],PRIMEM[\"Greenwich\",0],UNIT[\"degree\",0.0174532925199433],AUTHORITY[\"EPSG\",\"4326\"]]");
            check(com.atakmap.map.layer.model.ModelInfoFactory.isSupported(uri),"OBJ provider unavailable");
            scene.add(uri);
            check(scene.contains(uri),"added OBJ URI missing");long id;
            try(FeatureCursor cursor=scene.query(new FeatureDataStore2.FeatureQueryParameters())) {check(cursor.moveToNext(),"added OBJ scene missing");id=cursor.getId();check(!cursor.moveToNext(),"unexpected extra scene");}
            check(scene.isVisible(id),"new scene hidden");scene.setVisible(id,false);check(!scene.isVisible(id),"ID hide failed");scene.setVisible(id,true);check(scene.isVisible(id),"ID show failed");
            scene.setVisible(uri,false);check(!scene.isVisible(id),"original URI hide failed");scene.setVisible(uri,true);check(scene.isVisible(id),"original URI show failed");
            check(scene.remove(uri)&&!scene.contains(uri),"scene removal failed");
            try(FeatureCursor cursor=scene.query(new FeatureDataStore2.FeatureQueryParameters())){check(!cursor.moveToNext(),"removed scene still present");}
            System.out.println("SCENE_JNI_CONTROLS_PASS query=true idVisibility=true uriVisibility=true remove=true");
        }finally{scene.shutdown();}
    }
}
