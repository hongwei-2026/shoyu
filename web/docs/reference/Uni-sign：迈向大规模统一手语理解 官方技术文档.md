# Uni\-sign：迈向大规模统一手语理解 官方技术文档

# 一、项目概述

Uni‑Sign 是一款面向大规模手语理解的统一手语翻译框架，论文被 **ICLR 2025** 收录。项目主打多语种手语通用理解、轻量化姿态提取、在线实时推理，同时公开中文手语数据集、模型权重、训练推理全套代码，是目前国内**最适合个人落地、有权重、有公开数据集、无特殊申请门槛**的中文连续手语翻译开源项目。

若本项目对你有帮助，可在 GitHub 给项目点亮 Star，助力作者持续更新维护。

# 二、项目更新动态

|更新时间|更新内容|
|---|---|
|2025/01/25|论文成功收录于 ICLR 2025|
|2025/02/24|公开 CSL‑News 中文手语数据集及配套代码|
|2025/06/05|发布轻量化姿态提取模型，支持在线实时推理功能|
|2025/12/20|开放纯姿态检测权重，同步上线 How2Sign、OpenASL 美式手语推理代码，适配英文手语研究|

# 三、环境安装部署

## 3\.1 基础环境配置

官方建议独立搭建 Conda 虚拟环境，避免依赖冲突，固定 Python 版本为 3\.9。

```bash
# 创建虚拟环境
conda create --name Uni-Sign python=3.9
# 激活环境
conda activate Uni-Sign
# 批量安装项目依赖
pip install -r requirements.txt
```

## 3\.2 可选依赖（BLEURT评估工具）

若需要在 How2Sign、OpenASL 数据集上进行 BLEURT 分数评估，执行以下命令部署评估工具：

```bash
# 克隆BLEURT评估源码
git clone https://github.com/google-research/bleurt.git
cd bleurt
# 本地安装依赖
pip install .
cd ../
# 下载预训练评估权重
wget https://storage.googleapis.com/bleurt-oss-21/BLEURT-20.zip
# 解压权重文件
unzip BLEURT-20.zip
```

# 四、数据准备

数据集配置流程严格参照项目内 **DATASET\.md** 文档执行，项目公开可用数据集如下：

1. **CSL‑News**：中文手语公开数据集，适配日常中文连续手语翻译；

2. **How2Sign**：英文手语数据集；

3. **OpenASL**：美式手语公开数据集。

# 五、模型权重说明

## 5\.1 权重获取

Uni‑Sign 完整训练模型检查点（Model‑Checkpoints）可在官方指定链接直接下载，**全部公开、无申请门槛、免费可用**。

## 5\.2 权重类型

- 通用完整版权重：适用于训练、评估、高精度手语翻译；

- 纯姿态轻量化权重：体积更小、推理速度更快，适配在线实时推理、摄像头实时识别场景。

# 六、训练与评估流程

所有执行脚本必须在 **Uni‑Sign 项目根目录**内运行，严格遵循三阶段训练流程。

## 6\.1 三阶段训练命令

### 阶段一：纯姿态预训练

```bash
bash ./script/train_stage1.sh
```

### 阶段二：RGB\+姿态融合预训练

```bash
bash ./script/train_stage2.sh
```

### 阶段三：下游任务微调（最终可用模型）

```bash
bash ./script/train_stage3.sh
```

## 6\.2 模型评估命令

完成第三阶段微调后，使用单GPU执行模型性能评估：

```bash
bash ./script/eval_stage3.sh
```

# 七、推理使用说明

## 7\.1 快速体验方案

无需配置环境、无需下载权重，官方公开第二阶段纯姿态手语翻译推理结果，可直接用作效果对比参考。

## 7\.2 在线推理能力

项目支持轻量化姿态提取，适配摄像头实时采集、视频流在线推理，适合开发实时手语翻译小程序、网页、客户端。

# 八、开发人员与联系方式

## 8\.1 项目开发人员

东堂开发团队：负责 CSL‑News 数据集发布、Uni‑Sign 代码实现、轻量化推理功能开发。

## 8\.2 联系邮箱

李泽成：lizecheng19@gmail\.com（技术问题、合作咨询均可联系）

# 九、项目致谢

本项目代码改编自 GFSLT‑VLP，姿态编码器、时间编码器实现参考 CoSign，感谢 CoSign 作者开源代码、无私分享。同时依托多款优秀开源工具完成开发：

- SSVP‑SLT：手语翻译基础框架；

- MMPose：开源人体姿态估计工具箱；

- FUNASR：高性能语音转文字工具。

# 十、引用格式

若使用本项目进行学术研究、项目开发，引用格式如下：

```plain text
@article{li2025uni,
  title={Uni-Sign: Toward Unified Sign Language Understanding at Scale},
  author={Li, Zecheng and Zhou, Wengang and Zhao, Weichao and Wu, Kepeng and Hu, Hezhen and Li, Houqiang},
  journal={arXiv preprint arXiv:2501.15187},
  year={2025}
}
```

# 十一、项目适配总结（针对个人开发）

1. **可用权重**：官方公开完整训练权重\+轻量化姿态权重，无需自己训练；

2. **中文友好**：自带 CSL‑News 中文手语数据集，适配国内手语翻译场景；

3. **硬件门槛低**：轻量化模型支持 CPU 推理，可转 ONNX 脱离 PyTorch；

4. **适配你的项目**：原生支持摄像头在线实时推理，完美匹配「声桥手语翻译助手」开发需求。

> （注：文档部分内容可能由 AI 生成）
