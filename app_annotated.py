# =============================================================================
# 文件名称: app.py
# 项目说明: 桌面悬浮音乐播放器（基于 PyQt6 + pygame）
#
# 功能概览:
#   1. 扫描本地 Music 目录中的 .mp3/.wav/.ogg/.flac 音频文件并构建播放队列。
#   2. 提供胶囊形态的悬浮控制条（无边框、置顶、半透明），支持拖动与缩放。
#   3. 支持 顺序循环 / 单曲循环 / 随机播放 三种播放模式。
#   4. 支持收藏（爱心）、按收藏过滤播放队列、收藏数据持久化到 favorites.json。
#   5. 支持读取 ID3/FLAC 内嵌封面，或回退到磁盘同名图片。
#   6. 通过 pydub + numpy 在后台线程计算歌曲 RMS 音量包络线，驱动频谱条幅度。
#   7. 支持右键菜单：锁定位置、调整缩放比例、退出。
#   8. 支持向下边缘拖拽以纵向拉伸列表区域。
#
# 依赖:
#   - PyQt6           : 界面框架
#   - pygame          : 音频播放后端（mixer.music）
#   - mutagen (可选)  : 读取音频元数据（时长、内嵌封面）
#   - pydub  (可选)   : 解码音频以分析 RMS（依赖 ffmpeg）
#   - numpy  (可选)   : 数值计算 RMS 包络
#
# 设计要点:
#   - 任何外部高级库都做了"软依赖"处理，缺失时仅降级相关功能而不崩溃。
#   - 所有耗时计算（音量包络）都放到 QThread 后台线程，避免阻塞主 UI 事件循环。
#   - 资源路径统一通过 resource_path() 解析，兼容 PyInstaller 单文件打包模式。
# =============================================================================

import os
# 在导入 pygame 之前设置该环境变量，可彻底静默 pygame 启动时打印的
# "Hello from the pygame community..." 等终端提示信息，
# 让带 GUI 的程序在控制台看起来更"干净"。
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

import sys                                       # 进程参数、退出、PyInstaller 标记 _MEIPASS
import json                                      # 持久化收藏列表 favorites.json
import random                                    # 随机播放模式时随机选歌
import math                                      # 频谱波形使用 sin/cos 合成
from PyQt6 import QtWidgets, QtCore, QtGui       # PyQt6 三大命名空间：控件、核心、图形
import pygame                                    # 音频播放后端

# ---------------------------------------------------------------------------
# 可选依赖：mutagen
# 用于读取 MP3/FLAC 的元数据：歌曲时长（毫秒）和内嵌专辑封面（APIC/Picture）。
# 如果用户环境未安装 mutagen，这里把模块名置为 None，后面所有调用点都会
# 检查 `if not mutagen` 来做"功能降级"，比如不显示内嵌封面、时长返回 0。
# ---------------------------------------------------------------------------
try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC
    from mutagen.flac import FLAC
except ImportError:
    mutagen = None

# ---------------------------------------------------------------------------
# 可选依赖：numpy + pydub
# 用于离线解析整首歌的 PCM 样本并计算 RMS（均方根）音量包络线，
# 该包络线会驱动频谱条的"音量呼吸感"动画。
# pydub 依赖 ffmpeg/avconv 才能解码 mp3/flac 等格式，环境若不齐全则降级为
# 仅靠 sin/cos 合成动画（没有"随声音起伏"的效果）。
# ---------------------------------------------------------------------------
try:
    import numpy as np
    from pydub import AudioSegment
except ImportError:
    np = None
    AudioSegment = None

# 初始化 pygame 的音频混音器子系统。必须在 pygame.mixer.music 任意 API
# 调用之前完成；这里采用默认参数（freq/size/channels/buffer 都用默认值）。
pygame.mixer.init()

# 全局字体名称变量。默认使用 Windows 自带的微软雅黑作为兜底；
# 程序启动时若成功加载本地的 misans.ttf，会把这里替换为 misans 的字体族名。
FONT_FAMILY = "Microsoft YaHei"


def resource_path(relative_path):
    """获取打包后资源的绝对路径，兼容开发环境与 PyInstaller。

    - 当通过 PyInstaller 单文件打包并运行时，所有内嵌资源会被解压到一个
      临时目录，路径保存在 `sys._MEIPASS` 中。
    - 直接用 Python 解释器运行源码时，并不存在该属性，于是回退到当前
      工作目录的绝对路径。

    参数:
        relative_path: 相对资源名，例如 "上一首.png"、"misans.ttf"。
    返回:
        资源文件的绝对路径字符串。
    """
    try:
        # PyInstaller 注入的临时解包目录（runtime 解压路径）
        base_path = sys._MEIPASS
    except Exception:
        # 开发环境：以当前工作目录为基准
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class OutlinedLabel(QtWidgets.QLabel):
    """自定义带黑色描边的标签。

    标准 QLabel 直接绘制文字，遇到亮/暗背景切换时会出现"看不清"的情况。
    这里通过重写 paintEvent，在文本周围 8 个方向各偏移 1 像素绘制一遍
    "描边色"，最后再在 (0,0) 位置覆盖绘制一次"主体色"，从而模拟一圈
    黑色 outline 描边效果，保证白色字在任何背景下都清晰可读。
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        # 描边色：接近全黑的高透明度（240/255），让描边足够"沉"
        self.outline_color = QtGui.QColor(0, 0, 0, 240)
        # 文本主体色：默认纯白
        self.text_color = QtGui.QColor(255, 255, 255)
        # 控件最小高度，避免在某些布局里被压成 0
        self.setMinimumHeight(24)

    def set_text_color(self, color_str):
        """外部接口：通过 #RRGGBB 字符串切换文本主体色，并触发重绘。"""
        self.text_color = QtGui.QColor(color_str)
        self.update()

    def paintEvent(self, event):
        # 创建画家对象，所有绘制都通过它进行
        painter = QtGui.QPainter(self)
        # 启用文本抗锯齿，让描边和文字边缘更顺滑
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        # 当前控件的可绘制区域和当前字体（继承自 setFont 设置）
        rect = self.rect()
        font = self.font()
        painter.setFont(font)
        # 当前对齐方式（左/居中/右），与标准 QLabel 对齐策略一致
        align = self.alignment()

        # 第一步：用描边色，按 8 个方向各偏移 1 像素绘制文字，
        #         相当于把字"撑大"一圈，形成黑色 outline。
        painter.setPen(self.outline_color)
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for dx, dy in offsets:
            painter.drawText(rect.translated(dx, dy), align, self.text())

        # 第二步：用主体色，在原位置覆盖绘制一次，得到清晰的字面。
        painter.setPen(self.text_color)
        painter.drawText(rect, align, self.text())


