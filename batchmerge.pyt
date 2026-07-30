# -*- coding: utf-8 -*-
import arcpy
import os

class Toolbox(object):
    def __init__(self):
        self.label = u"批量合并工具箱"
        self.alias = "BatchMergeToolbox"
        self.tools = [BatchMergeTool]

class BatchMergeTool(object):
    def __init__(self):
        self.label = u"GDB/MDB/SHP合并工具"
        self.description = u"合并多目录要素，并将各要素的属性字段重命名为 '要素标签_原字段名'。"
        self.canRunInBackground = False

    def getParameterInfo(self):
        # 1. 检索文件夹
        p0 = arcpy.Parameter(
            displayName=u"1. 选择检索文件夹 (可随时更换文件夹重新搜索)",
            name="workspace_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input"
        )

        # 2. 遍历出的要素类
        p1 = arcpy.Parameter(
            displayName=u"2. 检索到的要素列表 (点击选中后，自动追加到下方队列)",
            name="found_fcs",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True
        )

        # 3. 待合并队列
        p2 = arcpy.Parameter(
            displayName=u"3. 待合并队列 (累加池：跨目录保留，点右侧 + / X 手动微调)",
            name="target_queue",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )

        # 4. 输出路径
        p3 = arcpy.Parameter(
            displayName=u"4. 输出合并结果 (建议输出至 GDB 以支持长字段名)",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )

        return [p0, p1, p2, p3]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            folder = parameters[0].valueAsText
            if folder and os.path.exists(folder):
                fc_list = []
                for root, dirs, files in arcpy.da.Walk(folder, datatype="FeatureClass"):
                    for f in files:
                        full_path = os.path.join(root, f)
                        fc_list.append(full_path)
                fc_list.sort()
                
                parameters[1].filter.type = "ValueList"
                parameters[1].filter.list = fc_list
                parameters[1].values = None

        if parameters[1].altered and parameters[1].value:
            raw_selected = parameters[1].valueAsText
            if raw_selected:
                new_items = [p.strip("'").strip('"') for p in raw_selected.split(";")]
                current_queue = []
                if parameters[2].value:
                    current_queue = [p.strip("'").strip('"') for p in parameters[2].valueAsText.split(";")]
                
                for item in new_items:
                    if item not in current_queue:
                        current_queue.append(item)
                
                parameters[2].values = current_queue
                parameters[1].values = None

        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        raw_inputs = parameters[2].valueAsText
        if not raw_inputs:
            arcpy.AddError(u"错误：待合并队列为空，请先添加要素类！")
            return
            
        input_fcs = [fc.strip("'").strip('"') for fc in raw_inputs.split(";")]
        output_fc = parameters[3].valueAsText
        out_workspace = os.path.dirname(output_fc)

        arcpy.AddMessage(u"============================================")
        arcpy.AddMessage(u"正在准备对 {} 个要素类的字段进行前缀标记:".format(len(input_fcs)))

        # ArcMap 系统核心保留字段列表（不修改这些字段的名称）
        sys_fields = {"objectid", "fid", "shape", "shape_length", "shape_area", "globalid"}

        temp_prep_fcs = []
        try:
            for idx, fc_path in enumerate(input_fcs, start=1):
                # 1. 提取要素来源标签 (例如: A工程库_图斑)
                parts = fc_path.replace("\\", "/").split("/")
                fc_name = os.path.splitext(parts[-1])[0]
                
                parent_db = u""
                for p in parts:
                    p_l = p.lower()
                    if p_l.endswith(".gdb") or p_l.endswith(".mdb"):
                        parent_db = os.path.splitext(p)[0]
                        break
                
                if parent_db:
                    source_prefix = u"{}_{}".format(parent_db, fc_name)
                else:
                    source_prefix = u"SHP_{}".format(fc_name)

                arcpy.AddMessage(u"  [{}/{}] 正在加前缀处理: [{}] (前缀: {})".format(idx, len(input_fcs), fc_name, source_prefix))

                # 2. 复制到内存临时空间，保证原始文件不受任何侵入修改
                temp_fc = os.path.join("in_memory", "temp_prefix_{}".format(idx))
                arcpy.CopyFeatures_management(fc_path, temp_fc)

                # 3. 遍历自定义字段并重命名：[来源前缀]_[原字段名]
                fields = arcpy.ListFields(temp_fc)
                for f in fields:
                    if f.name.lower() not in sys_fields and not f.required:
                        raw_new_name = u"{}_{}".format(source_prefix, f.name)
                        # 确保字段名称符合 GIS 数据库规范
                        valid_new_name = arcpy.ValidateFieldName(raw_new_name, out_workspace)
                        
                        try:
                            arcpy.AlterField_management(temp_fc, f.name, valid_new_name, valid_new_name)
                        except Exception as alter_err:
                            arcpy.AddWarning(u"    └─ 字段 {} 重命名跳过: {}".format(f.name, str(alter_err)))

                # 4. 增加全局属性行来源标记
                field_source = "数据来源"
                arcpy.AddField_management(temp_fc, field_source, "TEXT", field_length=255, field_alias=u"数据来源")
                with arcpy.da.UpdateCursor(temp_fc, [field_source]) as cursor:
                    for row in cursor:
                        row[0] = source_prefix
                        cursor.updateRow(row)

                temp_prep_fcs.append(temp_fc)

            # 5. 执行合并 (Merge)
            arcpy.AddMessage(u"============================================")
            arcpy.AddMessage(u"正在合并已标记字段的要素类...")
            arcpy.Merge_management(inputs=temp_prep_fcs, output=output_fc)
            arcpy.AddMessage(u"合并成功！已将各要素来源注入至各字段名及 '数据来源' 列中。")

        except Exception as e:
            arcpy.AddError(u"合并处理失败: {}".format(str(e)))
        finally:
            # 清理内存中的临时要素
            for t_fc in temp_prep_fcs:
                if arcpy.Exists(t_fc):
                    arcpy.Delete_management(t_fc)