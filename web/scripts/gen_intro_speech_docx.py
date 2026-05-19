# -*- coding: utf-8 -*-
"""生成手心语项目介绍演讲稿 Word 文档（详细版）。"""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.oxml.ns import qn

OUT = Path(__file__).resolve().parents[1] / "docs" / "手心语-项目介绍演讲稿（详细版）.docx"


def set_doc_font(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(12)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "黑体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")


def add_para(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(12)
    run.bold = bold


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def add_table(doc: Document, headers: list[str], rows: list[tuple]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)


def main() -> None:
    doc = Document()
    set_doc_font(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("手心语 — 项目介绍演讲稿与视频脚本")
    r.bold = True
    r.font.size = Pt(22)
    r.font.name = "黑体"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run("【详细版】含完整配音稿、项目说明、服务介绍、技术架构与分镜").font.size = Pt(11)

    doc.add_paragraph()
    meta = doc.add_paragraph()
    meta.add_run(
        "文档结构：\n"
        "· 第一章：完整配音稿（约 2400 字，正常语速约 7～8 分钟；若需压到 5 分钟可删「技术详解」段）\n"
        "· 第二章：分镜脚本（约 6～8 分钟成片参考）\n"
        "· 第三～九章：背景、功能、服务、技术、模型、部署、局限（供撰写字幕/答辩/旁白删减）\n"
        "· 第十章：录屏与剪辑检查清单\n"
    )

    doc.add_page_break()

    # ==================== 一、完整演讲稿 ====================
    add_heading(doc, "一、完整配音稿（详细版，建议朗读全文）", 1)

    speech_sections = [
        (
            "【开场 · 项目定位】",
            """各位老师、同学，大家好。今天我介绍的项目叫做「手心语」——手心的手，语言的语——是一款面向听障人士及其家属、手语学习者与无障碍服务场景的 Web 端手语识别与双向沟通助手。

我们先看现实痛点。我国听障群体人数众多，手语是很多人日常沟通的首选方式，但健听者往往看不懂手语；反过来，听障用户打字或写字速度有限，面对面交流时信息容易「卡在手上」。现有方案里，专业手语翻译人力成本高、预约难；纯文字聊天又丢失表情与现场感。我们希望用可本地部署、可扩展的工程系统，把「摄像头或视频里的手语」尽量可靠地转成文字，再与语音朗读、大字展示、常用语库组合起来，形成一条完整的沟通闭环。

手心语不是要替代持证手语翻译，而是面向日常陪伴、教学演示、社区活动与科研原型验证，让技术「能跑起来、能演示、能迭代」。""",
        ),
        (
            "【功能一 · 说话：健听侧输出 + 听障侧输入】",
            """手心语底部导航有四个主入口，第一个是「说话」，解决的是「我想让对方听到/看到一句话」。

在说话页，用户可以像聊天一样输入最多两千字的文本，选择朗读语言，然后两种输出方式：一是「播放声音」，支持浏览器本机语音合成，也支持接入 MiniMax 云端 TTS，音色可按语言切换；二是「展示给对方」，弹出全屏大字对话框，适合地铁、医院等嘈杂环境，对方直接看字。还可以勾选「识别出字后给对方看全屏大字」，与手语识别联动。

输入方式除键盘外，还有「手写」标签页：在画布上写字，点「识别填入」。后端优先用本地 RapidOCR 做快速识别，并对图像做 OpenCV 预处理；若本地结果为空或不可信，再调用智谱 GLM 视觉大模型识图。这样兼顾速度与准确率。

说话页右侧是「我的话」——常用语库。每条常用语可设分类、标签、排序，支持搜索与一键「听」或「展示」。左侧还可展开「手语词本」，按词、语种、分类管理词汇，方便对照练习。听障用户可把高频句子存好，需要时一点即播，不必每次重打。

此外，说话模块支持 DeepSeek 翻译接口：可把中文话译成英文再朗读，便于与只会英语的用户沟通。以上数据均按账号隔离存储，不会与其他用户混用。""",
        ),
        (
            "【功能二 · 拍一下：实时摄像头手语识别】",
            """第二个入口是「拍一下」，对应当场对着摄像头打手语的场景。

界面采用「上大下小」布局：上方是大屏摄像头预览，要求用户全身或上半身入镜，光线充足、背景尽量简洁；下方左侧是参数，右侧是「本段译文」与过程日志。

用户点「开始」后，系统按设定秒数——默认约 6 秒——录一小段 WebM 视频，录满自动上传并发起识别任务。可勾选「一直录直到我按停」，实现多段连续沟通；点「停」后，正在识别的那一段仍会跑完并出字，不会白录。每段可勾选「记入记录」和「本机/MiniMax 朗读」。

识别方式有三档，务必根据画面选择：第一，「仅 ONNX」——走本地 Uni-Sign 导出的手语翻译模型，读的是肢体动作，不读画面上的字幕，纯手语约 20～60 秒一段；第二，「仅 OCR」——用 RapidOCR 读画面底部硬字幕，有新闻条、教程字幕时 5～15 秒即可；第三，「混合」——ONNX 与 OCR 并行，再经 DeepSeek 多 Agent 合议定稿，并自动去掉模型思考过程，只展示干净译文。

若需要更实时的体验，可勾选「连续自动出字」：每 3～8 秒录一段、排队识别，字幕逐条追加，适合快速浏览，但准确度低于「传视频」里的整段模式。网页会提示勿与分段拍一下同时开，避免资源争抢。

语种方面，拍一下支持中文手语与英文手语快捷切换，模型包括 CSL-Daily、OpenESL/VECSL 演示路径、OpenASL、How2Sign 等，与上传视频共用同一套模型目录说明。""",
        ),
        (
            "【功能三 · 传视频：离线素材高精度识别】",
            """第三个入口是「传视频」，适合已经录好的手语视频、课程回放或新闻片段。

流程是：先选择本地 mp4 等文件上传，服务器保存到该用户专属 uploads 目录；然后在左侧点「开始整段识别」。系统会读取视频时长——浏览器预览元数据与服务端 ffprobe 取最大值——若超过约 8 秒阈值，则用 FFmpeg 按约 10～12 秒切分，逐段提取姿态、跑 ONNX，进度条显示「第 N/M 段」；每完成一段，识别输出区会增加一行「整段识别 第 N 句」。长视频混合识别时，还会对每一段分别做 OCR 对齐与 AI 仲裁，再合并成全文。

右侧是「边播边出字」：用同一预览播放器，按 6～10 秒切段上传，适合快速扫一遍内容，但官方说明准确度低于左侧整段。两边共用下方「识别输出」日志区，可点某条查看全文。

整段识别可勾选「记入记录」，完成后写入识别历史，并 toast 提示。画面有硬字幕时，强烈建议选 OCR 或混合；纯手语动作选 ONNX 或混合。中文连续句推荐 CSL-Daily 或 OpenESL 路径；英文 ASL 选 OpenASL。

视频页还提供「补录/手写」折叠区：识别结果不理想时，可手写或键盘修正，再「存到记录」。""",
        ),
        (
            "【功能四 · 记录与账号】",
            """第四个入口是「记录」，即识别历史表。每一行包含时间、语种模型、来源文件名、识别文本；可点「读」再次朗读，或删除。整段识别、边播、拍一下在勾选相应选项后都会写入这里。服务端若合并字段为空，会从分段列表自动拼接；前端还有兜底补存，避免勾选了却没记下。

账号方面，支持注册、登录与游客模式。注册用户数据落在 SQLite 用户表与每人独立的 JSON 文件；游客仅当前浏览器会话有效。顶栏可调字号 100%～140%、切换高对比、查看模型说明与帮助。健康状态点显示服务与 ONNX 是否就绪。

这些设计的目标，是让听障用户「说得出去、打得出来、存得下来」，让家属「看得懂、读得出来」。""",
        ),
        (
            "【服务介绍 · 交付形态与能力边界】",
            """从服务角度，手心语提供的是一套可本地或服务器部署的 Web 服务，而不是仅一个演示页面。

核心服务包括：手语视频识别服务——接收用户上传或实时片段，返回文本与分段元数据；文本转语音服务——可选 MiniMax；手写 OCR 服务——本地 + 智谱；翻译润色服务——DeepSeek；以及用户数据服务——常用语、词库、历史、上传文件管理。所有云端调用密钥在服务端 .env 配置，前端不暴露 API Key，适合校园机房、公益机构内网部署。

服务按用户隔离，路径校验防止越权访问他人上传。识别任务异步执行，前端轮询任务状态，支持分场景取消——整段、边播、拍一下互不干扰。超时与错误会返回中文说明，例如 NumPy 版本不兼容、未安装 FFmpeg、识别结果为空等。

交付上，机构可在一台带 CPU 的机器上安装 Python 依赖与 ONNX 模型包，执行 uvicorn 启动；有 GPU 可加速但非必须。需要更高准确率时，再开通 DeepSeek、智谱、Kimi 等密钥即可启用混合识别，无需改代码结构。""",
        ),
        (
            "【技术介绍 · 架构与识别流水线】",
            """技术架构分四层。

第一层，表现层：单页 Web 应用，原生 JavaScript 模块化，无 React 构建链，便于部署静态资源；响应式布局适配手机与桌面，强调无障碍。

第二层，应用层：FastAPI 提供 REST API——认证、上传、翻译任务、历史、常用语、词库、TTS、健康检查、模型目录等；SessionMiddleware 管理登录态；ThreadPoolExecutor 跑长任务。

第三层，识别层：这是核心。视频进入后，根据模式分支：ONNX 路径调用 Uni-Sign 仓库导出的推理脚本，先由姿态估计把人体关键点序列化，再送入 ONNX Runtime 做自回归解码得到中文或英文句子；长视频由 _run_onnx_translate_maybe_split 切片，每片独立推理后去重合并。OCR 路径对关键帧或整片抽帧，RapidOCR 识别硬字幕，再经 DeepSeek 做口语化清洗。混合路径在 ThreadPoolExecutor 里并行 OCR、可选 Kimi 视频理解、智谱 GLM 视频理解，再对每一段调用 run_hybrid_fusion：多源文本进 DeepSeek 仲裁，可选 GLM 复核，输出 strip 掉思考链的最终译文。

第四层，数据层：SQLite 存用户；每用户 JSON 存 phrases、vocabulary、translation_history；上传视频按 uploads/用户键/ 存放。启动时 lifespan 钩子检查模型 tar 包是否解压。

关键技术栈：Python 3、FastAPI、Uvicorn、ONNX Runtime、OpenCV、FFmpeg、transformers/sentencepiece（模型相关）、passlib 密码哈希、python-dotenv。边播与拍一下短片段走 rt_fast 快路径：轻量姿态、少帧、优先 OCR 硬字幕，减少外网调用。

模型侧，已部署的是 Uni-Sign 统一框架导出的多数据集 ONNX：CSL-Daily 中文、OpenASL/How2Sign 英文等；OpenESL 为事件相机研究项目，网页对 RGB 演示视频走别名到中文 ONNX。词级 WLASL 模型在目录中备查，整段网页流程尚未接入。项目 docs/reference 下有与官方对齐的中文技术说明文档。""",
        ),
        (
            "【收尾 · 场景、局限与展望】",
            """适用场景包括：听障用户家庭沟通、手语选修课演示、无障碍公益科普、科研复现 Uni-Sign/ONNX 流程，以及作为多模态翻译系统的原型平台。

也要诚实说明局限：手语识别准确率受拍摄角度、光照、背景、模型域差异影响；短片段 ONNX 容易「飘字」；无硬字幕时 OCR 无效；云端混合依赖网络与配额；我们不做手语语法纠错与方言全覆盖；OpenESL 完整事件流需专用相机，网页暂不支持。

展望方向：接入更稳的实时推理、词级与句级混合、手语合成回传、与政务/医疗预约翻译系统对接等。

欢迎大家访问演示地址体验。我的介绍到此结束，谢谢！""",
        ),
    ]

    for sec_title, sec_body in speech_sections:
        add_para(doc, sec_title, bold=True)
        for para in sec_body.strip().split("\n\n"):
            add_para(doc, para)
        doc.add_paragraph()

    doc.add_page_break()

    # ==================== 二、分镜 ====================
    add_heading(doc, "二、视频分镜脚本（详细版 · 成片约 6～8 分钟）", 1)
    add_para(doc, "建议：旁白用第一章配音稿；画面按本表剪辑，可 Accelerate 识别等待片段。", bold=True)

    shots = [
        ("0:00-0:25", "片头", "项目名、Logo、Slogan「让手语被看见」", "手心语界面淡入；轻柔背景音乐起"),
        ("0:25-0:55", "痛点", "沟通鸿沟、听障场景", "示意图：手语↔文字断层；医院/学校剪影"),
        ("0:55-1:45", "架构一页", "四大入口概览", "录屏快速划过底部导航：说话/拍一下/传视频/记录"),
        ("1:45-3:00", "说话详解", "输入、朗读、展示、手写、常用语", "录屏：打字→播放；点展示全屏；手写识别；点常用语卡片"),
        ("3:00-4:30", "拍一下详解", "摄像头、分段、三种模式、停止收尾", "录屏：开始→译文出现；切换 OCR/混合下拉；按停后仍出字"),
        ("4:30-6:00", "传视频详解", "上传、整段5段进度、输出多行、记入记录", "录屏：上传→整段识别→黄框第5/5段→记录页新增一行"),
        ("6:00-6:40", "记录与账号", "历史表、游客/登录、无障碍", "录屏：记录朗读；字号滑条；高对比"),
        ("6:40-7:40", "服务+技术", "部署、.env、流水线", "架构图动画：浏览器→FastAPI→ONNX/OCR/AI；代码目录（密钥打码）"),
        ("7:40-8:10", "局限与展望", "诚实边界、未来", "文字卡片列局限；结尾二维码/网址"),
    ]
    add_table(doc, ["时间", "段落", "旁白/字幕要点", "画面与音效"], shots)

    doc.add_page_break()

    # ==================== 三、项目详细介绍 ====================
    add_heading(doc, "三、项目详细介绍（书面材料，不必全文朗读）", 1)

    add_heading(doc, "3.1 项目名称与版本", 2)
    add_para(
        doc,
        "项目名称：手心语（Palmsign / 手语助手 Web）。当前 Web 服务版本号 2.0.0（FastAPI 应用定义）。"
        "定位：听障沟通辅助 + 手语识别技术验证平台。",
    )

    add_heading(doc, "3.2 建设背景与意义", 2)
    add_bullets(
        doc,
        [
            "听障群体日常沟通依赖手语，健听者理解门槛高，信息不对称影响教育、就业与就医体验。",
            "手语识别（Sign Language Translation, SLT）与孤立手语识别（ISLR）是活跃研究方向，但论文模型少有一键可用的产品形态。",
            "本项目将 Uni-Sign 等前沿工作导出为 ONNX，用 FastAPI 封装为可演示、可部署的 Web 服务，并叠加 OCR 与多模态大模型，贴近「有字幕新闻」与「纯手语」两类真实素材。",
            "同步提供「说话」反向通道（文字→语音/大字），形成双向沟通闭环，而非单向识别演示。",
        ],
    )

    add_heading(doc, "3.3 目标用户", 2)
    add_table(
        doc,
        ["用户类型", "典型需求", "推荐使用功能"],
        [
            ("听障用户本人", "快速表达、留存沟通记录", "说话展示、拍一下、记录"),
            ("家属/志愿者", "理解对方手语、代为朗读", "传视频整段识别、给对方看大字"),
            ("手语教师/学生", "课堂回放、句子核对", "传视频混合模式、手语词本"),
            ("开发者/研究者", "复现 ONNX、对接新模型", "健康检查、模型目录 API、docs/reference"),
            ("机构信息化", "内网部署、数据不出校", "本地 ONNX + 可选关闭云端"),
        ],
    )

    doc.add_page_break()

    # ==================== 四、功能详解 ====================
    add_heading(doc, "四、功能模块详解", 1)

    modules = [
        (
            "4.1 说话（view-speak）",
            [
                "文本输入：pSpeak 文本框，最长 2000 字。",
                "朗读：本机 speechSynthesis；MiniMax TTS（需 MINIMAX_API_KEY）。",
                "展示给对方：phraseShowDialog 全屏大字；partnerMirror 识别后镜像大字。",
                "手写：speakHandCanvas + btnManualHandRecognize；后端 /api/handwriting 等。",
                "常用语：分类、标签、搜索、phraseBoard 卡片、听/展示按钮。",
                "手语词本：vocabulary 表，词/语/类管理（部分 UI 可折叠）。",
                "翻译：DeepSeek 接口，按朗读语言自动译后播放。",
            ],
        ),
        (
            "4.2 拍一下（view-live）",
            [
                "摄像头：getUserMedia，理想 1280×720，仅视频轨。",
                "分段录制：MediaRecorder → webm，默认 liveSegmentSec 6 秒。",
                "循环：liveLoop 勾选则 do-while 直到 liveAbort。",
                "停止语义：停止后当前段识别仍完成（liveSeg 轮询不 cancel）。",
                "连续自动出字：liveContinuousRt，live-rt-*.webm，队列 liveContQueue。",
                "识别任务：POST /api/jobs/translate，realtimeSegment: true。",
                "模型选择：modelSelectLive；识别方式 recognitionModeLive。",
            ],
        ),
        (
            "4.3 传视频（view-video）",
            [
                "上传：POST /api/upload，保存 uploads/{userKey}/...。",
                "整段识别：btnRunVideoJob，realtimeSegment: false，长视频 FFmpeg 切片。",
                "边播：btnVideoRtStart，video-rt-*.webm，videoRtJobQueue 排队。",
                "进度：jobProgressBox / videoJobProgressBox，partialSegmentTexts 增量展示。",
                "记入记录：chkJobHistory；完成后 ensureRecognitionHistory 兜底。",
                "补录：manualText + btnSaveManual 手写区。",
            ],
        ),
        (
            "4.4 记录（view-history）",
            [
                "GET /api/history 列表；POST 手动追加；DELETE 按 id 删除。",
                "字段：createdAt, modelKey, sourceFile, text, note。",
                "自动写入：appendHistory 为真且识别成功；note 含 job-auto; mode=...。",
            ],
        ),
        (
            "4.5 系统功能",
            [
                "认证：注册/登录/退出/游客；Session  Cookie。",
                "模型说明：modelsGuideDialog，/api/models/catalog。",
                "帮助：helpDialog 使用说明。",
                "健康：/api/health 返回 ONNX、脚本、翻译密钥状态。",
                "每日小贴士：/api/tips/today。",
            ],
        ),
    ]
    for title, bullets in modules:
        add_heading(doc, title, 2)
        add_bullets(doc, bullets)

    doc.add_page_break()

    # ==================== 五、服务介绍 ====================
    add_heading(doc, "五、项目服务介绍", 1)

    add_heading(doc, "5.1 服务清单", 2)
    add_table(
        doc,
        ["服务名称", "说明", "依赖"],
        [
            ("手语视频识别", "上传/实时片段 → 文本 + 分段元数据", "ONNX、FFmpeg、可选云端 AI"),
            ("识别任务调度", "异步 job，queued→running→done/error", "ThreadPoolExecutor"),
            ("用户与会话", "注册登录、游客、数据隔离", "SQLite + Session"),
            ("常用语/词库", "CRUD JSON 存储", "无云端"),
            ("识别历史", "自动/手动写入，最多 500 条/用户", "JSON 文件"),
            ("TTS 语音合成", "MiniMax 云端朗读", "MINIMAX_API_KEY"),
            ("手写 OCR", "画布图片识别", "RapidOCR、ZHIPU_API_KEY"),
            ("文本翻译润色", "DeepSeek", "DEEPSEEK_API_KEY"),
            ("混合仲裁", "ONNX+OCR+Kimi+GLM+DeepSeek", "多密钥可选"),
        ],
    )

    add_heading(doc, "5.2 服务级别与部署模式", 2)
    add_bullets(
        doc,
        [
            "单机演示模式：本机 uvicorn，浏览器访问 127.0.0.1:8000，适合开发与答辩。",
            "局域网模式：host 0.0.0.0，同一 WiFi 下手机访问电脑 IP。",
            "内网生产模式：前置 Nginx HTTPS，仅开放必要端口；.env 统一管理密钥。",
            "隐私模式：仅配置 ONNX，不填云端 Key，识别完全离线（准确度依场景而定）。",
        ],
    )

    add_heading(doc, "5.3 数据安全与隔离", 2)
    add_bullets(
        doc,
        [
            "密码 bcrypt 哈希存储；会话密钥 SESSION_SECRET。",
            "上传路径校验：必须属于 uploads/{subjectKey}/，禁止 .. 穿越。",
            "任务查询校验 subjectKey，防越权读他人 job。",
            "游客数据在 GUEST_SESSION_ROOT，清除浏览器数据可能丢失。",
        ],
    )

    doc.add_page_break()

    # ==================== 六、技术架构 ====================
    add_heading(doc, "六、技术架构详解", 1)

    add_heading(doc, "6.1 总体架构", 2)
    add_para(
        doc,
        "Browser（静态 index.html + app.js）"
        " → HTTPS/HTTP → Uvicorn(ASGI) → FastAPI Router"
        " → 业务逻辑（认证/上传/任务/历史）"
        " → 识别子系统（ONNX 子进程 / OCR / hybrid_recognition.py）"
        " → 文件系统（SQLite、JSON、uploads、models/）",
    )

    add_heading(doc, "6.2 识别流水线（整段 · 混合 · 举例）", 2)
    add_bullets(
        doc,
        [
            "1. 接收 videoRelativePath，校验归属，探测时长 effective_dur。",
            "2. dur > 阈值：FFmpeg 切分为 chunk_sec（约 10～12s）片段。",
            "3. 每片段：姿态提取 → ONNX 推理 → 得 onnx 文本，写入 segmentTexts。",
            "4. 并行：全片 burned-in OCR；可选 Kimi/GLM 整段视频理解。",
            "5. 多段时：_hybrid_fuse_video_segments 按段对齐 OCR 行与 ONNX 句。",
            "6. 每段 run_hybrid_fusion → DeepSeek 仲裁 → sanitize 去思考链。",
            "7. 合并 hist_text，validate，写 history，job status=done。",
        ],
    )

    add_heading(doc, "6.3 识别流水线（拍一下 · 快路径）", 2)
    add_bullets(
        doc,
        [
            "realtimeSegment=true 或路径含 live-rt/rt-live。",
            "_run_rt_segment_recognition：轻量 ONNX、少帧。",
            "SNAP_OCR_FIRST：有硬字幕优先 OCR，数秒内返回。",
            "rt_fast：混合模式跳过 Kimi/GLM 外网，本地启发式合并。",
        ],
    )

    add_heading(doc, "6.4 主要 API 一览", 2)
    apis = [
        ("POST /api/auth/register|login|guest", "认证"),
        ("GET /api/auth/me", "当前用户"),
        ("POST /api/upload", "视频上传"),
        ("POST /api/jobs/translate", "创建识别任务"),
        ("GET /api/jobs/{job_id}", "轮询任务状态"),
        ("GET/POST/DELETE /api/history", "识别记录"),
        ("GET/POST /api/phrases", "常用语"),
        ("GET/POST /api/vocabulary", "手语词"),
        ("POST /api/tts/minimax", "云语音"),
        ("GET /api/health", "服务健康"),
        ("GET /api/models/catalog", "模型目录"),
    ]
    add_table(doc, ["接口", "用途"], apis)

    add_heading(doc, "6.5 目录结构（讲解时可展示）", 2)
    add_bullets(
        doc,
        [
            "web/app.py — 主服务入口",
            "web/static/ — 前端页面与脚本",
            "web/hybrid_recognition.py — 混合识别与合议",
            "web/zhipu_vision.py — 智谱视觉/手写",
            "web/model_catalog.py — 模型元数据",
            "models/ — ONNX 与 Uni-Sign 仓库",
            "data/ — 全局 config、SQLite",
            "docs/reference/ — 中文技术文档",
            "requirements-web.txt — Python 依赖",
            ".env — API 密钥（勿提交公开仓库）",
        ],
    )

    doc.add_page_break()

    # ==================== 七、模型与模式 ====================
    add_heading(doc, "七、识别模式与模型选型指南", 1)

    add_table(
        doc,
        ["模式", "读什么", "典型耗时", "适用画面"],
        [
            ("仅 ONNX", "肢体动作→句子", "整段每段1～3分钟", "纯手语、无硬字幕"),
            ("仅 OCR", "底部硬字幕", "5～15秒", "新闻条、教程字幕"),
            ("混合", "ONNX+OCR+AI仲裁", "最长", "既要手语又要字幕，要求最准"),
        ],
    )
    doc.add_paragraph()
    add_table(
        doc,
        ["模型键", "语种", "说明"],
        [
            ("csl_daily", "中文", "日常中文连续手语，Uni-Sign ONNX"),
            ("openesl", "中文", "OpenESL/VECSL 演示 RGB 视频，推理别名到 csl_daily"),
            ("openasl", "英文", "美式手语连续句"),
            ("how2sign", "英文", "教程风格英文手语"),
            ("wlasl_islr", "英文词级", "网页整段流程暂未接入"),
        ],
    )

    doc.add_page_break()

    # ==================== 八、部署 ====================
    add_heading(doc, "八、部署与运行（演示录像前检查）", 1)
    add_bullets(
        doc,
        [
            "安装：pip install -r requirements-web.txt",
            "模型：确保 models/ 下 ONNX 包已解压（启动时自动检查 tar）",
            "配置：复制 .env，填写 DEEPSEEK、ZHIPU、MINIMAX、MOONSHOT 等（按需）",
            "启动：在项目根目录执行 python -m uvicorn web.app:app --host 127.0.0.1 --port 8000",
            "访问：浏览器打开 http://127.0.0.1:8000 ，Ctrl+F5 强刷",
            "FFmpeg：建议安装并加入 PATH，否则长视频无法切片",
            "NumPy：需 >=1.26,<2.0，与 onnxruntime 兼容",
        ],
    )

    # ==================== 九、局限 ====================
    add_heading(doc, "九、适用场景、局限与合规说明", 1)
    add_bullets(
        doc,
        [
            "适用：教学演示、科研复现、家庭辅助沟通原型、无障碍科普。",
            "不适用：法律、医疗等高风险场景的专业翻译替代。",
            "局限：准确率受拍摄条件限制；短片段 ONNX 不稳定；依赖外部 API 时受网络影响。",
            "合规：上传视频需获得被拍摄者同意；云端传输注意机构隐私政策。",
        ],
    )

    # ==================== 十、录制清单 ====================
    add_heading(doc, "十、录屏与剪辑检查清单", 1)
    add_bullets(
        doc,
        [
            "□ 服务已启动，health 绿点正常",
            "□ 准备 30～60 秒中文手语样片 + 一段带底部字幕新闻片段",
            "□ 演示拍一下：双手入镜、停止后仍出字",
            "□ 演示整段：可见第 N/M 段进度与多行输出",
            "□ 演示记入记录：记录页出现新行 + toast",
            "□ 演示说话：朗读 + 全屏展示 + 常用语点击",
            "□ 技术段：架构图自制，.env 密钥打码",
            "□ 导出 1080p，字幕可对照第一章配音稿",
            "□ 背景音乐 -12dB 以下，人声清晰",
        ],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"已生成：{OUT}")


if __name__ == "__main__":
    main()