class MarqueeLabel(OutlinedLabel):
    """超长文本自动循环滚动标签（俗称"跑马灯"）。

    在固定宽度的展示区显示歌名时，文字若超出可视范围就会被截断；
    本控件通过 QTimer 周期性地循环偏移文本字符序列，实现"无限横向滚动"
    的视觉效果，且继承 OutlinedLabel 的描边能力。
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        # 当前滚动的"起始字符索引"，每个 tick +1
        self.scroll_pos = 0
        # 完整文本内容（不会被改写，只用于推导每帧显示的子串）
        self._full_text = text
        # 定时器：每 250ms 触发一次滚动，速度温和不晃眼
        self.scroll_timer = QtCore.QTimer(self)
        self.scroll_timer.timeout.connect(self.scroll_text)
        self.scroll_timer.start(250)

    def setText(self, text):
        """重写 setText：除了显示，还要把"滚动源文本"和"位置指针"重置。"""
        self._full_text = text
        self.scroll_pos = 0
        super().setText(text)

    def scroll_text(self):
        """定时回调：根据当前文本宽度判断是否需要滚动，并推进一帧。"""
        if not self._full_text:
            # 空文本无需滚动
            return

        # 利用字体度量获取文本绘制后的像素宽度
        metrics = QtGui.QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._full_text)

        # 文本能完整放下，或控件本身很窄（尚未布局完成）时，不滚动，
        # 始终显示原始内容并把滚动指针归零，避免出现首字符位移问题。
        if text_width <= self.width() or self.width() <= 10:
            self.scroll_pos = 0
            super().setText(self._full_text)
            return

        # 在末尾追加 6 个空格，作为"循环间隙"，让一段文本结束与开头之间
        # 视觉上有自然的空白过渡，否则文字会粘连首尾。
        display_text = self._full_text + "      "
        # 滚动指针自增并对长度取模，实现循环
        self.scroll_pos = (self.scroll_pos + 1) % len(display_text)
        # 经典字符串旋转：把头部 scroll_pos 个字符接到末尾
        rotated_text = display_text[self.scroll_pos:] + display_text[:self.scroll_pos]
        super().setText(rotated_text)


class RMSCalculator(QtCore.QThread):
    """后台异步计算歌曲真实音量包络线，避免阻塞 UI。

    QThread 子类化模式：
        - 在 run() 中执行长任务（这里是整首歌的 PCM 解码 + RMS 分块计算）
        - 计算结果通过 pyqtSignal 发回主线程，由频谱组件接收并消费

    输出:
        result_ready 信号携带一个 list[float]，长度约 200，元素为
        归一化后的 RMS（0 ~ 1），代表 200 个时间分段的相对响度。
    """
    # 自定义信号：list 类型负载，承载归一化的 RMS 数据
    result_ready = QtCore.pyqtSignal(list)

    def __init__(self, file_path):
        super().__init__()
        # 待分析的音频文件绝对路径
        self.file_path = file_path

    def run(self):
        # 缺少必要的库（pydub 或 numpy）则直接返回空列表，让 UI 走兜底动画。
        if not AudioSegment or not np:
            self.result_ready.emit([])
            return
        try:
            # 用 pydub 解码任意支持格式（mp3/wav/flac/ogg 等，依赖 ffmpeg）。
            sound = AudioSegment.from_file(self.file_path)
            # 转成单声道，避免左右声道独立分析带来的复杂度。
            sound = sound.set_channels(1)
            # 取出 PCM 整型样本数组，长度 = 采样率 * 时长。
            samples = np.array(sound.get_array_of_samples())

            # 把整首歌切成 200 段，每段算一个 RMS 值，得到包络线。
            points = 200
            chunk_size = len(samples) // points
            if chunk_size == 0:
                # 非常短的音频（<200 个样本）兜底，避免后面 0 整除。
                chunk_size = 1

            envelope = []
            for i in range(0, len(samples), chunk_size):
                chunk = samples[i:i+chunk_size]
                if len(chunk) > 0:
                    # RMS = sqrt(mean(x^2))，反映这一段的"平均响度"
                    rms = np.sqrt(np.mean(chunk**2))
                    envelope.append(float(rms))
                else:
                    envelope.append(0.0)

            # 归一化到 0 ~ 1，便于在频谱条上当作高度倍率使用。
            max_rms = max(envelope) if envelope else 1.0
            if max_rms == 0:
                # 全静音文件保护，避免除零
                max_rms = 1.0
            normalized = [r / max_rms for r in envelope]
            self.result_ready.emit(normalized)
        except Exception:
            # 任何异常（解码失败、文件损坏、ffmpeg 缺失等）都安全降级，
            # 让 UI 退化为不依赖包络的合成动画。
            self.result_ready.emit([])


class SpectrumWidget(QtWidgets.QWidget):
    """流体频谱组件。

    实现一段视觉"音量条"动画：每一帧由若干条竖直矩形组成，
    高度由两个相位不同的正余弦波叠加而成，再乘以"当前时刻"在
    RMS 包络线上的相对响度，得到既有韵律感又跟随真实音量起伏的效果。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_playing = False    # 是否处于"播放中"状态（暂停时静止）
        self.phase = 0.0           # 正/余弦的相位累加器，每帧自增
        self.envelope = []         # RMS 包络线（0~1），长度约 200
        self.duration_ms = 0       # 当前歌曲总时长（毫秒），用于定位包络索引
        self.scale_factor = 1.0    # 缩放因子（与外部窗口一起缩放粗细/间距）

        # 50ms 心跳定时器（约 20 FPS），驱动相位推进与 update() 重绘
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_spectrum)
        self.timer.start(50)
        # 默认 80x12，配合胶囊条尺寸；缩放时由外部调用 setFixedXxx 改写
        self.setFixedHeight(12)
        self.setFixedWidth(80)

    def set_playing(self, playing):
        """切换播放/暂停的视觉状态（暂停时频谱条压平为基线）。"""
        self.is_playing = playing

    def set_duration_ms(self, duration_ms):
        """设置当前歌曲总时长，用于将播放进度映射到包络索引。"""
        self.duration_ms = duration_ms

    def set_envelope(self, envelope):
        """异步线程算完 RMS 包络后，由信号回调注入到本组件。"""
        self.envelope = envelope

    def update_spectrum(self):
        """定时器回调：推进相位，触发 paintEvent 重绘。"""
        if self.is_playing:
            # 播放时让相位前进，制造流动效果
            self.phase += 0.25
            self.update()
        else:
            # 暂停态也调用一次 update 让画面收敛到"静止 baseline"
            self.update()

    def paintEvent(self, event):
        # 画家 + 抗锯齿，画出顺滑的小矩形条
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        # 鲜亮的柠檬黄色调，与品牌主题色撞色形成视觉焦点
        painter.setBrush(QtGui.QColor("#d4df31"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)

        width = self.width()
        height = self.height()
        # 频谱条的粗细和间隔也参与等比缩放
        bar_width = max(1, int(2 * self.scale_factor))
        spacing = max(1, int(1 * self.scale_factor))
        # 根据可用宽度推导本帧能容纳多少根竖条
        num_bars = int(width / (bar_width + spacing))

        # volume_factor: 当前播放点的"响度倍率"，未拿到包络则保持 1.0
        volume_factor = 1.0
        if self.is_playing and self.envelope and self.duration_ms > 0:
            # pygame.mixer.music.get_pos() 返回当前曲目已播放毫秒数
            current_ms = pygame.mixer.music.get_pos()
            # 按播放进度比例映射到包络数组的索引
            idx = int((current_ms / self.duration_ms) * len(self.envelope))
            # 索引夹紧到合法区间，避免越界
            idx = min(max(idx, 0), len(self.envelope) - 1)
            volume_factor = self.envelope[idx]

        # 逐根竖条绘制：用两个不同频率/相位的三角函数合成出形态多变的波形
        for i in range(num_bars):
            if self.is_playing:
                h1 = math.sin(self.phase + i * 0.4) * 4.0
                h2 = math.cos(self.phase * 0.7 - i * 0.25) * 3.0
                # 加上一个最小高度 2，再乘以响度倍率
                bar_height = int((abs(h1 + h2) + 2) * volume_factor)
                # 限制到 [2, height] 之间，避免负值或溢出
                bar_height = min(max(bar_height, 2), height)
            else:
                # 暂停时所有条都收敛为最低 2 像素
                bar_height = 2
            # 从底部对齐绘制：起点 y = height - bar_height
            painter.drawRect(i * (bar_width + spacing), height - bar_height, bar_width, bar_height)


class DesktopMusicPlayer(QtWidgets.QWidget):
    """桌面悬浮音乐播放器主窗口。

    职责:
      - 持有播放队列、当前曲目、播放模式等状态
      - 组装无边框 + 置顶 + 透明背景的胶囊形态 UI
      - 桥接 pygame.mixer.music 与界面交互（播放/暂停/上一首/下一首）
      - 通过定时器轮询播放完成状态以自动切歌
    """
    def __init__(self):
        super().__init__()
        # 本地音乐目录与收藏存档文件名（相对当前工作目录）
        self.music_dir = "Music"
        self.favorites_file = "favorites.json"

        # 启动时若 Music 目录不存在则自动建立，便于首次使用
        if not os.path.exists(self.music_dir):
            os.makedirs(self.music_dir)

        # ---------- 核心状态控制 ----------
        self.current_song = None        # 当前播放曲目字典 {name, path, cover, liked}
        self.is_paused = False          # 是否处于"暂停"中
        self.play_queue = []            # 实际播放队列（可能被收藏过滤裁剪）
        self.play_mode = 0              # 0: 列表循环, 1: 单曲循环, 2: 随机播放
        self.global_liked_filter = False  # 是否启用"只显示我喜欢"
        self.songs = []                 # 全量扫描得到的曲目
        self.favorites = set()          # 收藏曲名集合（按文件名不带后缀存）

        # ---------- 拖拽 / 调整尺寸状态 ----------
        self.is_resizing = False        # 是否正在通过底部边缘拖拽改高
        self.is_dragging = False        # 是否正在拖动整个窗口
        self.resize_start_y = 0         # 调整尺寸时记录鼠标起始 Y
        self.resize_start_height = 0    # 调整尺寸时记录窗口起始高度
        self.position_locked = False    # 是否锁定位置（锁定后禁止拖动，仍可拉伸）
        self.scale_factor = 1.0         # UI 整体缩放系数（右键菜单可调）

        # 启动顺序：先读收藏，再扫描磁盘合并 liked 状态，最后构建界面
        self.load_favorites()
        self.scan_music_folder()
        self.init_ui()

        # 自动切换歌曲的轮询定时器（pygame.mixer 没有"播完"事件，
        # 这里用 500ms 周期检测 get_busy() 状态实现自动续播/切歌）
        self.track_timer = QtCore.QTimer(self)
        self.track_timer.timeout.connect(self.check_playback_status)
        self.track_timer.start(500)

    def load_favorites(self):
        """从 favorites.json 读取收藏列表（容错：解析失败回退为空集合）。"""
        if os.path.exists(self.favorites_file):
            try:
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    self.favorites = set(json.load(f))
            except Exception:
                # JSON 损坏或编码异常都不应导致程序崩溃
                self.favorites = set()

    def save_favorites(self):
        """把当前收藏集合写回磁盘（UTF-8 + 缩进，便于人工查看）。"""
        with open(self.favorites_file, 'w', encoding='utf-8') as f:
            json.dump(list(self.favorites), f, ensure_ascii=False, indent=4)

    def scan_music_folder(self):
        """扫描 self.music_dir 中所有受支持格式的音频，构建 self.songs 列表。

        - 支持后缀: .mp3 / .wav / .ogg / .flac
        - 同名图片 (.png/.jpg/.jpeg) 视为外置封面，优先级高于内嵌封面
        - 文件名（不含后缀）作为唯一显示名，同时与 favorites 集合对照
        """
        self.songs = []
        if not os.path.exists(self.music_dir):
            return

        supported_exts = ('.mp3', '.wav', '.ogg', '.flac')
        files = os.listdir(self.music_dir)
        for file in files:
            if file.lower().endswith(supported_exts):
                # 拆出"曲名"作为显示名 + 收藏键
                name, _ = os.path.splitext(file)
                path = os.path.join(self.music_dir, file)

                # 在同目录寻找同名外置封面（优先 png > jpg > jpeg）
                cover_path = ""
                for img_ext in ('.png', '.jpg', '.jpeg'):
                    temp_img = os.path.join(self.music_dir, name + img_ext)
                    if os.path.exists(temp_img):
                        cover_path = temp_img
                        break

                # 通过收藏集合判断 liked 状态
                liked = name in self.favorites
                self.songs.append({
                    "name": name,
                    "path": path,
                    "cover": cover_path,
                    "liked": liked
                })

        # 扫描结束后立即根据当前过滤器重建播放队列
        self.update_play_queue()

    def update_play_queue(self):
        """根据 global_liked_filter 切换"全部曲目" / "仅收藏"作为实际队列。"""
        if self.global_liked_filter:
            self.play_queue = [s for s in self.songs if s["liked"]]
        else:
            # 注意复制一份列表，避免外部对队列的修改影响 self.songs
            self.play_queue = self.songs.copy()

    def get_current_queue_index(self):
        """查找当前曲目在 play_queue 中的下标；未在队列中或无当前曲目返回 -1。"""
        if not self.current_song:
            return -1
        for idx, s in enumerate(self.play_queue):
            if s["name"] == self.current_song["name"]:
                return idx
        return -1

    def get_embedded_cover(self, file_path):
        """读取音频文件的内嵌封面字节流。

        - mp3: 读取 ID3 帧中的 APIC 图片
        - flac: 读取 FLAC 自带的 pictures 列表的第一张
        - 缺少 mutagen 或读取失败一律返回 None
        返回值: bytes 或 None。
        """
        if not mutagen:
            return None
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                audio = MP3(file_path, ID3=ID3)
                if audio.tags:
                    # ID3 帧里可能有多个 tag，遍历找到 APIC 图片帧
                    for tag in audio.tags.values():
                        if isinstance(tag, APIC):
                            return tag.data
            elif ext == ".flac":
                audio = FLAC(file_path)
                if audio.pictures:
                    return audio.pictures[0].data
        except Exception:
            # 任何元数据异常都视为"没有封面"，保持稳定性
            pass
        return None

    def get_song_duration_ms(self, file_path):
        """读取曲目时长（毫秒）。失败或缺 mutagen 则返回 0。"""
        if not mutagen:
            return 0
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                audio = MP3(file_path)
                # mutagen 暴露的 length 单位是秒（float），需 *1000 转毫秒
                return int(audio.info.length * 1000)
            elif ext == ".flac":
                audio = FLAC(file_path)
                return int(audio.info.length * 1000)
        except Exception:
            pass
        return 0

    # --- UI 初始化 ---
    def init_ui(self):
        """构建窗口、布局以及所有控件，并应用样式表与阴影。

        UI 结构：
            grid_layout (2 列 x 2 行)
              ┌────────────────┬─────────────────────────────────────┐
              │                │ (0,1) pill_bar         胶囊控制条     │
              ├────────────────┼─────────────────────────────────────┤
              │ (1,0) cover    │ (1,1) list_container   播放列表面板    │
              └────────────────┴─────────────────────────────────────┘
        """
        # 设置无边框 + 始终置顶 + 工具窗口（不在任务栏占位），构成"悬浮小组件"形态
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        # 透明背景：圆角胶囊靠子控件自身的 border-radius 实现
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 开启鼠标追踪，让 mouseMoveEvent 在未按下按键时也能收到事件（用于光标变形）
        self.setMouseTracking(True)

        # 精准对齐总宽度：110(左侧封面) + 10(网格Spacing) + 400(播放器宽度) + 10(左右Margin) = 530px
        self.setFixedWidth(530)

        # 主网格布局：2 列（封面 / 主体），上下两行（控制条 / 列表）
        self.grid_layout = QtWidgets.QGridLayout(self)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setColumnMinimumWidth(0, 110)  # 第一列留给封面
        self.grid_layout.setColumnMinimumWidth(1, 400)  # 第二列留给控制栏和列表

        # 1. 顶部胶囊控制条
        self.pill_bar = QtWidgets.QWidget()
        self.pill_bar.setObjectName("PillBar")
        # 半透明深色 + 细边框 + 大圆角，营造"胶囊"质感
        self.pill_bar.setStyleSheet("""
            QWidget#PillBar {
                background-color: rgba(18, 25, 38, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 18px;
            }
        """)

        # 给胶囊条加一层柔和的投影，提升悬浮感
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QtGui.QColor(0, 0, 0, 130))
        shadow.setOffset(0, 3)
        self.pill_bar.setGraphicsEffect(shadow)

        # 布局整体间距设置为 12px，让呼吸感更加均匀、开阔
        self.pill_layout = QtWidgets.QHBoxLayout(self.pill_bar)
        self.pill_layout.setContentsMargins(12, 4, 12, 4)
        self.pill_layout.setSpacing(12)

        # 列表面板开关按钮，最左侧入口
        self.btn_list = self.create_img_btn("列表.png", self.toggle_playlist_panel)
        self.pill_layout.addWidget(self.btn_list)

        # 标题 + 频谱 的纵向小布局：上方歌名滚动，下方频谱条
        title_spec_layout = QtWidgets.QVBoxLayout()
        title_spec_layout.setSpacing(1)

        # 歌名采用跑马灯标签，超长会自动滚动
        self.lbl_title = MarqueeLabel("未在播放")
        self.lbl_title.setFont(QtGui.QFont(FONT_FAMILY, 10, QtGui.QFont.Weight.Bold))
        # 优化歌名展示区宽度为 140px，配合下面的弹性 Stretch，给中间空出完美的空白地带，绝不再重叠
        self.lbl_title.setFixedWidth(140)
        self.spectrum = SpectrumWidget()

        title_spec_layout.addWidget(self.lbl_title)
        title_spec_layout.addWidget(self.spectrum)
        self.pill_layout.addLayout(title_spec_layout)

        # 核心：黄金弹性区，会自动吃掉所有多余宽度，将歌名和按键极致优雅地隔开
        self.pill_layout.addStretch()

        # 右侧一组功能按钮：上一首 / 播放暂停 / 下一首 / 播放模式 / 全局收藏过滤
        self.btn_prev = self.create_img_btn("上一首.png", self.prev_song)
        self.btn_play = self.create_img_btn("继续.png", self.toggle_play)
        self.btn_next = self.create_img_btn("下一首.png", self.next_song)
        self.btn_mode = self.create_img_btn("列表循环.png", self.toggle_play_mode)
        self.btn_global_like = self.create_img_btn("爱心.png", self.toggle_global_liked_filter)

        # 依次按顺序、等间距(12px)挂载，彻底摆脱上一版不对称挤压问题
        self.pill_layout.addWidget(self.btn_prev)
        self.pill_layout.addWidget(self.btn_play)
        self.pill_layout.addWidget(self.btn_next)
        self.pill_layout.addWidget(self.btn_mode)
        self.pill_layout.addWidget(self.btn_global_like)

        # 挂载控制条到网格 (0,1)
        self.grid_layout.addWidget(self.pill_bar, 0, 1)

        # 2. 突出封面（左侧 110x110 方块，缩放图片显示）
        self.lbl_cover = QtWidgets.QLabel()
        self.lbl_cover.setFixedSize(110, 110)
        self.lbl_cover.setStyleSheet("background-color: #1a1c24; border: none;")
        # 让 setPixmap 的图片自动按 QLabel 大小缩放
        self.lbl_cover.setScaledContents(True)
        # 启动时给一张占位图（写有 "OST" 字样的纯色块）
        self.set_placeholder_cover()
        self.grid_layout.addWidget(self.lbl_cover, 1, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        # 3. 列表窗口（四周全圆角，浑然一体）
        self.list_container = QtWidgets.QWidget()
        self.list_container.setObjectName("ListContainer")
        self.list_container.setFixedHeight(110)
        self.list_container.setStyleSheet("""
            QWidget#ListContainer {
                background-color: rgba(15, 20, 30, 0.7); 
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }
        """)

        # 列表容器的阴影：略偏右下方向，强化"卡片"感
        container_shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        container_shadow.setBlurRadius(12)
        container_shadow.setColor(QtGui.QColor(0, 0, 0, 150))
        container_shadow.setOffset(2, 3)
        self.list_container.setGraphicsEffect(container_shadow)

        # 容器内部用纵向布局填入真正的 QListWidget
        container_layout = QtWidgets.QVBoxLayout(self.list_container)
        container_layout.setContentsMargins(6, 6, 6, 6)

        # 真正承载歌曲列表的 QListWidget
        self.list_widget = QtWidgets.QListWidget()
        # 大段 QSS 样式：透明背景 + 暗色分割线 + 自定义瘦长滚动条
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                background: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
                padding: 3px 0px;
            }
            
            QScrollBar:vertical {
                border: none;
                background: rgba(255, 255, 255, 0.03);
                width: 5px;
                margin: 2px 0px 2px 0px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 12px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 0, 127, 0.6);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        # 点击列表项 -> 切换到对应歌曲
        self.list_widget.itemClicked.connect(self.on_list_item_clicked)
        container_layout.addWidget(self.list_widget)

        # 列表容器挂载到网格 (1,1)
        self.grid_layout.addWidget(self.list_container, 1, 1)

        # 默认折叠：隐藏封面与列表，呈现极简的胶囊条
        self.lbl_cover.hide()
        self.list_container.hide()

        # 把扫描到的歌曲渲染进列表
        self.refresh_list_ui()

    def create_img_btn(self, img_name, callback):
        """创建一个 22x22 的透明背景图片按钮。

        - 优先加载磁盘上的图标文件（兼容打包路径）；
        - 找不到图标文件时，退化为显示文件名前两个字的文本按钮，避免空白；
        - 自动绑定 click 回调。
        """
        btn = QtWidgets.QPushButton()
        btn.setFixedSize(22, 22)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("background: transparent; border: none;")
        # 兼容 PyInstaller 打包与本地开发环境的图片路径寻找
        img_path = resource_path(img_name)
        if os.path.exists(img_path):
            btn.setIcon(QtGui.QIcon(img_path))
            btn.setIconSize(QtCore.QSize(18, 18))
        else:
            # 资源缺失时的兜底：显示文字，方便排查"图标怎么没了"的问题
            btn.setText(img_name.split('.')[0][:2])
            btn.setStyleSheet("color: white; font-size: 10px;")
        btn.clicked.connect(callback)
        return btn

    def set_btn_icon(self, btn, icon_name):
        """运行时切换按钮图标（例如播放/暂停状态切换）。资源缺失同样退化文字。"""
        img_path = resource_path(icon_name)
        if os.path.exists(img_path):
            btn.setIcon(QtGui.QIcon(img_path))
        else:
            btn.setText(icon_name.split('.')[0][:2])

    def set_placeholder_cover(self):
        """生成一张 110x110 的占位封面（深色背景 + 粉色 'OST' 字样）。"""
        pixmap = QtGui.QPixmap(110, 110)
        pixmap.fill(QtGui.QColor("#1a1c24"))
        # 用 QPainter 在 pixmap 上画一个居中的 OST 字样，作为视觉占位
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#ff007f"))
        font = QtGui.QFont(FONT_FAMILY, 16, QtGui.QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "OST")
        painter.end()
        self.lbl_cover.setPixmap(pixmap)

    # --- 右键功能菜单实现 ---
    def contextMenuEvent(self, event):
        """右键弹出美化菜单：锁定位置、调整多阶缩放比例、安全退出"""
        # 创建一个 QMenu，直接在 self 上下文中弹出
        menu = QtWidgets.QMenu(self)
        # QMenu 整体样式：深色半透明背景 + 粉色 hover 高亮 + 圆角分隔线
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(18, 25, 38, 0.95);
                border: 1px solid rgba(255, 0, 127, 0.4);
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #dddddd;
                font-family: 'Microsoft YaHei';
                font-size: 11px;
                padding: 6px 20px 6px 20px;
                background-color: transparent;
            }
            QMenu::item:selected {
                background-color: rgba(255, 0, 127, 0.2);
                color: #ff007f;
                border-radius: 4px;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.1);
                margin: 4px 10px;
            }
        """)

        # 锁定位置（点击会反转 position_locked，文本相应改变）
        lock_text = "解锁位置" if self.position_locked else "锁定位置"
        lock_action = menu.addAction(lock_text)
        lock_action.triggered.connect(self.toggle_position_lock)

        # 调整缩放（扩充：0.5、0.8、1.0、1.2、1.5、2.0）
        scale_menu = menu.addMenu("调整缩放")
        # 子菜单复用同一份 QSS，保持视觉一致
        scale_menu.setStyleSheet(menu.styleSheet())

        # 缩放档位：(展示文案, 真实倍率)
        scales = [
            ("0.5x (迷你)", 0.5),
            ("0.8x", 0.8),
            ("1.0x (默认)", 1.0),
            ("1.2x", 1.2),
            ("1.5x", 1.5),
            ("2.0x (双倍)", 2.0)
        ]
        for label, val in scales:
            act = scale_menu.addAction(label)
            # 通过绑定 val 默认参数解决 late binding 闭包问题，确保点击每一项都调用对应的比例
            act.triggered.connect(lambda checked=False, v=val: self.apply_scale(v))

        menu.addSeparator()

        # 退出菜单项 -> 走完整的资源清理流程
        exit_action = menu.addAction("退出")
        exit_action.triggered.connect(self.exit_application)

        # 完美兼容 PyQt6 的 event.globalPos()
        # 在鼠标点击的全局坐标处弹出菜单
        menu.exec(event.globalPos())

    def toggle_position_lock(self):
        """切换"位置锁定"开关；锁定后窗口仍可拉伸高度但不能拖动整体位置。"""
        self.position_locked = not self.position_locked

    def apply_scale(self, factor):
        """缩放算法：对整个窗口核心布局、按钮、滚动条、行高及字体等进行比例缩放"""
        # 把缩放因子记录下来，refresh_list_ui 等函数会读取它来同步缩放子项
        self.scale_factor = factor
        # 整个窗口宽度按比例放大，所有内部布局靠下面的同比例换算跟上
        scaled_width = int(530 * factor)
        self.setFixedWidth(scaled_width)

        # 1. 缩放全局布局间距
        self.grid_layout.setSpacing(int(10 * factor))
        self.grid_layout.setContentsMargins(
            int(5 * factor), int(5 * factor), int(5 * factor), int(5 * factor)
        )
        self.pill_layout.setContentsMargins(
            int(12 * factor), int(4 * factor), int(12 * factor), int(4 * factor)
        )
        self.pill_layout.setSpacing(int(12 * factor))

        # 2. 调整网格布局列宽
        self.grid_layout.setColumnMinimumWidth(0, int(110 * factor))
        self.grid_layout.setColumnMinimumWidth(1, int(400 * factor))

        # 3. 调整封面和列表宽高限制
        self.lbl_cover.setFixedSize(int(110 * factor), int(110 * factor))
        self.lbl_title.setFixedWidth(int(140 * factor))
        # 字号也乘以缩放因子，做到"真·物理放大"，保持比例
        self.lbl_title.setFont(QtGui.QFont(FONT_FAMILY, int(10 * factor), QtGui.QFont.Weight.Bold))

        # 4. 频谱尺寸缩放与参数同步
        self.spectrum.setFixedWidth(int(80 * factor))
        self.spectrum.setFixedHeight(int(12 * factor))
        self.spectrum.scale_factor = factor  # 将比例传入频谱组件

        # 5. 精确动态调节所有小控制按钮的尺寸与 Icon 大小
        for btn in [self.btn_list, self.btn_prev, self.btn_play, self.btn_next, self.btn_mode, self.btn_global_like]:
            btn.setFixedSize(int(22 * factor), int(22 * factor))
            if not btn.icon().isNull():
                btn.setIconSize(QtCore.QSize(int(18 * factor), int(18 * factor)))

        # 6. 等比微调列表中现代化滚动条和项边距的样式 QSS
        # 先确保滚动条不会缩到 0 像素（minimum 3）
        scrollbar_width = max(3, int(5 * factor))
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
            }}
            QListWidget::item {{
                background: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
                padding: {int(3 * factor)}px 0px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: rgba(255, 255, 255, 0.03);
                width: {scrollbar_width}px;
                margin: 2px 0px 2px 0px;
                border-radius: {max(1, int(2 * factor))}px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 255, 255, 0.15);
                min-height: {int(12 * factor)}px;
                border-radius: {max(1, int(2 * factor))}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(255, 0, 127, 0.6);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        # 7. 重绘列表内各个控件与行距，实现完全缩放
        # refresh_list_ui 内部会读取 self.scale_factor 来重建每一行的高度/字号/小图标
        self.refresh_list_ui()

        # 8. 刷新窗口高度边界
        # 折叠态：只看胶囊条 + 一个上下边距
        # 展开态：胶囊条 + 列表容器（110px 高度等比放大）+ 缝隙
        if self.list_container.isHidden():
            self.setFixedHeight(self.pill_bar.sizeHint().height() + int(15 * factor))
        else:
            self.list_container.setFixedHeight(int(110 * factor))
            self.setFixedHeight(self.pill_bar.sizeHint().height() + int(110 * factor) + int(25 * factor))

        # 让 QWidget 重新基于新尺寸自适应一次
        self.adjustSize()

    # --- 交互槽函数 ---
    def toggle_playlist_panel(self):
        """点击列表按钮：在"折叠胶囊条"与"展开封面+列表"两种形态间切换。"""
        if self.list_container.isHidden():
            self.lbl_cover.show()
            self.list_container.show()
        else:
            self.lbl_cover.hide()
            self.list_container.hide()
        self.adjustSize()

    def on_list_item_clicked(self, item):
        """QListWidget 行被点击：根据行号定位到 play_queue，并播放对应曲目。"""
        row = self.list_widget.row(item)
        self.play_song_at_index(row)

    def toggle_play(self):
        """中央播放按钮：根据当前状态执行播放/暂停/恢复。"""
        # 队列为空时无意义
        if not self.play_queue:
            return

        # 程序刚启动尚未选定歌曲：直接播放队列首曲
        if not self.current_song:
            self.play_song_at_index(0)
            return

        # 已经在播放 -> 暂停
        if pygame.mixer.music.get_busy() and not self.is_paused:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.set_btn_icon(self.btn_play, "继续.png")
            self.spectrum.set_playing(False)
        else:
            # 暂停状态 -> 恢复播放
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.set_btn_icon(self.btn_play, "暂停.png")
            self.spectrum.set_playing(True)
        # 状态变化后刷新列表（活动行的边框/字色会跟着变）
        self.refresh_list_ui()

    def play_song_at_index(self, index):
        """加载并播放队列指定位置的歌曲，同时更新封面、频谱、按钮等所有视觉。"""
        # 边界检查：空队列或越界都直接返回，不要让 pygame 抛错
        if not self.play_queue or index < 0 or index >= len(self.play_queue):
            return

        song = self.play_queue[index]
        self.current_song = song
        # 新歌默认是"非暂停"
        self.is_paused = False

        try:
            # 启动新歌前，先终止上一首尚未结束的 RMS 计算线程，节省 CPU
            if hasattr(self, "rms_thread") and self.rms_thread.isRunning():
                self.rms_thread.terminate()

            # 装载并立即开始播放
            pygame.mixer.music.load(song["path"])
            pygame.mixer.music.play()

            # 同步标题、按钮图标、频谱状态
            self.lbl_title.setText(song["name"])
            self.set_btn_icon(self.btn_play, "暂停.png")
            self.spectrum.set_playing(True)

            # 把当前曲目时长写入频谱组件，并清空旧的包络数据
            duration_ms = self.get_song_duration_ms(song["path"])
            self.spectrum.set_duration_ms(duration_ms)
            self.spectrum.set_envelope([])

            # 启动后台线程异步计算新曲的 RMS 包络
            self.rms_thread = RMSCalculator(song["path"])
            self.rms_thread.result_ready.connect(self.spectrum.set_envelope)
            self.rms_thread.start()

            # ---------- 封面加载策略 ----------
            # 优先使用磁盘上"同名图片"作为封面；
            # 否则尝试读取音频内嵌封面；
            # 都没有就回退到占位图。
            cover_loaded = False
            if song["cover"] and os.path.exists(song["cover"]):
                self.lbl_cover.setPixmap(QtGui.QPixmap(song["cover"]))
                cover_loaded = True
            else:
                embedded_data = self.get_embedded_cover(song["path"])
                if embedded_data:
                    pixmap = QtGui.QPixmap()
                    if pixmap.loadFromData(embedded_data):
                        self.lbl_cover.setPixmap(pixmap)
                        cover_loaded = True

            if not cover_loaded:
                self.set_placeholder_cover()

            # 列表 UI 也要刷新一次，让活动行高亮指向新歌
            self.refresh_list_ui()
        except Exception as e:
            # 任何加载/播放异常都不会让程序崩溃，仅在控制台输出
            print(f"播放失败: {e}")

    def prev_song(self):
        """上一首：随机模式下随机跳；其他模式按队列倒着走，并循环到末尾。"""
        if not self.play_queue:
            return

        current_idx = self.get_current_queue_index()
        if self.play_mode == 2:
            # 随机播放：忽略当前位置，直接抽一首
            next_idx = random.randint(0, len(self.play_queue) - 1)
        else:
            # 顺序/单曲模式下，"上一首"统一按 -1 推进；首次播放则从 0 开始
            next_idx = (current_idx - 1) % len(self.play_queue) if current_idx != -1 else 0
        self.play_song_at_index(next_idx)

    def next_song(self):
        """下一首：与 prev_song 对称，随机模式随机跳，其他模式 +1 循环。"""
        if not self.play_queue:
            return

        current_idx = self.get_current_queue_index()
        if self.play_mode == 2:
            next_idx = random.randint(0, len(self.play_queue) - 1)
        else:
            next_idx = (current_idx + 1) % len(self.play_queue) if current_idx != -1 else 0
        self.play_song_at_index(next_idx)

    def toggle_play_mode(self):
        """循环切换三种播放模式，并刷新模式按钮图标。"""
        self.play_mode = (self.play_mode + 1) % 3
        if self.play_mode == 0:
            self.set_btn_icon(self.btn_mode, "列表循环.png")
        elif self.play_mode == 1:
            self.set_btn_icon(self.btn_mode, "单曲循环.png")
        else:
            self.set_btn_icon(self.btn_mode, "随机播放.png")

    def toggle_global_liked_filter(self):
        """切换"只看我喜欢"过滤器：影响 play_queue 与列表 UI。"""
        self.global_liked_filter = not self.global_liked_filter

        # 用爱心实心/空心两种图标传达开关状态
        icon_name = "爱心（填充）.png" if self.global_liked_filter else "爱心.png"
        self.set_btn_icon(self.btn_global_like, icon_name)

        self.update_play_queue()
        self.refresh_list_ui()

    def toggle_song_liked(self, song):
        """切换某首歌的收藏状态，并立即持久化到 favorites.json。"""
        song["liked"] = not song["liked"]

        if song["liked"]:
            self.favorites.add(song["name"])
        else:
            self.favorites.discard(song["name"])

        # 立即落盘，避免突然关程序丢数据
        self.save_favorites()

        # 如果当前正处于"仅收藏"模式，取消收藏后队列要相应缩短
        if self.global_liked_filter:
            self.update_play_queue()

        self.refresh_list_ui()
    def refresh_list_ui(self):
        """根据当前 play_queue 重建整个列表 UI（清空 -> 逐项重建）。

        每行包含：
          - 一个小爱心按钮（点击切换收藏）
          - 一个跑马灯歌名
          - 当前播放行额外附加一个小型频谱组件，且整行带高亮边框
        """
        self.list_widget.clear()

        for song in self.play_queue:
            # QListWidgetItem 是"占位项"，真正的视觉由 setItemWidget 设置的 widget 提供
            item = QtWidgets.QListWidgetItem()
            # 缩放单项高度
            item.setSizeHint(QtCore.QSize(0, int(28 * self.scale_factor)))

            # 每行一个独立的子 QWidget，使用水平布局排放各部件
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(widget)
            layout.setContentsMargins(4, 1, 4, 1)
            layout.setSpacing(6)

            # 收藏按钮：根据当前 liked 状态选实心/空心爱心图标
            like_icon = "爱心（填充）.png" if song["liked"] else "爱心.png"
            # 用默认参数捕获 song，避免 lambda 闭包共享变量陷阱
            btn_like = self.create_img_btn(like_icon, lambda checked=False, s=song: self.toggle_song_liked(s))
            btn_like.setFixedSize(int(14 * self.scale_factor), int(14 * self.scale_factor))
            layout.addWidget(btn_like)

            # 歌名标签：限制宽度 + 跑马灯滚动 + 缩放字号
            lbl_name = MarqueeLabel(song["name"])
            # 缩放歌名的可剪裁限制宽度
            lbl_name.setFixedWidth(int(280 * self.scale_factor))
            # 缩放字号大小
            lbl_name.setFont(QtGui.QFont(FONT_FAMILY, int(9 * self.scale_factor)))
            layout.addWidget(lbl_name)
            # 弹簧把右侧空间撑开
            layout.addStretch()

            # 判断该行是否是"当前播放行"，是的话特别加样式与小频谱
            is_active = (self.current_song is not None and song["name"] == self.current_song["name"])
            if is_active:
                # 高亮容器：粉色边框 + 半透明粉色背景
                widget.setObjectName("ActiveItem")
                widget.setStyleSheet(f"""
                    QWidget#ActiveItem {{
                        border: 1px solid rgba(255, 0, 127, 0.5);
                        border-radius: {max(1, int(4 * self.scale_factor))}px;
                        background-color: rgba(255, 0, 127, 0.1);
                    }}
                """)
                # 文字也染成主题粉，并加粗
                lbl_name.set_text_color("#ff007f")
                lbl_name.setFont(QtGui.QFont(FONT_FAMILY, int(9 * self.scale_factor), QtGui.QFont.Weight.Bold))

                # 行内迷你频谱：状态与播放器全局状态保持同步
                mini_spec = SpectrumWidget()
                mini_spec.scale_factor = self.scale_factor
                mini_spec.set_playing(pygame.mixer.music.get_busy() and not self.is_paused)
                mini_spec.setFixedWidth(int(24 * self.scale_factor))
                layout.addWidget(mini_spec)
            else:
                # 普通行：浅灰色字
                lbl_name.set_text_color("#dddddd")

            # 把组装好的 widget 注入到列表项中
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def check_playback_status(self):
        """500ms 周期检查 pygame.mixer 是否还在播放，未播且非暂停 -> 自动续/切歌。"""
        if self.current_song and not self.is_paused:
            if not pygame.mixer.music.get_busy():
                # 单曲循环：再次播放当前歌；找不到当前 idx 则直接 play() 重启
                if self.play_mode == 1:
                    current_idx = self.get_current_queue_index()
                    if current_idx != -1:
                        self.play_song_at_index(current_idx)
                    else:
                        pygame.mixer.music.play()
                else:
                    # 列表循环 / 随机播放：交给 next_song 决定下一首
                    self.next_song()

    # --- 鼠标拖拽移动 & 底部拖拽拉高窗口（支持锁定） ---
    def mousePressEvent(self, event):
        """按下鼠标：根据光标位置区分"拉伸窗口"与"拖动窗口"两种意图。"""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # 即使位置被锁定，只要列表展开，边缘依然允许鼠标上下拉伸高度
            if not self.list_container.isHidden() and event.position().y() >= self.height() - 10:
                # 鼠标位于底部 10 像素 -> 进入"resize"模式，记录起点
                self.is_resizing = True
                self.resize_start_y = event.globalPosition().y()
                self.resize_start_height = self.height()
                event.accept()
            elif not self.position_locked:  # 未锁定时，允许拖曳窗口
                # 普通区域 + 未锁定 -> 进入"drag"模式，记录鼠标到窗口左上角的偏移
                self.is_dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动：动态切换光标形状，并执行 resize / drag。"""
        # 鼠标悬停在底部边缘时变成上下拉伸光标，提示用户可拖拉
        if not self.list_container.isHidden() and event.position().y() >= self.height() - 10:
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

        if self.is_resizing:
            # 拉伸：根据 Y 轴位移改写窗口高度，同时同步列表容器的高度
            delta_y = event.globalPosition().y() - self.resize_start_y
            new_height = self.resize_start_height + delta_y
            # 高度上下限同样跟随缩放因子，防止控件挤变形
            limit_min = int(170 * self.scale_factor)
            limit_max = int(600 * self.scale_factor)
            if limit_min <= new_height <= limit_max:
                self.setFixedHeight(int(new_height))
                # 列表容器约比整体高度小 75 像素（控制条 + 缝隙）
                self.list_container.setFixedHeight(int(new_height - 75))
            event.accept()
 
        elif self.is_dragging and not self.position_locked:
            # 拖动整窗：用全局鼠标点减去之前记录的偏移得到新左上角
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """松开鼠标：清空拖拽/拉伸状态，光标恢复默认。"""
        self.is_resizing = False
        self.is_dragging = False
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        event.accept()

    # --- 安全关闭与退出资源清理，彻底打碎 CMD 残留 ---
    def closeEvent(self, event):
        """重写关闭事件：当窗口关闭时彻底停止硬件、杀死子进程/线程"""
        # 等后台 RMS 线程真正退出，避免 Qt 警告 "QThread: Destroyed while thread is still running"
        if hasattr(self, "rms_thread") and self.rms_thread.isRunning():
            self.rms_thread.terminate()
            self.rms_thread.wait()  # 阻塞等待线程物理退出
        try:
            # 停止音频播放、释放 mixer 资源
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            # 资源已被部分回收时再次调用可能抛错，这里吞掉以免影响关闭流程
            pass
        event.accept()

    def exit_application(self):
        """完整注销硬件并强制关闭退出，不给终端任何挂起机会"""
        self.close()  # 触发上面完美的 closeEvent
        QtWidgets.QApplication.quit()
        sys.exit(0)


if __name__ == "__main__":
    # 程序入口：构建 QApplication 是 PyQt 程序唯一允许在主线程运行的事件循环宿主
    app = QtWidgets.QApplication(sys.argv)

    # 优先使用打包随附的 misans.ttf 美化字体；加载成功才覆盖全局 FONT_FAMILY
    misans_path = resource_path("misans.ttf")
    if os.path.exists(misans_path):
        font_id = QtGui.QFontDatabase.addApplicationFont(misans_path)
        if font_id != -1:
            families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
            if families:
                FONT_FAMILY = families[0]

    # 设置全局默认字体；后续控件若未单独 setFont 都会继承这个字体
    app.setFont(QtGui.QFont(FONT_FAMILY))

    # 创建主窗口、显示、进入 Qt 事件循环
    player = DesktopMusicPlayer()
    player.show()
    sys.exit(app.exec())