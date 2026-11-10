// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import android.database.Cursor;
/** SQL structure builder; selection values are always bound by the database. */
public final class SQLiteQueryBuilder {
    private String tables;
    private boolean distinct;
    private final StringBuilder where=new StringBuilder();
    public void setTables(String tables){
        this.tables=tables;
    }
    public String getTables(){
        return tables;
    }
    public void setDistinct(boolean distinct){
        this.distinct=distinct;
    }
    public void appendWhere(CharSequence condition){
        where.append(condition);
    }
    public String buildQuery(String[] projection,String selection,String groupBy,String having,String orderBy,String limit){
        String combined=where.length()==0?selection:selection==null||selection.isEmpty()?where.toString():"("+where+") AND ("+selection+")";
        return buildQueryString(distinct,tables,projection,combined,groupBy,having,orderBy,limit);
    }
    public Cursor query(SQLiteDatabase db,String[] projection,String selection,String[] args,String groupBy,String having,String orderBy){
        return query(db,projection,selection,args,groupBy,having,orderBy,null);
    }
    public Cursor query(SQLiteDatabase db,String[] projection,String selection,String[] args,String groupBy,String having,String orderBy,String limit){
        return db.rawQuery(buildQuery(projection,selection,groupBy,having,orderBy,limit),args);
    }
    public static String buildQueryString(boolean distinct,String tables,String[] columns,String where,String groupBy,String having,String orderBy,String limit){
        if(tables==null||tables.isEmpty())throw new IllegalArgumentException("tables required");
        if(having!=null&&!having.isEmpty()&&(groupBy==null||groupBy.isEmpty()))throw new IllegalArgumentException("HAVING requires GROUP BY");
        if(limit!=null&&!limit.isEmpty()&&!limit.matches("\\s*\\d+\\s*(,\\s*\\d+\\s*)?"))throw new IllegalArgumentException("invalid LIMIT");
        StringBuilder sql=new StringBuilder("SELECT ");
        if(distinct)sql.append("DISTINCT ");
        sql.append(columns==null||columns.length==0?"*":String.join(", ",columns)).append(" FROM ").append(tables);
        clause(sql," WHERE ",where);
        clause(sql," GROUP BY ",groupBy);
        clause(sql," HAVING ",having);
        clause(sql," ORDER BY ",orderBy);
        clause(sql," LIMIT ",limit);
        return sql.toString();
    }
    private static void clause(StringBuilder sql,String name,String value){
        if(value!=null&&!value.isEmpty())sql.append(name).append(value);
    }
}
