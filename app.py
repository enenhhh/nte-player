import os
# 彻底静默 pygame 启动时的终端提示信息
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

import sys
import json
import random
import math
from PyQt6 import QtWidgets, QtCore, QtGui
import pygame

# 尝试导入高级库，如果未安装则降级
try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC
    from mutagen.flac import FLAC
except ImportError:
    mutagen = None

try:
    import numpy as np
    from pydub import AudioSegment
except ImportError:
    np = None
    AudioSegment = None

# 初始化音频播放器
pygame.mixer.init()

# 全局字体变量，默认为微软雅黑
FONT_FAMILY = "Microsoft YaHei"


def resource_path(relative_path):
    """获取打包后资源的绝对路径，兼容开发环境与 PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class OutlinedLabel(QtWidgets.QLabel):
    """自定义带黑色描边的标签"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.outline_color = QtGui.QColor(0, 0, 0, 240)
        self.text_color = QtGui.QColor(255, 255, 255)
        self.setMinimumHeight(24)

    def set_text_color(self, color_str):
        self.text_color = QtGui.QColor(color_str)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        
        rect = self.rect()
        font = self.font()
        painter.setFont(font)
        align = self.alignment()
        
        painter.setPen(self.outline_color)
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for dx, dy in offsets:
            painter.drawText(rect.translated(dx, dy), align, self.text())
            
        painter.setPen(self.text_color)
        painter.drawText(rect, align, self.text())


class MarqueeLabel(OutlinedLabel):
    """超长文本自动循环滚动标签"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.scroll_pos = 0
        self._full_text = text
        self.scroll_timer = QtCore.QTimer(self)
        self.scroll_timer.timeout.connect(self.scroll_text)
        self.scroll_timer.start(250)

    def setText(self, text):
        self._full_text = text
        self.scroll_pos = 0
        super().setText(text)

    def scroll_text(self):
        if not self._full_text:
            return
        
        metrics = QtGui.QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._full_text)
        
        if text_width <= self.width() or self.width() <= 10:
            self.scroll_pos = 0
            super().setText(self._full_text)
            return

        display_text = self._full_text + "      "
        self.scroll_pos = (self.scroll_pos + 1) % len(display_text)
        rotated_text = display_text[self.scroll_pos:] + display_text[:self.scroll_pos]
        super().setText(rotated_text)


class RMSCalculator(QtCore.QThread):
    """后台异步计算歌曲真实音量包络线，避免阻塞 UI"""
    result_ready = QtCore.pyqtSignal(list)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        if not AudioSegment or not np:
            self.result_ready.emit([])
            return
        try:
            sound = AudioSegment.from_file(self.file_path)
            sound = sound.set_channels(1)
            samples = np.array(sound.get_array_of_samples())
            
            points = 200
            chunk_size = len(samples) // points
            if chunk_size == 0:
                chunk_size = 1
                
            envelope = []
            for i in range(0, len(samples), chunk_size):
                chunk = samples[i:i+chunk_size]
                if len(chunk) > 0:
                    rms = np.sqrt(np.mean(chunk**2))
                    envelope.append(float(rms))
                else:
                    envelope.append(0.0)
            
            max_rms = max(envelope) if envelope else 1.0
            if max_rms == 0:
                max_rms = 1.0
            normalized = [r / max_rms for r in envelope]
            self.result_ready.emit(normalized)
        except Exception:
            self.result_ready.emit([])


class SpectrumWidget(QtWidgets.QWidget):
    """流体频谱组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_playing = False
        self.phase = 0.0
        self.envelope = []
        self.duration_ms = 0
        self.scale_factor = 1.0  # 缩放因子
        
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_spectrum)
        self.timer.start(50)
        self.setFixedHeight(12)
        self.setFixedWidth(80)

    def set_playing(self, playing):
        self.is_playing = playing

    def set_duration_ms(self, duration_ms):
        self.duration_ms = duration_ms

    def set_envelope(self, envelope):
        self.envelope = envelope

    def update_spectrum(self):
        if self.is_playing:
            self.phase += 0.25
            self.update()
        else:
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#d4df31"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        
        width = self.width()
        height = self.height()
        # 频谱条的粗细和间隔也参与等比缩放
        bar_width = max(1, int(2 * self.scale_factor))
        spacing = max(1, int(1 * self.scale_factor))
        num_bars = int(width / (bar_width + spacing))
        
        volume_factor = 1.0
        if self.is_playing and self.envelope and self.duration_ms > 0:
            current_ms = pygame.mixer.music.get_pos()
            idx = int((current_ms / self.duration_ms) * len(self.envelope))
            idx = min(max(idx, 0), len(self.envelope) - 1)
            volume_factor = self.envelope[idx]
            
        for i in range(num_bars):
            if self.is_playing:
                h1 = math.sin(self.phase + i * 0.4) * 4.0
                h2 = math.cos(self.phase * 0.7 - i * 0.25) * 3.0
                bar_height = int((abs(h1 + h2) + 2) * volume_factor)
                bar_height = min(max(bar_height, 2), height)
            else:
                bar_height = 2
            painter.drawRect(i * (bar_width + spacing), height - bar_height, bar_width, bar_height)


