from __future__ import annotations

TAXONOMY_VERSION = "task-taxonomy-v2"

SUPPORTED_TAXONOMY_VERSIONS = ("task-taxonomy-v1", TAXONOMY_VERSION)

TAXONOMY = {
    "version": TAXONOMY_VERSION,
    "domains": [
        {"id": "general", "label": "通用", "description": "不依赖特定专业领域的任务。"},
        {"id": "medicine", "label": "医学与健康", "description": "医学文献、临床信息、健康知识。"},
        {"id": "law", "label": "法律", "description": "法律知识、合同和司法材料。"},
        {"id": "finance", "label": "金融与商业", "description": "金融、会计、经营分析。"},
        {"id": "software", "label": "软件开发", "description": "程序、软件工程和计算系统。"},
        {"id": "science", "label": "自然科学与工程", "description": "科学研究和工程专业问题。"},
        {"id": "education", "label": "教育", "description": "教学、学习与教育评估。"},
    ],
    "tasks": [
        {"id": "knowledge_qa", "label": "知识问答", "description": "回答有事实或专业知识依据的问题。"},
        {"id": "literature_review", "label": "文献综述", "description": "整合多篇研究、比较结论并归纳证据。"},
        {"id": "document_qa", "label": "文档问答", "description": "基于给定文档回答问题。"},
        {"id": "structured_extraction", "label": "结构化信息提取", "description": "从来源材料提取字段、实体、关系或结构化记录。"},
        {"id": "summarization", "label": "内容摘要", "description": "保持事实一致地压缩来源内容。"},
        {"id": "contract_review", "label": "合同审查", "description": "检查合同条款、识别风险和不一致。"},
        {"id": "code_development", "label": "代码开发", "description": "编写、修改、调试或测试代码。"},
        {"id": "data_analysis", "label": "数据分析", "description": "分析数据、选择统计方法并解释结果。"},
        {"id": "mathematical_problem_solving", "label": "数学解题", "description": "完成数学推导与计算。"},
        {"id": "visual_document_understanding", "label": "图文文档理解", "description": "读取图像、图表、版面或混合文档。"},
        {"id": "translation", "label": "翻译", "description": "在不同自然语言之间转换内容。"},
        {"id": "tool_workflow", "label": "工具任务执行", "description": "通过检索、软件工具或多步操作完成任务。"},
    ],
    "capabilities": [
        {"id": "domain_knowledge", "label": "领域知识", "description": "测量事实或专业知识的正确性。"},
        {"id": "long_context", "label": "长文本理解", "description": "直接测量长输入中信息定位、理解或利用；长度本身不足以证明。"},
        {"id": "cross_document_synthesis", "label": "跨文档整合", "description": "测量多个文档的比较、整合或冲突识别。"},
        {"id": "citation_reliability", "label": "引用可靠性", "description": "直接测量引用存在性、准确性、完整性或证据支持。"},
        {"id": "information_extraction", "label": "信息抽取", "description": "测量字段、实体或关系抽取的正确性。"},
        {"id": "instruction_following", "label": "指令与格式遵循", "description": "直接测量指令约束或输出格式符合程度。"},
        {"id": "reasoning", "label": "逻辑与数学推理", "description": "测量推导、多步推理或问题求解正确性。"},
        {"id": "code_correctness", "label": "代码正确性", "description": "通过测试、执行或明确规格测量代码功能正确性。"},
        {"id": "statistical_reasoning", "label": "统计推理", "description": "测量统计方法选择、数据分析和统计结论解释。"},
        {"id": "grounded_faithfulness", "label": "来源忠实性", "description": "直接测量回答或摘要与给定来源的一致性。"},
        {"id": "multimodal_understanding", "label": "多模态理解", "description": "测量对图像、图表、视听或混合模态内容的理解。"},
        {"id": "multilingual_communication", "label": "多语言表达", "description": "直接测量跨语言理解、翻译或表达质量。"},
        {"id": "tool_use", "label": "工具使用", "description": "测量工具选择、调用和任务执行成功率。"},
    ],
}

def label_ids(layer: str) -> frozenset[str]:
    return frozenset(item["id"] for item in TAXONOMY[layer])
