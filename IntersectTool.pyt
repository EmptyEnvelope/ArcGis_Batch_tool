# -*- coding: utf-8 -*-
import arcpy
import os

class Toolbox(object):
    def __init__(self):
        self.label = u"批量相交校验工具箱"
        self.alias = "BatchIntersectToolbox"
        self.tools = [BatchIntersectTool]

class BatchIntersectTool(object):
    def __init__(self):
        self.label = u"GDB/MDB/SHP 批量相交校验"
        self.description = u"递归遍历工作目录。"
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName=u"校验用图层 / 要素类",
            name="val_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        p1 = arcpy.Parameter(
            displayName=u"工作根目录 (递归搜索包含 GDB/MDB/SHP 的目录)",
            name="workspace_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )

        p2 = arcpy.Parameter(
            displayName=u"搜索到的要素类 (保留路径，按 GDB/MDB/SHP 名称排序)",
            name="selected_fcs",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )

        p3 = arcpy.Parameter(
            displayName=u"输出结果文件夹",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )

        return [p0, p1, p2, p3]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[1].altered and parameters[1].value:
            folder = parameters[1].valueAsText
            if folder and os.path.exists(folder):
                fc_list = []
                
                # 递归遍历目录中的要素类 (支持 GDB, MDB, SHP)
                for root, dirs, files in arcpy.da.Walk(folder, datatype="FeatureClass"):
                    root_lower = root.lower()
                    for f in files:
                        f_lower = f.lower()
                        full_path = os.path.join(root, f)
                        
                        container_name = u""
                        # 1. 检查路径是否包含 .gdb 或 .mdb
                        parts = full_path.replace("\\", "/").split("/")
                        for p in parts:
                            p_l = p.lower()
                            if p_l.endswith(".gdb") or p_l.endswith(".mdb"):
                                container_name = p
                                break
                        
                        # 2. 如果不属于 GDB/MDB，但是独立的 .shp 文件
                        if not container_name and f_lower.endswith(".shp"):
                            container_name = f  # 直接使用 shp 文件名作为排序容器名
                        
                        if container_name:
                            fc_list.append((container_name.lower(), full_path))

                # 按照 GDB/MDB/SHP 名称升序排序
                fc_list.sort(key=lambda x: (x[0], x[1]))
                choices = [item[1] for item in fc_list]
                parameters[2].filter.type = "ValueList"
                parameters[2].filter.list = choices
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        val_layer = parameters[0].valueAsText
        workspace_folder = parameters[1].valueAsText
        
        raw_selected = parameters[2].valueAsText
        if not raw_selected:
            arcpy.AddError(u"未选择任何要校验的要素类！")
            return
            
        selected_fcs = raw_selected.split(";")
        output_folder = parameters[3].valueAsText

        # 解析校验用数据的名称（支持 GDB, MDB 或 Shapefile/图层名）
        val_gdb_name = u"校验数据"
        val_parts = val_layer.replace("\\", "/").split("/")
        for part in val_parts:
            p_l = part.lower()
            if p_l.endswith(".gdb") or p_l.endswith(".mdb"):
                val_gdb_name = os.path.splitext(part)[0]
                break
        else:
            val_gdb_name = os.path.splitext(os.path.basename(val_layer))[0]

        # 创建合并输出 GDB: 相交校验-(校验数据名称).gdb
        out_gdb_filename = u"相交校验-{}.gdb".format(val_gdb_name)
        out_gdb_path = os.path.join(output_folder, out_gdb_filename)

        if not arcpy.Exists(out_gdb_path):
            arcpy.AddMessage(u"正在创建合并输出 GDB: {}".format(out_gdb_filename))
            arcpy.CreateFileGDB_management(output_folder, out_gdb_filename)
        else:
            arcpy.AddMessage(u"输出 GDB 已存在，将直接写入: {}".format(out_gdb_filename))

        total = len(selected_fcs)
        for idx, raw_fc_path in enumerate(selected_fcs, start=1):
            fc_path = raw_fc_path.strip("'").strip('"')
            
            # 提取要素名 (如果是 SHP 会去掉 .shp 后缀)
            fc_base = os.path.splitext(os.path.basename(fc_path))[0]
            
            # 判断是否包含父级数据库 (GDB / MDB)
            parent_db = u""
            for p in fc_path.replace("\\", "/").split("/"):
                p_l = p.lower()
                if p_l.endswith(".gdb") or p_l.endswith(".mdb"):
                    parent_db = os.path.splitext(p)[0]
                    break
            
            # 拼接目标表名
            if parent_db:
                raw_target_name = u"{}_{}_相交".format(parent_db, fc_base)
            else:
                raw_target_name = u"{}_相交".format(fc_base)
                
            target_fc_name = arcpy.ValidateTableName(raw_target_name, out_gdb_path)
            target_fc_path = os.path.join(out_gdb_path, target_fc_name)

            arcpy.AddMessage(u"[{}/{}] 正在执行相交校验: {}".format(idx, total, fc_base))
            
            try:
                # 执行 ArcTool 相交校验
                arcpy.Intersect_analysis([val_layer,fc_path], target_fc_path)
                arcpy.AddMessage(u"  └─ 成功导出至: {}".format(target_fc_name))
            except Exception as e:
                arcpy.AddWarning(u"  └─ 相交分析失败: {} | 错误信息: {}".format(fc_path, str(e)))

        arcpy.AddMessage(u"处理完成！")