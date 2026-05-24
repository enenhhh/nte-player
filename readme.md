# 异环车载播放器桌面还原版

[![Stars](https://img.shields.io/github/stars/enenhhh/nte-player?style=flat-square&color=ff007f)](https://github.com/enenhhh/nte-player/stargazers)
[![License](https://img.shields.io/github/license/enenhhh/nte-player?style=flat-square&color=blue)](https://github.com/enenhhh/nte-player/blob/main/LICENSE)
![Language](https://img.shields.io/github/languages/top/enenhhh/nte-player?style=flat-square&color=3776AB)
![Downloads](https://img.shields.io/github/downloads/enenhhh/nte-player/total?style=flat-square&color=green)

这是一个使用 Python (PyQt6 + Pygame) 编写的电脑桌面悬浮播放器，基本还原了游戏《异环》中的车载播放器界面与交互。

本项目仅用于个人学习和图形界面开发交流。素材均为个人游戏内截图并手动去噪、抠图、优化整理所得，未对游戏客户端进行任何解包。

---

## 下载与使用

1. **一键下载**：直接前往 [Releases 页面](https://github.com/enenhhh/nte-player/releases) 下载打包好的 `app.exe` 单体运行文件（推荐，无需配置任何 Python 环境）。
2. 将 `app.exe` 放到您想运行的任意电脑桌面或目录运行。
3. 首次运行后，它会自动在同级目录下生成一个 `Music` 文件夹。
4. 将您的歌曲文件（支持 .mp3, .wav, .flac, .ogg）放入 `Music` 文件夹中。如果要配封面，把与歌曲同名的图片（jpg / png）一同放入即可。

---

## 已实现功能

* **界面还原**：基本还原了游戏中的播放器样式，包括左侧独立突出的正方形封面与半透明毛玻璃质感的歌单列表。
* **音乐收藏**：支持单曲收藏（我喜欢）。点击最右侧的红心，播放队列和列表将自动切换为仅播放/显示收藏的歌曲。
* **真实律动频谱**：切歌时在后台异步计算歌曲的音量包络线，频谱高度会根据歌曲实际的音量起伏做出真实的律动（需要 pydub 依赖，若无则自动降级为平滑波形动画）。
* **超长歌名滚动**：歌曲名过长时会自动触发跑马灯平滑滚动，解决文本重叠挤压问题。
* **封面自动读取**：支持自动提取 MP3 / FLAC 音频文件内嵌的封面图片。如果文件没有内嵌封面，则尝试读取同级目录下的同名图片，都找不到时展示默认占位图。
* **右键菜单控制**：右键点击播放器可以呼出功能菜单，支持锁定/解锁窗口位置、调整 0.5x 到 2.0x 六档多阶缩放，以及安全退出。
* **自由拉伸高度**：列表展开时，鼠标移到最下方边缘可直接按住左键拖拽，自由调整列表显示的高度。

---

## 本地开发

如果您想直接运行源码或进行二次开发，请按以下步骤操作：

1. 下载本项目源码（下载 ZIP 压缩包或使用 git clone）。
2. 本项目提供了两个版本供您参考：
   * `app.py`：精简干净的主运行程序。
   * `app_annotated.py`：功能完全相同，但附带了极其详细的代码注释，方便想要学习 PyQt6 界面开发的同学阅读。
3. 确保您的电脑安装了 Python 3.10+。
4. 打开终端，使用清华源安装项目所需的第三方依赖库：
   ```bash
   pip install PyQt6 pygame mutagen pydub numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
5. 在源码目录下直接运行：
   ```bash
   python app.py
   ```

---

## 声明与致谢

* **免责声明**：本项目仅限个人学习研究使用，切勿用于任何商业用途。
* **字体声明**：本项目使用了小米科技有限责任公司（小米）发布的免费商用字体 MiSans，版权归属于小米科技有限责任公司。

---

### Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=enenhhh/nte-player&type=Date)](https://star-history.com/#enenhhh/nte-player&Date)
