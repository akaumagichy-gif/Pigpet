# -*- coding: utf-8 -*-
"""
旋转猪猪桌宠
================
一只绕自身逆时针旋转的透明小猪，做成极小的置顶桌宠窗口。

玩法: 按住猪猪 -> 以【点到的像素点】为轴心, 把它整体旋转+拉伸+压扁(像捏住一点猛拽, 越拖越怪诞)
      -> 松手沿反方向弹射。无重力直线飞行, 每次撞墙掉速, 几番后悬空停下(仍在旋转, 可再抓)。

多屏: 启动时在鼠标所在的屏幕居中生成; 右键 -> 放置到屏幕 -> 选任意屏幕。
退出: 右键 -> 退出, 或按 Esc。

运行: python pigpet.py      依赖: PyQt5 (已安装 5.9.7)
"""
import os
import math

from PyQt5.QtCore import QPoint, QPointF, QSize, Qt, QTimer
from PyQt5.QtGui import QCursor, QIcon, QKeySequence, QMovie, QPainter, QPixmap
from PyQt5.QtWidgets import (QApplication, QMenu, QShortcut, QSystemTrayIcon,
                             QWidget)

# ---------------- 可调常量 ----------------
W, H = 160, 160                 # 窗口大小 (正方形)
LAUNCH_K = 0.6                 # 发射力度系数 (越大射得越远/越快)
MIN_SPEED = 3.0                 # 最小发射速度 (避免原地不动)
TIMER_INTERVAL = 16             # 物理帧间隔 ms (~60fps)
SPIN_SPEED =90                 # 猪旋转播放速度 % (100=原速, 越小越慢)
MAX_STEP = 30.0                 # 单次物理子步最大位移, 防止高速穿墙
RESTITUTION = 0.95              # 撞墙反弹系数 (每次撞墙速度乘 0.82, 明显掉速)
AIR_DRAG = 0.995                 # 每帧轻微空气阻力 (让它最终能停下)
STOP_SPEED = 1.0                # 低于此速度即视为停下
MAX_PULL = 130.0                # 拉伸上限 (px), 拉过一点就不再增大力度

GIF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pigpig.gif')
TRAY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tray.png')