class DesktopMusicPlayer(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.music_dir = "Music"
        self.favorites_file = "favorites.json"
        
        if not os.path.exists(self.music_dir):
            os.makedirs(self.music_dir)
            
        # 核心状态控制
        self.current_song = None
        self.is_paused = False
        self.play_queue = []
        self.play_mode = 0  # 0: 列表循环, 1: 单曲循环, 2: 随机播放
        self.global_liked_filter = False
        self.songs = []
        self.favorites = set()
        
        self.is_resizing = False
        self.is_dragging = False
        self.resize_start_y = 0
        self.resize_start_height = 0
        self.position_locked = False  # 是否锁定位置
        self.scale_factor = 1.0        # 缩放系数
        
        self.load_favorites()
        self.scan_music_folder()
        self.init_ui()
        
        # 自动切换歌曲轮询
        self.track_timer = QtCore.QTimer(self)
        self.track_timer.timeout.connect(self.check_playback_status)
        self.track_timer.start(500)

    def load_favorites(self):
        if os.path.exists(self.favorites_file):
            try:
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    self.favorites = set(json.load(f))
            except Exception:
                self.favorites = set()

    def save_favorites(self):
        with open(self.favorites_file, 'w', encoding='utf-8') as f:
            json.dump(list(self.favorites), f, ensure_ascii=False, indent=4)

    def scan_music_folder(self):
        self.songs = []
        if not os.path.exists(self.music_dir):
            return
        
        supported_exts = ('.mp3', '.wav', '.ogg', '.flac')
        files = os.listdir(self.music_dir)
        for file in files:
            if file.lower().endswith(supported_exts):
                name, _ = os.path.splitext(file)
                path = os.path.join(self.music_dir, file)
                
                cover_path = ""
                for img_ext in ('.png', '.jpg', '.jpeg'):
                    temp_img = os.path.join(self.music_dir, name + img_ext)
                    if os.path.exists(temp_img):
                        cover_path = temp_img
                        break
                
                liked = name in self.favorites
                self.songs.append({
                    "name": name,
                    "path": path,
                    "cover": cover_path,
                    "liked": liked
                })
        
        self.update_play_queue()

    def update_play_queue(self):
        if self.global_liked_filter:
            self.play_queue = [s for s in self.songs if s["liked"]]
        else:
            self.play_queue = self.songs.copy()

    def get_current_queue_index(self):
        if not self.current_song:
            return -1
        for idx, s in enumerate(self.play_queue):
            if s["name"] == self.current_song["name"]:
                return idx
        return -1

    def get_embedded_cover(self, file_path):
        if not mutagen:
            return None
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                audio = MP3(file_path, ID3=ID3)
                if audio.tags:
                    for tag in audio.tags.values():
                        if isinstance(tag, APIC):
                            return tag.data
            elif ext == ".flac":
                audio = FLAC(file_path)
                if audio.pictures:
                    return audio.pictures[0].data
        except Exception:
            pass
        return None

    def get_song_duration_ms(self, file_path):
        if not mutagen:
            return 0
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                audio = MP3(file_path)
                return int(audio.info.length * 1000)
            elif ext == ".flac":
                audio = FLAC(file_path)
                return int(audio.info.length * 1000)
        except Exception:
            pass
        return 0

    # --- UI 初始化 ---
    def init_ui(self):
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint | 
            QtCore.Qt.WindowType.WindowStaysOnTopHint | 
            QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        
        # 精准对齐总宽度：110(左侧封面) + 10(网格Spacing) + 400(播放器宽度) + 10(左右Margin) = 530px
        self.setFixedWidth(530)

        self.grid_layout = QtWidgets.QGridLayout(self)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setColumnMinimumWidth(0, 110)  # 第一列留给封面
        self.grid_layout.setColumnMinimumWidth(1, 400)  # 第二列留给控制栏和列表

        # 1. 顶部胶囊控制条
        self.pill_bar = QtWidgets.QWidget()
        self.pill_bar.setObjectName("PillBar")
        self.pill_bar.setStyleSheet("""
            QWidget#PillBar {
                background-color: rgba(18, 25, 38, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 18px;
            }
        """)
        
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QtGui.QColor(0, 0, 0, 130))
        shadow.setOffset(0, 3)
        self.pill_bar.setGraphicsEffect(shadow)

        # 布局整体间距设置为 12px，让呼吸感更加均匀、开阔
        self.pill_layout = QtWidgets.QHBoxLayout(self.pill_bar)
        self.pill_layout.setContentsMargins(12, 4, 12, 4)
        self.pill_layout.setSpacing(12)

        self.btn_list = self.create_img_btn("列表.png", self.toggle_playlist_panel)
        self.pill_layout.addWidget(self.btn_list)

        title_spec_layout = QtWidgets.QVBoxLayout()
        title_spec_layout.setSpacing(1)
        
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

        # 挂载控制条
        self.grid_layout.addWidget(self.pill_bar, 0, 1)

        # 2. 突出封面
        self.lbl_cover = QtWidgets.QLabel()
        self.lbl_cover.setFixedSize(110, 110)
        self.lbl_cover.setStyleSheet("background-color: #1a1c24; border: none;")
        self.lbl_cover.setScaledContents(True)
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
        
        container_shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        container_shadow.setBlurRadius(12)
        container_shadow.setColor(QtGui.QColor(0, 0, 0, 150))
        container_shadow.setOffset(2, 3)
        self.list_container.setGraphicsEffect(container_shadow)

        container_layout = QtWidgets.QVBoxLayout(self.list_container)
        container_layout.setContentsMargins(6, 6, 6, 6)

        self.list_widget = QtWidgets.QListWidget()
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
        self.list_widget.itemClicked.connect(self.on_list_item_clicked)
        container_layout.addWidget(self.list_widget)
        
        self.grid_layout.addWidget(self.list_container, 1, 1)

        self.lbl_cover.hide()
        self.list_container.hide()

        self.refresh_list_ui()

    def create_img_btn(self, img_name, callback):
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
            btn.setText(img_name.split('.')[0][:2])
            btn.setStyleSheet("color: white; font-size: 10px;")
        btn.clicked.connect(callback)
        return btn

    def set_btn_icon(self, btn, icon_name):
        img_path = resource_path(icon_name)
        if os.path.exists(img_path):
            btn.setIcon(QtGui.QIcon(img_path))
        else:
            btn.setText(icon_name.split('.')[0][:2])

    def set_placeholder_cover(self):
        pixmap = QtGui.QPixmap(110, 110)
        pixmap.fill(QtGui.QColor("#1a1c24"))
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
        menu = QtWidgets.QMenu(self)
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

        # 锁定位置
        lock_text = "解锁位置" if self.position_locked else "锁定位置"
        lock_action = menu.addAction(lock_text)
        lock_action.triggered.connect(self.toggle_position_lock)

        # 调整缩放（扩充：0.5、0.8、1.0、1.2、1.5、2.0）
        scale_menu = menu.addMenu("调整缩放")
        scale_menu.setStyleSheet(menu.styleSheet())
        
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

        # 退出
        exit_action = menu.addAction("退出")
        exit_action.triggered.connect(self.exit_application)

        # 完美兼容 PyQt6 的 event.globalPos()
        menu.exec(event.globalPos())

    def toggle_position_lock(self):
        self.position_locked = not self.position_locked

    def apply_scale(self, factor):
        """缩放算法：对整个窗口核心布局、按钮、滚动条、行高及字体等进行比例缩放"""
        self.scale_factor = factor
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
        self.refresh_list_ui()

        # 8. 刷新窗口高度边界
        if self.list_container.isHidden():
            self.setFixedHeight(self.pill_bar.sizeHint().height() + int(15 * factor))
        else:
            self.list_container.setFixedHeight(int(110 * factor))
            self.setFixedHeight(self.pill_bar.sizeHint().height() + int(110 * factor) + int(25 * factor))
            
        self.adjustSize()

    # --- 交互槽函数 ---
    def toggle_playlist_panel(self):
        if self.list_container.isHidden():
            self.lbl_cover.show()
            self.list_container.show()
        else:
            self.lbl_cover.hide()
            self.list_container.hide()
        self.adjustSize()

    def on_list_item_clicked(self, item):
        row = self.list_widget.row(item)
        self.play_song_at_index(row)

    def toggle_play(self):
        if not self.play_queue:
            return
        
        if not self.current_song:
            self.play_song_at_index(0)
            return

        if pygame.mixer.music.get_busy() and not self.is_paused:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.set_btn_icon(self.btn_play, "继续.png")
            self.spectrum.set_playing(False)
        else:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.set_btn_icon(self.btn_play, "暂停.png")
            self.spectrum.set_playing(True)
        self.refresh_list_ui()

    def play_song_at_index(self, index):
        if not self.play_queue or index < 0 or index >= len(self.play_queue):
            return
        
        song = self.play_queue[index]
        self.current_song = song
        self.is_paused = False
        
        try:
            if hasattr(self, "rms_thread") and self.rms_thread.isRunning():
                self.rms_thread.terminate()

            pygame.mixer.music.load(song["path"])
            pygame.mixer.music.play()
            
            self.lbl_title.setText(song["name"])
            self.set_btn_icon(self.btn_play, "暂停.png")
            self.spectrum.set_playing(True)
            
            duration_ms = self.get_song_duration_ms(song["path"])
            self.spectrum.set_duration_ms(duration_ms)
            self.spectrum.set_envelope([])
            
            self.rms_thread = RMSCalculator(song["path"])
            self.rms_thread.result_ready.connect(self.spectrum.set_envelope)
            self.rms_thread.start()

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
            
            self.refresh_list_ui()
        except Exception as e:
            print(f"播放失败: {e}")

    def prev_song(self):
        if not self.play_queue:
            return
        
        current_idx = self.get_current_queue_index()
        if self.play_mode == 2:
            next_idx = random.randint(0, len(self.play_queue) - 1)
        else:
            next_idx = (current_idx - 1) % len(self.play_queue) if current_idx != -1 else 0
        self.play_song_at_index(next_idx)

    def next_song(self):
        if not self.play_queue:
            return
        
        current_idx = self.get_current_queue_index()
        if self.play_mode == 2:
            next_idx = random.randint(0, len(self.play_queue) - 1)
        else:
            next_idx = (current_idx + 1) % len(self.play_queue) if current_idx != -1 else 0
        self.play_song_at_index(next_idx)

    def toggle_play_mode(self):
        self.play_mode = (self.play_mode + 1) % 3
        if self.play_mode == 0:
            self.set_btn_icon(self.btn_mode, "列表循环.png")
        elif self.play_mode == 1:
            self.set_btn_icon(self.btn_mode, "单曲循环.png")
        else:
            self.set_btn_icon(self.btn_mode, "随机播放.png")

    def toggle_global_liked_filter(self):
        self.global_liked_filter = not self.global_liked_filter
        
        icon_name = "爱心（填充）.png" if self.global_liked_filter else "爱心.png"
        self.set_btn_icon(self.btn_global_like, icon_name)
        
        self.update_play_queue()
        self.refresh_list_ui()

    def toggle_song_liked(self, song):
        song["liked"] = not song["liked"]
        
        if song["liked"]:
            self.favorites.add(song["name"])
        else:
            self.favorites.discard(song["name"])
            
        self.save_favorites()
        
        if self.global_liked_filter:
            self.update_play_queue()
                
        self.refresh_list_ui()

    def refresh_list_ui(self):
        self.list_widget.clear()
        
        for song in self.play_queue:
            item = QtWidgets.QListWidgetItem()
            # 缩放单项高度
            item.setSizeHint(QtCore.QSize(0, int(28 * self.scale_factor)))
            
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(widget)
            layout.setContentsMargins(4, 1, 4, 1)
            layout.setSpacing(6)
            
            like_icon = "爱心（填充）.png" if song["liked"] else "爱心.png"
            btn_like = self.create_img_btn(like_icon, lambda checked=False, s=song: self.toggle_song_liked(s))
            btn_like.setFixedSize(int(14 * self.scale_factor), int(14 * self.scale_factor))
            layout.addWidget(btn_like)
            
            lbl_name = MarqueeLabel(song["name"])
            # 缩放歌名的可剪裁限制宽度
            lbl_name.setFixedWidth(int(280 * self.scale_factor))
            # 缩放字号大小
            lbl_name.setFont(QtGui.QFont(FONT_FAMILY, int(9 * self.scale_factor)))
            layout.addWidget(lbl_name)
            layout.addStretch()
            
            is_active = (self.current_song is not None and song["name"] == self.current_song["name"])
            if is_active:
                widget.setObjectName("ActiveItem")
                widget.setStyleSheet(f"""
                    QWidget#ActiveItem {{
                        border: 1px solid rgba(255, 0, 127, 0.5);
                        border-radius: {max(1, int(4 * self.scale_factor))}px;
                        background-color: rgba(255, 0, 127, 0.1);
                    }}
                """)
                lbl_name.set_text_color("#ff007f")
                lbl_name.setFont(QtGui.QFont(FONT_FAMILY, int(9 * self.scale_factor), QtGui.QFont.Weight.Bold))
                
                mini_spec = SpectrumWidget()
                mini_spec.scale_factor = self.scale_factor
                mini_spec.set_playing(pygame.mixer.music.get_busy() and not self.is_paused)
                mini_spec.setFixedWidth(int(24 * self.scale_factor))
                layout.addWidget(mini_spec)
            else:
                lbl_name.set_text_color("#dddddd")
                
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def check_playback_status(self):
        if self.current_song and not self.is_paused:
            if not pygame.mixer.music.get_busy():
                if self.play_mode == 1:
                    current_idx = self.get_current_queue_index()
                    if current_idx != -1:
                        self.play_song_at_index(current_idx)
                    else:
                        pygame.mixer.music.play()
                else:
                    self.next_song()

    # --- 鼠标拖拽移动 & 底部拖拽拉高窗口（支持锁定） ---
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # 即使位置被锁定，只要列表展开，边缘依然允许鼠标上下拉伸高度
            if not self.list_container.isHidden() and event.position().y() >= self.height() - 10:
                self.is_resizing = True
                self.resize_start_y = event.globalPosition().y()
                self.resize_start_height = self.height()
                event.accept()
            elif not self.position_locked:  # 未锁定时，允许拖曳窗口
                self.is_dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if not self.list_container.isHidden() and event.position().y() >= self.height() - 10:
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

        if self.is_resizing:
            delta_y = event.globalPosition().y() - self.resize_start_y
            new_height = self.resize_start_height + delta_y
            limit_min = int(170 * self.scale_factor)
            limit_max = int(600 * self.scale_factor)
            if limit_min <= new_height <= limit_max:
                self.setFixedHeight(int(new_height))
                self.list_container.setFixedHeight(int(new_height - 75))
            event.accept()
        elif self.is_dragging and not self.position_locked:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_resizing = False
        self.is_dragging = False
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        event.accept()

    # --- 安全关闭与退出资源清理，彻底打碎 CMD 残留 ---
    def closeEvent(self, event):
        """重写关闭事件：当窗口关闭时彻底停止硬件、杀死子进程/线程"""
        if hasattr(self, "rms_thread") and self.rms_thread.isRunning():
            self.rms_thread.terminate()
            self.rms_thread.wait()  # 阻塞等待线程物理退出
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        event.accept()

    def exit_application(self):
        """完整注销硬件并强制关闭退出，不给终端任何挂起机会"""
        self.close()  # 触发上面完美的 closeEvent
        QtWidgets.QApplication.quit()
        sys.exit(0)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    misans_path = resource_path("misans.ttf")
    if os.path.exists(misans_path):
        font_id = QtGui.QFontDatabase.addApplicationFont(misans_path)
        if font_id != -1:
            families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
            if families:
                FONT_FAMILY = families[0]
                
    app.setFont(QtGui.QFont(FONT_FAMILY))
    
    player = DesktopMusicPlayer()
    player.show()
    sys.exit(app.exec())