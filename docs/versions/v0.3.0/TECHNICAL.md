# v0.3.0 技术方案

migration4新增sources.subject，默认english；旧数学样例和math库分析资料归math，其余当前英语资料归english。客户端X-Cuoti-Subject使用ASCII学科ID，服务端白名单。资料列表/历史/统计/考点/候选按学科过滤，上传写明确学科；AI接口仍服务端校验资料属于english。显式ID访问不改变归属；页面根据资料自身学科显示。

## 实现

app/subjects.py维护固定学科ID。GET bootstrap返回subjects。上传multipart新增subject字段，默认english兼容旧客户端；服务端验证白名单。sources.subject持久化；GET sources/history/dashboard/knowledge/review/candidates从X-Cuoti-Subject读取白名单学科，默认english。ASCII ID避免浏览器非ASCII请求头错误。

domain.list_questions(subject)在SQL层按sources.subject过滤，knowledge_stats对非英语返回空。非英语eligible=false，题目状态为记录为做对/错题/未作答/待核对。分析与手动分析接口检查资料归属为english，防止前端标记绕过。英语分析可用与学科读取结果仍分别验证。

客户端选科保存在sessionStorage；root/home永远显示选择学科，dashboard是本科概览。资料/题目详情返回真实subject并切换显示上下文；此操作不修改资料归属。静态页面版本0.3.0，无构建步骤；配置/数据目录沿用前版，Key不变。

## 迁移4

新增sources.subject，默认english；根据旧数学示例名或math-*分析关系恢复math归属。迁移记录存在则不重复重分类；FK关系和原件不变。历史混合资料若归属不符合用户期望，需要后续显式迁移入口，当前不自动按识别语言挪动。

## 保持的范围

仅英语提供knowledge库及AI分析，其他科只做学习记录。单个孩子、单个当前学期，未新增多用户账号/课程表/每科教材/云同步。既有记录通过来源详情可回看。
