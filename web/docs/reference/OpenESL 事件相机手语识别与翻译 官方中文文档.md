# OpenESL 事件相机手语识别与翻译 官方中文文档

# 一、项目简介

**OpenESL** 是国内最新开源、基于**事件相机（Event Camera）**的手语识别与翻译项目。区别于传统普通RGB摄像头，本项目使用事件流采集手语动作，具有超低延迟、抗光照干扰、高速动作捕捉等优势。

项目主打**事件流手语、帧流\+事件流融合手语**两大研究方向，公开两套中文手语高清基准数据集，适合高精度、低延迟、嵌入式端手语设备开发。

- 采集设备：事件相机（Event Camera）

- 数据类型：事件流、普通视频帧、双模态融合数据

- 语种：纯中文手语（CSL）

- 适用方向：实时手语翻译、暗光环境识别、穿戴式手语设备、嵌入式部署

- 项目特点：高帧率、低延迟、抗抖动、暗光识别能力极强

# 二、项目更新日志

|更新时间|更新内容|
|---|---|
|2024/08/19|发布 **Event\-CSL 事件手语基准数据集**，构建事件流手语翻译基线|

# 三、两大公开数据集介绍

## 3\.1 Event\-CSL（纯事件流手语数据集）

**论文：**arXiv:2408\.10488

**全称：**Event Stream\-based Sign Language Translation

国内首套高清事件相机中文手语数据集。使用事件相机采集手语，只捕捉动作变化像素，无冗余画面，具备极低延迟、抗光照、抗模糊特性。

- 数据形式：纯事件流（Event Stream）

- 画面质量：高清、无运动模糊

- 适用场景：高速手语动作、暗光环境、嵌入式硬件

- 配套演示视频：sign\_demo\.mp4

## 3\.2 VECSL（帧\+事件双模态手语数据集）

**论文：**arXiv:2503\.06484

**全称：**Frame and Event Stream Sign Language Translation

融合普通RGB视频帧\+事件流双模态，兼顾画面纹理与动作变化，识别精度最高，是目前综合能力最强的中文手语基准数据集。

- 数据形式：RGB视频帧 \+ 事件流双通道

- 优势：既保留人脸、手部纹理，又捕捉细微手势变化

- 适用：高精度连续中文手语翻译

- 配套演示视频：vecsl\_github\_demo\.mp4（时长1分23秒）

# 四、项目配套资源

## 4\.1 论文资源

1. Event\-CSL 论文：https://arxiv\.org/abs/2408\.10488

2. VECSL 论文：https://arxiv\.org/abs/2503\.06484

## 4\.2 外部开源资源

- 论文代码汇总页：`https://paperswithcode\.com/task/sign\-language\-recognition/codeless`（国内解析失败、无法直连）

- Awesome\-Sign\-Language 手语资源汇总库：`https://github\.com/ZechengLi19/Awesome\-Sign\-Language`（Uni‑Sign作者维护，最全手语开源集合）

# 五、数据集特点对比（通俗易懂）

|数据集|数据流|优点|缺点|适合人群|
|---|---|---|---|---|
|Event\-CSL|纯事件流|极快、低功耗、不怕暗光|无彩色画面、纹理缺失|硬件嵌入式开发|
|VECSL|视频\+事件双模态|精度最高、动作纹理全覆盖|算力要求更高|高精度翻译、学术研究|

# 六、引用格式

## 6\.1 Event\-CSL 引用

```plain text
@misc{wang2025eventcsl,
      title={Event Stream-based Sign Language Translation: A High-Definition Benchmark Dataset and A Novel Baseline}, 
      author={Shiao Wang and Xiao Wang and Duoqing Yang and Yao Rong and Fuling Wang and Jianing Li and Lin Zhu and Bo Jiang},
      year={2025},
      eprint={2408.10488},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
}
```

## 6\.2 VECSL 引用

```plain text
@article{wang2025FESLT,
  title={Sign language translation using frame and event stream: Benchmark dataset and algorithms},
  author={Wang, Xiao and Li, Yuehang and Wang, Fuling and Jiang, Bo and Wang, Yaowei and Tian, Yonghong and Tang, Jin and Luo, Bin},
  journal={arXiv preprint arXiv:2503.06484},
  year={2025}
}
```

# 七、国内使用限制说明

> **【重要提示】**
> 
> 1、paperswithcode 链接国内**网页解析失败**，无法直接打开；
> 
> 2、目前官方**未公开完整训练权重**，仅公开论文、演示视频；
> 
> 3、事件相机硬件昂贵，普通电脑摄像头**无法采集事件流数据**；
> 
> 4、普通RGB摄像头项目不建议优先使用本模型。
> 
> 

# 八、个人开发适配总结（专属你的项目）

1. **适用场景**：未来做硬件、嵌入式、特殊摄像头可以用；

2. **不适用场景**：现在普通电脑摄像头、手机摄像头不要用；

3. **权重情况**：暂无公开权重、暂不可直接部署推理；

4. **推荐排序**：Uni\-Sign \&gt; WLASL \&gt;\&gt; OpenESL；

5. **定位**：本项目属于前沿科研数据集，不适合新手快速做Demo。

> （注：文档部分内容可能由 AI 生成）