class PigPet(QWidget):
    def __init__(self):
        super().__init__()
        self.W, self.H = W, H

        # 无边框 + 置顶 + 不占任务栏 + 背景全透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)

        # 初始: 在鼠标所在屏幕居中
        start = self._screen_center(self._screen_at(QCursor.pos()))
        self.move(start)

        # 动画
        self.movie = QMovie(GIF_PATH)
        self.movie.setScaledSize(QSize(W, H))
        self.movie.setSpeed(SPIN_SPEED)   # 放慢旋转
        self.movie.frameChanged.connect(self.update)
        self.movie.start()

        # 弹弓/飞行状态
        self.dragging = False
        self.flying = False
        self.pivot = QPointF(start) + QPointF(W / 2, H / 2)  # 中心支点(窗口中心, 供发射)
        self.stretch = QPointF()    # 拉伸向量 (窗口坐标系, 中心->鼠标)
        self.grab_pt = None         # 按下时的点击像素点 (窗口系), 作为拖拽变形轴心
        self.vel = QPointF()        # 速度 (px/tick)
        self.fpos = QPointF(start)  # 精确位置 (含亚像素)

        # 物理定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.timer.start(TIMER_INTERVAL)

        # 退出: Esc
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._quit)

        # 系统托盘: 通知区(右下角)图标, 随时可隐藏/恢复/退出
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self._tray_icon(), self)
            self.tray.setToolTip('PigPet')
            self.tray_menu = QMenu(self)
            self._vis_action = self.tray_menu.addAction('')
            self._vis_action.triggered.connect(self._toggle_visible)
            self.tray_menu.addSeparator()
            self._add_screen_quit_items(self.tray_menu)
            # 每次弹出菜单时刷新"显示/隐藏"文字
            self.tray_menu.aboutToShow.connect(
                lambda: self._vis_action.setText(self._vis_label()))
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

    # ---------------- 屏幕辅助 ----------------
    def _screen_at(self, pos):
        for s in QApplication.screens():
            if s.geometry().contains(pos):
                return s
        return QApplication.primaryScreen()

    def _screen_center(self, screen):
        g = screen.availableGeometry()
        return QPoint(g.left() + (g.width() - self.W) // 2,
                      g.top() + (g.height() - self.H) // 2)

    def _current_geo(self):
        # 猪猪当前在哪个屏幕, 就用哪个屏幕 bounds 做反弹
        c = (self.fpos + QPointF(self.W / 2, self.H / 2)).toPoint()
        for s in QApplication.screens():
            if s.geometry().contains(c):
                return s.availableGeometry()
        return QApplication.primaryScreen().availableGeometry()

    def _move_to_screen(self, screen):
        p = self._screen_center(screen)
        self.move(p)
        self.fpos = QPointF(p)
        self.vel = QPointF()
        self.dragging = False
        self.flying = False
        self.stretch = QPointF()
        self.grab_pt = None

    # ---------------- 交互 ----------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self.flying = False
            self.vel = QPointF()
            self.fpos = QPointF(self.pos())
            self.pivot = self.fpos + QPointF(W / 2, H / 2)  # 支点 = 按下时窗口中心
            self.stretch = QPointF()
            self.grab_pt = e.pos()   # 点击像素点, 作为拖拽变形轴心
            self.update()

    def mouseMoveEvent(self, e):
        if self.dragging:
            # 窗口不移动, 只记录"拉伸"向量(中心 -> 鼠标)
            mouse_win = e.globalPos() - self.pos()
            vec = QPointF(mouse_win.x() - W / 2, mouse_win.y() - H / 2)
            d = math.hypot(vec.x(), vec.y())
            if d > MAX_PULL:  # 拉伸上限
                vec = vec * (MAX_PULL / d)
            self.stretch = vec
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            self.grab_pt = None
            self._launch()
            self.update()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction(self._vis_label(), self._toggle_visible)
        menu.addSeparator()
        self._add_screen_quit_items(menu)
        menu.exec_(e.globalPos())

    # ---------------- 系统托盘 (通知区右下角) ----------------
    def _add_screen_quit_items(self, menu):
        screen_menu = menu.addMenu('放置到屏幕')
        for i, s in enumerate(QApplication.screens(), 1):
            screen_menu.addAction('屏幕 %d' % i, lambda s=s: self._move_to_screen(s))
        menu.addSeparator()
        menu.addAction('退出', self._quit)

    def _vis_label(self):
        return '隐藏猪猪' if self.isVisible() else '显示猪猪'

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def _on_tray_activated(self, reason):
        # 左键单击/双击 -> 显示或隐藏猪猪
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_visible()

    @staticmethod
    def _tray_icon():
        # 多尺寸图标: Windows 按 DPI 挑最合适的, 避免模糊/压扁
        icon = QIcon()
        base = os.path.dirname(os.path.abspath(__file__))
        for s in (16, 32):
            p = QPixmap(os.path.join(base, 'tray_%d.png' % s))
            if not p.isNull():
                icon.addPixmap(p)
        if icon.isNull():
            icon = QIcon(TRAY_PATH)   # 兜底: 用原图
        return icon

    # ---------------- 弹弓发射 ----------------
    def _launch(self):
        # 拉伸方向的反方向弹射 (中心支点弹弓)
        vec = QPointF(-self.stretch.x(), -self.stretch.y())
        d = math.hypot(vec.x(), vec.y())
        if d < 2.0:
            self.vel = QPointF()   # 拉得太小, 原地不动
            self.flying = False
            return
        speed = max(d * LAUNCH_K, MIN_SPEED)
        self.vel = vec * (speed / d)
        self.flying = True
        self.stretch = QPointF()

    # ---------------- 物理 ---------------
    def _step(self):
        if not self.flying:
            return
        geo = self._current_geo()
        dist = math.hypot(self.vel.x(), self.vel.y())
        steps = max(1, int(math.ceil(dist / MAX_STEP)))
        vx, vy = self.vel.x() / steps, self.vel.y() / steps
        left, top = geo.left(), geo.top()
        right = geo.right() - self.W + 1   # 窗口左上角允许的最大 x
        bottom = geo.bottom() - self.H + 1
        for _ in range(steps):
            self.fpos.setX(self.fpos.x() + vx)
            self.fpos.setY(self.fpos.y() + vy)
            if self.fpos.x() < left:
                self.fpos.setX(left)
                self.vel.setX(abs(self.vel.x()) * RESTITUTION)
            elif self.fpos.x() > right:
                self.fpos.setX(right)
                self.vel.setX(-abs(self.vel.x()) * RESTITUTION)
            if self.fpos.y() < top:
                self.fpos.setY(top)
                self.vel.setY(abs(self.vel.y()) * RESTITUTION)
            elif self.fpos.y() > bottom:
                self.fpos.setY(bottom)
                self.vel.setY(-abs(self.vel.y()) * RESTITUTION)
        # 空气阻力: 每一帧整体轻微减速, 保证最终能停下
        self.vel *= AIR_DRAG
        # 速度过低 -> 悬空停住 (仍在旋转, 可抓)
        if math.hypot(self.vel.x(), self.vel.y()) < STOP_SPEED:
            self.vel = QPointF()
            self.flying = False
        self.move(int(round(self.fpos.x())), int(round(self.fpos.y())))

    # ---------------- 绘制 ----------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if self.dragging and math.hypot(self.stretch.x(), self.stretch.y()) > 2.0:
            # 以【点击到的像素点】为轴心绕它旋转+压扁, 并自动缩放整只猪避免被窗口裁剪
            g = self.grab_pt or QPoint(self.W // 2, self.H // 2)
            gx, gy = g.x(), g.y()
            sx, sy = self.stretch.x(), self.stretch.y()
            d = math.hypot(sx, sy)
            ang = math.atan2(sy, sx)
            k = min(1.0, d / MAX_PULL)
            stretch = 1 + 0.7 * k     # 沿拖动轴拉伸 (调低, 防过度变形)
            squash = 1 - 0.30 * k     # 垂直方向压扁
            ca, sa = math.cos(ang), math.sin(ang)

            # 变形后 4 个角的包围盒, 求统一缩放因子 f: 让整只猪始终留在窗口内
            corners = []
            for px, py in ((0, 0), (self.W, 0), (0, self.H), (self.W, self.H)):
                ox, oy = px - gx, py - gy
                rx = (stretch * ox) * ca - (squash * oy) * sa
                ry = (stretch * ox) * sa + (squash * oy) * ca
                corners.append((gx + rx, gy + ry))
            minx = min(c[0] for c in corners); maxx = max(c[0] for c in corners)
            miny = min(c[1] for c in corners); maxy = max(c[1] for c in corners)
            bw = max(1e-6, maxx - minx); bh = max(1e-6, maxy - miny)
            cx = (minx + maxx) / 2; cy = (miny + maxy) / 2
            margin = 8
            f = min(1.0, (self.W - 2 * margin) / bw, (self.H - 2 * margin) / bh)

            pix = self.movie.currentPixmap()
            p.save()
            p.translate(self.W / 2, self.H / 2)   # fit 后再居中
            p.scale(f, f)
            p.translate(-cx, -cy)
            p.translate(gx, gy)                    # 轴心 = 点击像素
            p.rotate(math.degrees(ang))
            p.scale(stretch, squash)
            p.translate(-gx, -gy)
            p.drawPixmap(0, 0, pix)                # 以窗口原点绘制, 整体绕点击像素变形
            p.restore()
        else:
            p.drawPixmap(0, 0, self.movie.currentPixmap())

    def _quit(self):
        QApplication.instance().quit()


def main():
    app = QApplication([])
    # 有系统托盘作为"锚", 猪被隐藏时程序不应退出 (靠托盘/菜单 退出 才退出)
    app.setQuitOnLastWindowClosed(False)
    pet = PigPet()
    pet.show()
    app.exec_()


if __name__ == '__main__':
    main()
