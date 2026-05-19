# WLASL 词级美国手语大规模数据集 官方中文文档

# 一、项目简介

**WLASL** 是开源大规模词级手语视频数据集，论文发表于 WACV 2020，获得**最佳论文荣誉提名**。

本仓库为论文《Word\-level Deep Sign Language Recognition from Video: A New Large\-scale Dataset and Methods Comparison》官方代码库。

用途：**孤立单词手语识别、手势分类、轻量手语模型训练、摄像头实时单词识别**。

- 语种：美国手语（ASL）

- 数据形式：短视频手语、单词语义、标注完整

- 模型支持：I3D、TGCN姿态模型

- 难度：极低、新手友好、可CPU推理、可转ONNX

# 二、重要前置说明（国内必看）

> **【致命限制】**
> 
> 1、数据集原始视频全部托管在 YouTube，**国内无法直接下载**；
> 
> 2、官方缺失视频申请表单为 Google 表单，**国内无法访问**；
> 
> 3、无需尝试原版下载流程，国内用户**百分百下不到完整原版视频**。
> 
> **解决办法：网上已有别人打包好的 WLASL2000 完整数据集（国内网盘），可直接下载。**
> 
> 

# 三、环境依赖说明

## 3\.1 视频下载工具

原项目依赖 YouTube 视频下载工具：

- youtube\-dl：维护停滞，大量视频失效

- **yt\-dlp（推荐）**：youtube\-dl 升级版，目前唯一可用

注意：YouTube 频繁更新反爬机制，使用 yt\-dlp 必须保持最新版本。

# 四、原版下载流程（国外可用、国内不可用）

## 4\.1 拉取代码

```bash
git clone https://github.com/dxli94/WLASL.git
```

## 4\.2 下载原始视频

```bash
cd start_kit
python video_downloader.py
```

## 4\.3 预处理视频片段

```bash
python preprocess.py
```

处理完成后视频保存至：`videos/` 目录

# 五、缺失视频补充方案

YouTube 视频链接经常过期，下载数据集普遍缺失部分视频。官方补充方案：

## 5\.1 生成缺失视频清单

```bash
python find_missing.py
```

生成 `missing\.txt` 记录缺失视频ID。

## 5\.2 官方补全申请（国内不可用）

谷歌表单申请地址：`https://docs\.google\.com/forms/d/e/1FAIpQLSc3yHyAranhpkC9ur\_Z\-Gu5gS5M0WnKtHV07Vo6eL6nZHzruw/viewform?usp=sf\_link`

提示：境外网页，国内无法访问。作者承诺7天内补发缺失视频链接。

# 六、仓库文件结构说明

|文件名称|作用说明|
|---|---|
|WLASL\_vx\.x\.json|全部数据集标注、标签、视频信息总文件|
|data\_reader\.py|数据集加载示例代码|
|video\_downloader\.py|YouTube视频下载脚本|
|preprocess\.py|视频截取、预处理脚本|
|C\-UDA\-1\.0\.pdf|数据使用协议（必须遵守）|

# 七、数据标注字段详解

JSON 内部所有字段官方释义：

- **gloss**：手语单词标签（英文）

- **bbox**：人体手部框选坐标 \(xmin,ymin,xmax,ymax\)

- **fps**：固定帧率 25

- **frame\_start**：手语起始帧

- **frame\_end**：手语结束帧，\-1代表视频末尾

- **instance\_id**：同手势不同样本编号

- **signer\_id**：手语表演者编号

- **source**：视频来源站点

- **split**：训练集/测试集/验证集划分

- **url**：原YouTube下载链接

- **variation\_id**：手语方言差异编号

- **video\_id**：视频唯一ID

# 八、数据集子集划分

根据词频筛选，官方划分4个难度子集：

1. **WLASL100**：100个高频手语单词

2. **WLASL300**：300个高频单词

3. **WLASL1000**：1000个单词

4. **WLASL2000**：全集，2000个手语单词（最常用）

# 九、模型训练与测试教程

## 9\.1 I3D 视频手语模型（最常用）

### （1）环境准备

```bash
mkdir data
# 将视频放入 data/ 路径
cp WLASL2000 -r data/
```

### （2）训练命令

```bash
# 提前下载I3D预训练权重放入 I3D/weights/
python train_i3d.py
```

### （3）测试命令

```bash
# 下载WLASL官方预训练权重放入 I3D/archived/
python test_i3d.py
```

## 9\.2 TGCN 姿态关键点模型

使用人体骨骼关键点进行手语识别，轻量化、适合前端部署。

1. 下载姿态关键点压缩包；

2. 解压至：`WLASL/data/`；

3. 修改训练代码路径为项目根目录；

```bash
# 训练
python train_tgcn.py
# 测试（权重放入 code/TGCN/archived）
python test_tgcn.py
```

# 十、许可协议

- 协议：C\-UDA 1\.0 数据使用协议

- 限制：**仅限学术使用，禁止商业用途**

- 版权：尊重视频原作者版权，不可私自倒卖数据集

# 十一、引用文献

```plain text
@inproceedings{li2020word,
 title={Word-level Deep Sign Language Recognition from Video: A New Large-scale Dataset and Methods Comparison},
 author={Li, Dongxu and Rodriguez, Cristian and Yu, Xin and Li, Hongdong},
 booktitle={The IEEE Winter Conference on Applications of Computer Vision},
 pages={1459--1469},
 year={2020}
}

```

# 十二、个人开发适配总结（给你专用）

1. **用途**：适合做「孤立手势、单词手语识别」，不适合长句连续手语；

2. **难度**：最简单入门手语数据集，代码干净、依赖少；

3. **硬件**：最低4GB显存即可训练，CPU也能推理；

4. **国内现状**：原版下载渠道全部失效，必须使用别人打包好的国内网盘完整版；

5. **适配你的项目**：适合做本地兜底识别（简单单词手语），复杂句子用Uni\-Sign。

> （注：文档部分内容可能由 AI 生成）
