# -*- coding: utf-8 -*-
"""生成《手心语》项目简介 PDF（提交用）。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "手心语-项目简介.pdf"

FONT_PATHS = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]


def register_cn_font() -> tuple[str, str]:
    """返回 (正文字体名, 标题字体名)。"""
    for i, p in enumerate(FONT_PATHS):
        if not p.is_file():
            continue
        try:
            name = "CNBody" if i == 0 else f"CNBody{i}"
            pdfmetrics.registerFont(TTFont(name, str(p), subfontIndex=0))
            pdfmetrics.registerFont(TTFont(name + "Bold", str(p), subfontIndex=0))
            return name, name
        except Exception:
            try:
                pdfmetrics.registerFont(TTFont(name, str(p)))
                return name, name
            except Exception:
                continue
    raise RuntimeError("未找到可用的中文字体，请确认 Windows 字体目录存在 msyh.ttc 或 simsun.ttc")


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def build_styles(body_font: str, title_font: str) -> dict[str, ParagraphStyle]:
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName=title_font,
            fontSize=26,
            leading=34,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName=body_font,
            fontSize=14,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0B6E5E"),
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            fontName=body_font,
            fontSize=11,
            leading=18,
            alignment=TA_CENTER,
            textColor=colors.grey,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=title_font,
            fontSize=16,
            leading=24,
            spaceBefore=14,
            spaceAfter=10,
            textColor=colors.HexColor("#0B6E5E"),
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=title_font,
            fontSize=13,
            leading=20,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=body_font,
            fontSize=11,
            leading=18,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            firstLineIndent=22,
        ),
        "body_nb": ParagraphStyle(
            "body_nb",
            fontName=body_font,
            fontSize=11,
            leading=18,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=body_font,
            fontSize=11,
            leading=17,
            leftIndent=18,
            spaceAfter=4,
        ),
    }


def add_table(
    story: list,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    cell_style: ParagraphStyle,
) -> None:
    def row_paras(cells: list[str]) -> list:
        return [P(c, cell_style) for c in cells]

    data = [row_paras(headers)] + [row_paras(r) for r in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5F2")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.35 * cm))


def main() -> None:
    body_font, title_font = register_cn_font()
    S = build_styles(body_font, title_font)
    S["table_cell"] = ParagraphStyle(
        "table_cell",
        fontName=body_font,
        fontSize=9,
        leading=14,
        alignment=TA_LEFT,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="手心语项目简介",
        author="手心语项目组",
    )
    story: list = []

    # ===== 封面 =====
    story.append(Spacer(1, 3.5 * cm))
    story.append(P("手心语", S["cover_title"]))
    story.append(P("手语识别与双向沟通 Web 应用", S["cover_sub"]))
    story.append(Spacer(1, 0.8 * cm))
    story.append(P("项　目　简　介", S["cover_title"]))
    story.append(Spacer(1, 2 * cm))
    story.append(P(f"文档版本：V2.0　　日期：{date.today().isoformat()}", S["cover_meta"]))
    story.append(P("项目类型：无障碍 / 手语理解 / 多模态 Web 服务", S["cover_meta"]))
    story.append(PageBreak())

    # ===== 摘要 =====
    story.append(P("摘　要", S["h1"]))
    story.append(
        P(
            "「手心语」是一套面向听障人士、家属、手语学习者及无障碍服务场景的 Web 端手语识别与沟通辅助系统。"
            "系统以 Uni-Sign 框架导出的 ONNX 手语翻译模型为核心，结合 FFmpeg 视频分段、RapidOCR 硬字幕识别"
            "及 DeepSeek、智谱 GLM、Moonshot Kimi 等多模态大模型的可选合议能力，实现「摄像头/视频 → 文本」"
            "的高可用工程化路径；并配套文字朗读（本机 TTS / MiniMax）、全屏大字展示、常用语库、手语词本、"
            "识别历史等双向沟通功能。项目采用 FastAPI + 原生 JavaScript 单页架构，支持注册登录与游客试用、"
            "按用户隔离数据，可在单机或局域网内部署，兼顾隐私与可演示性。本文档从背景意义、功能服务、"
            "技术方案、创新特色、部署方式及局限展望等方面对项目进行系统介绍。",
            S["body"],
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    # ===== 一、背景 =====
    story.append(P("一、项目背景与建设意义", S["h1"]))
    story.append(
        P(
            "听障群体在日常生活、教育就业与公共服务中获取信息的渠道，高度依赖手语与文字之间的转换。"
            "然而，健听者普遍不具备手语理解能力，专业手语翻译资源稀缺、预约成本高；"
            "听障用户在现场打字或书写速度有限，面对面沟通中信息易中断。随着深度学习在手语理解（Sign Language Translation, SLT）"
            "与孤立手语识别（ISLR）领域的发展，学术界已出现 Uni-Sign 等统一框架，但多数成果仍以论文与实验代码形式存在，"
            "缺少面向真实场景的 Web 产品化封装。",
            S["body"],
        )
    )
    story.append(
        P(
            "本项目「手心语」旨在弥合「研究成果」与「可用工具」之间的鸿沟：将手语视频识别、字幕 OCR、"
            "多源 AI 仲裁与听障侧表达辅助（朗读、大字、常用语）整合为一体化 Web 服务，"
            "服务于家庭沟通、课堂教学、公益科普、科研复现与机构信息化试点，"
            "为无障碍环境建设提供可部署、可扩展的技术样板。",
            S["body"],
        )
    )

    # ===== 二、定位 =====
    story.append(P("二、项目定位与建设目标", S["h1"]))
    story.append(P("2.1 项目定位", S["h2"]))
    story.append(
        P(
            "手心语定位为「手语识别 + 沟通辅助」一体化的 Web 应用平台（版本 2.0.0），"
            "核心能力是连续手语视频/实时片段到可读文本，辅以反向通道（文本到语音/大字）。"
            "项目明确不替代持证手语翻译，适用于非高风险、非法律效力的日常与教学辅助场景。",
            S["body"],
        )
    )
    story.append(P("2.2 建设目标", S["h2"]))
    goals = [
        "工程化：完成从视频输入、姿态提取、ONNX 推理到结果展示的端到端流水线；",
        "多场景：支持上传长视频整段识别、摄像头分段「拍一下」、边播预览三种典型用法；",
        "多模态：在 ONNX 基础上可选 OCR 与云端大模型混合，提升有硬字幕素材的可用性；",
        "双向沟通：提供说话、展示、常用语、词库、历史记录，形成识别—表达闭环；",
        "可部署：支持本地/局域网部署，密钥服务端集中配置，用户数据按账号隔离；",
        "无障碍：字号调节、高对比、语义化页面结构与读屏友好设计。",
    ]
    for g in goals:
        story.append(P(f"• {g}", S["bullet"]))

    # ===== 三、功能 =====
    story.append(P("三、系统功能详细介绍", S["h1"]))

    story.append(P("3.1 模块总览", S["h2"]))
    add_table(
        story,
        ["模块", "入口", "主要能力"],
        [
            ["说话", "底部导航「说话」", "文本输入、朗读、全屏展示、手写识别、常用语、手语词本、翻译朗读"],
            ["拍一下", "「拍一下」", "摄像头分段录制、自动识别、连续字幕、三种识别模式"],
            ["传视频", "「传视频」", "文件上传、整段多段识别、边播预览、补录存历史"],
            ["记录", "「记录」", "识别历史查看、朗读、删除、自动/手动写入"],
        ],
        [3.2 * cm, 3.2 * cm, 10.1 * cm],
        S["table_cell"],
    )

    story.append(P("3.2 「说话」— 表达与朗读", S["h2"]))
    story.append(
        P(
            "用户可输入最多 2000 字文本，选择朗读语言，通过浏览器本机 speechSynthesis 或 MiniMax 云端 TTS 播放；"
            "「展示给对方」以全屏大字对话框呈现，适合嘈杂环境面对面交流。"
            "手写面板支持画布输入，后端优先 RapidOCR 本地识别，失败时回退智谱 GLM 视觉识图。"
            "右侧「我的话」管理常用语，支持分类、搜索、一键听/展示；可展开手语词本维护词汇。"
            "可选 DeepSeek 翻译后朗读，便于跨语种沟通。",
            S["body"],
        )
    )

    story.append(P("3.3 「拍一下」— 实时摄像头识别", S["h2"]))
    story.append(
        P(
            "大屏摄像头预览，默认每约 6 秒录一段 WebM，录满自动上传识别；支持循环录制至手动停止，"
            "停止后仍完成当前段识别以免结果丢失。识别模式：① 仅 ONNX—解读肢体动作，纯手语约 20～60 秒/段；"
            "② 仅 OCR—读取画面硬字幕，约 5～15 秒；③ 混合—ONNX+OCR+多 Agent 仲裁，输出净译文。"
            "「连续自动出字」模式每 3～8 秒排队识别，适合快速浏览。支持中/英文手语模型快捷切换。",
            S["body"],
        )
    )

    story.append(P("3.4 「传视频」— 离线高精度识别", S["h2"]))
    story.append(
        P(
            "用户上传 mp4 等文件至个人 uploads 目录。左侧「整段识别」对长视频按约 10～12 秒 FFmpeg 切分，"
            "逐段姿态提取与 ONNX 推理，进度显示「第 N/M 段」，输出区按句展示；混合模式对每段分别 OCR 对齐与仲裁后合并。"
            "右侧「边播边出字」按 6～10 秒切段预览，速度更快、准确度略低。"
            "可勾选「记入记录」；有硬字幕素材建议 OCR/混合，纯手语建议 ONNX/混合。",
            S["body"],
        )
    )

    story.append(P("3.5 账号、无障碍与系统功能", S["h2"]))
    story.append(
        P(
            "支持用户注册、登录及游客试用（会话级数据）。顶栏提供字号 100%～140% 调节、高对比模式、"
            "模型说明对话框、帮助与连接健康状态。识别结果可触发「给对方看」全屏镜像大字。"
            "识别历史表按时间、模型、来源文件管理，支持朗读与删除。",
            S["body"],
        )
    )

    story.append(PageBreak())

    # ===== 四、服务 =====
    story.append(P("四、项目服务内容与交付形态", S["h1"]))
    add_table(
        story,
        ["服务项", "说明", "依赖条件"],
        [
            ["手语视频识别", "上传/实时片段 → 文本 + 分段元数据", "ONNX 模型、FFmpeg；混合需云端 Key"],
            ["异步任务调度", "queued → running → done/error，前端轮询", "ThreadPoolExecutor"],
            ["用户与数据", "认证、常用语、词库、历史、上传隔离", "SQLite + JSON"],
            ["语音合成", "MiniMax TTS", "MINIMAX_API_KEY"],
            ["手写 OCR", "画布 → 文本", "RapidOCR；可选 ZHIPU_API_KEY"],
            ["翻译润色/仲裁", "DeepSeek 多 Agent 合议", "DEEPSEEK_API_KEY 等"],
        ],
        [3.5 * cm, 7.5 * cm, 5.5 * cm],
        S["table_cell"],
    )
    story.append(
        P(
            "交付模式包括：① 单机演示（127.0.0.1）；② 局域网服务（0.0.0.0）；③ 内网生产（Nginx + HTTPS）；"
            "④ 隐私模式（仅 ONNX，不配置云端密钥）。所有 API Key 通过服务端 .env 加载，不暴露给浏览器。",
            S["body"],
        )
    )

    # ===== 五、技术 =====
    story.append(P("五、技术方案与系统架构", S["h1"]))
    story.append(P("5.1 总体架构（四层）", S["h2"]))
    layers = [
        "表现层：HTML5 + CSS + 原生 JavaScript 模块化单页应用，响应式布局；",
        "应用层：FastAPI + Uvicorn，REST API、Session 会话、异步识别任务；",
        "识别层：ONNX Runtime 推理、OpenCV 读帧、FFmpeg 切片、RapidOCR、hybrid_recognition 混合合议；",
        "数据层：SQLite 用户库、每用户 JSON（短语/词库/历史）、uploads 分目录存储。",
    ]
    for L in layers:
        story.append(P(f"• {L}", S["bullet"]))

    story.append(P("5.2 识别流水线（整段 · 混合）", S["h2"]))
    steps = [
        "接收视频路径，校验用户权限，探测有效时长；",
        "超过阈值则 FFmpeg 切分为多段；",
        "每段：人体姿态估计 → ONNX 自回归解码得句子；",
        "并行：全片硬字幕 OCR；可选 Kimi/GLM 视频理解；",
        "多段混合：逐段 ONNX 与 OCR 行对齐，run_hybrid_fusion 仲裁；",
        "sanitize 去除模型思考链，校验语种，可选写入识别历史，返回 job 结果。",
    ]
    for i, s in enumerate(steps, 1):
        story.append(P(f"{i}. {s}", S["bullet"]))

    story.append(P("5.3 快路径（拍一下 / 边播）", S["h2"]))
    story.append(
        P(
            "realtimeSegment 标记触发 rt 路径：轻量姿态、少帧数、SNAP_OCR_FIRST 优先字幕、"
            "rt_fast 混合模式减少外网调用，在数秒到数十秒内返回，适配实时交互。",
            S["body"],
        )
    )

    story.append(P("5.4 主要技术栈", S["h2"]))
    add_table(
        story,
        ["类别", "技术选型"],
        [
            ["语言/框架", "Python 3.10+、FastAPI、Uvicorn、Pydantic"],
            ["前端", "原生 JavaScript (ES Module)、无构建链"],
            ["推理", "ONNX Runtime、OpenCV、Uni-Sign 导出工具链"],
            ["视频", "FFmpeg（tools/ffmpeg 内置 Windows 可执行文件）"],
            ["OCR", "rapidocr-onnxruntime"],
            ["云端（可选）", "DeepSeek、智谱 zai-sdk、Moonshot Kimi、MiniMax TTS"],
            ["安全", "passlib bcrypt、Session 中间件、上传路径校验"],
        ],
        [4 * cm, 12.5 * cm],
        S["table_cell"],
    )

    # ===== 六、模型 =====
    story.append(P("六、模型支持与识别模式", S["h1"]))
    add_table(
        story,
        ["模式", "原理", "适用场景", "典型耗时"],
        [
            ["仅 ONNX", "姿态 → 手语翻译模型", "纯手语、无硬字幕", "整段每段 1～3 分钟"],
            ["仅 OCR", "RapidOCR 读底部字幕", "新闻/教程硬字幕", "5～15 秒"],
            ["混合", "ONNX+OCR+AI 仲裁", "要求最高准确率", "较长"],
        ],
        [2.5 * cm, 4.5 * cm, 5 * cm, 4.5 * cm],
        S["table_cell"],
    )
    add_table(
        story,
        ["模型", "语种", "说明"],
        [
            ["CSL-Daily", "中文", "日常中文连续手语，Uni-Sign ONNX"],
            ["OpenESL/VECSL", "中文", "演示 RGB 视频路径，推理别名至 CSL-Daily"],
            ["OpenASL", "英文", "美式手语连续句"],
            ["How2Sign", "英文", "教程风格英文手语"],
        ],
        [3.5 * cm, 2 * cm, 11 * cm],
        S["table_cell"],
    )

    # ===== 七、创新 =====
    story.append(P("七、项目特色与创新点", S["h1"]))
    innovations = [
        "产品化封装：将 Uni-Sign/ONNX 学术流水线封装为可一键启动的 Web 服务，降低使用门槛；",
        "多源混合合议：ONNX、硬字幕 OCR、视频大模型可选融合，DeepSeek 仲裁并过滤思考链，只展示净译文；",
        "双向沟通闭环：不仅「手语→字」，还提供「字→音/大字」与常用语库，覆盖听障表达与健听理解双向需求；",
        "分场景任务隔离：整段、边播、拍一下分 scope 取消轮询，避免互相中断；",
        "长视频分段策略：自动按时长切分、逐段识别、进度可视化与历史拼接写入；",
        "无障碍工程实践：字号、高对比、语义标签、跳过链接与提交用说明文档体系（docs/reference）。",
    ]
    for inv in innovations:
        story.append(P(f"• {inv}", S["bullet"]))

    # ===== 八、部署 =====
    story.append(P("八、部署与运行环境", S["h1"]))
    story.append(
        P(
            "环境要求：Python 3.10+；建议 NumPy ≥1.26 且 &lt;2.0 以兼容 ONNX Runtime；"
            "Windows 可使用项目内置 tools/ffmpeg/bin；模型权重需放置于 models/ 对应目录（体积较大，单独分发）。",
            S["body"],
        )
    )
    deploy_steps = [
        "pip install -r requirements.txt",
        "复制 .env.example 为 .env 并填写密钥（按需）",
        "python -m uvicorn web.app:app --host 127.0.0.1 --port 8000",
        "浏览器访问并 Ctrl+F5 强刷缓存",
    ]
    story.append(P("快速启动步骤：", S["body_nb"]))
    for s in deploy_steps:
        story.append(P(f"• {s}", S["bullet"]))

    # ===== 九、场景 =====
    story.append(P("九、典型应用场景", S["h1"]))
    scenarios = [
        "听障用户家庭日常：拍一下识别 → 展示大字或朗读给家属；",
        "手语课程：上传课堂回放视频整段识别 → 逐句核对；",
        "公益科普展览：游客模式快速体验手语识别；",
        "科研教学：复现 ONNX 推理与混合识别流程，阅读 docs/reference 中文技术文档；",
        "机构内网试点：仅本地 ONNX，数据不出域。",
    ]
    for sc in scenarios:
        story.append(P(f"• {sc}", S["bullet"]))

    # ===== 十、局限 =====
    story.append(P("十、局限、风险与合规说明", S["h1"]))
    story.append(
        P(
            "识别准确率受拍摄角度、光照、背景 clutter、模型训练域影响；短片段 ONNX 可能出现「飘字」；"
            "无硬字幕时 OCR 无效；混合模式依赖外网与 API 配额；OpenESL 完整事件流需专用相机，网页暂不支持 RGB 以外格式；"
            "本项目不适用于法律、医疗等高风险专业翻译场景。上传视频须获得被摄者同意；"
            "公开发布时注意 .env 密钥与第三方模型/FFmpeg 再分发许可。",
            S["body"],
        )
    )

    # ===== 十一、展望 =====
    story.append(P("十一、后续工作与展望", S["h1"]))
    future = [
        "优化实时推理延迟与稳定性，探索流式识别；",
        "接入词级 WLASL 与句级 SLT 的混合交互；",
        "手语合成（Sign Language Production）回传通道；",
        "与政务、医疗预约翻译系统的标准接口对接；",
        "持续跟进 Uni-Sign、OpenESL 等官方权重发布与合规分发。",
    ]
    for f in future:
        story.append(P(f"• {f}", S["bullet"]))

    # ===== 附录 =====
    story.append(PageBreak())
    story.append(P("附录 A：主要 API 接口", S["h1"]))
    apis = [
        "POST /api/auth/register|login|guest — 认证",
        "POST /api/upload — 视频上传",
        "POST /api/jobs/translate — 创建识别任务",
        "GET /api/jobs/{job_id} — 查询任务",
        "GET|POST|DELETE /api/history — 识别记录",
        "GET|POST /api/phrases — 常用语",
        "GET|POST /api/vocabulary — 手语词库",
        "GET /api/health — 服务健康",
        "GET /api/models/catalog — 模型目录",
    ]
    for a in apis:
        story.append(P(f"• {a}", S["bullet"]))

    story.append(P("附录 B：项目目录结构（核心）", S["h1"]))
    dirs = [
        "web/app.py — 主服务；web/hybrid_recognition.py — 混合识别",
        "web/static/ — 前端页面；web/model_catalog.py — 模型元数据",
        "models/Uni-Sign-repo/onnx_tools/ — ONNX 推理脚本",
        "tools/ffmpeg/bin/ — FFmpeg 可执行文件（Windows）",
        "docs/reference/ — 中文技术参考文档",
        "data/、uploads/ — 运行时数据（不纳入版本库）",
    ]
    for d in dirs:
        story.append(P(f"• {d}", S["bullet"]))

    story.append(Spacer(1, 1 * cm))
    story.append(P("—— 文档结束 ——", S["cover_meta"]))

    # 修复表格中文字体：用 Paragraph 包一层（简化：表格用 body 样式重建）
    doc.build(story)
    print(f"已生成: {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
