# v0.2.0 英语实现方案

english-core-1考点库，english-evidence-1提示词。识别保持多学科页面读取，英语题保留阅读上下文。分析仅英语，缺文章/选项/评分依据时待确认。migration3标记旧数学分析stale，不删除原始记录，旧练习计划结束以避免跨学科混用。现有教材数学版本改为暂不确定，提醒设置真实英语教材。

## 接口与迁移

沿用[v0.1.0架构/API](../v0.1.0/TECHNICAL.md)和[v0.1.1页面读取](../v0.1.1/TECHNICAL.md)。migration3仅首次执行：旧math-*分析状态stale，旧活动计划结束，数学教材人教A/B改暂不确定。不删除任何题目/资料/分析建议。新英语分析采用当前库ID；旧ID不可确认或入复习。PUT /api/pages/:id/subject支持用户明确确认英语，仅修改学科标记，不伪造OCR内容。识别与分析仍由已配置千问模型完成。

## 英语考点

- en_vocabulary：词汇与表达 / 词义与词形
- en_collocation：词汇与表达 / 固定搭配与短语
- en_word_formation：词汇与表达 / 词性与构词
- en_tense_voice：语法 / 时态与语态
- en_nonfinite：语法 / 非谓语动词
- en_relative_clause：语法 / 定语从句
- en_noun_clause：语法 / 名词性从句
- en_adverbial_clause：语法 / 状语从句
- en_agreement：语法 / 主谓一致
- en_articles_prepositions：语法 / 冠词与介词
- en_sentence_structure：语法 / 句子结构与特殊句式
- en_reading_detail：阅读与篇章 / 阅读细节定位
- en_reading_inference：阅读与篇章 / 阅读推理判断
- en_reading_main：阅读与篇章 / 主旨与作者态度
- en_reading_word：阅读与篇章 / 阅读词义猜测
- en_cloze：阅读与篇章 / 完形填空与上下文
- en_cohesion：阅读与篇章 / 七选五与篇章衔接
- en_grammar_fill：阅读与篇章 / 语法填空
- en_writing_accuracy：写作 / 写作语言准确性
- en_writing_task：写作 / 写作任务与内容
- en_writing_coherence：写作 / 写作结构与连贯
- en_continuation：写作 / 读后续写情节与表达

## 边界

不承诺覆盖全部教材。听力原音频未接入；缺原文的听力/阅读不猜答案。写作允许多个合理答案，只标有依据的错误，不自动评分。分析是建议，须用户逐题确认；暂不做作文全自动评分或考试分数预测。
