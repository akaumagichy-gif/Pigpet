# -*- coding: utf-8 -*-
import os, time
from PyQt5.QtGui import QMovie

GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pigpig.gif')
m = QMovie(GIF)
print('frameCount =', m.frameCount())

# Measure how many distinct frames cycle in one wall-clock second at default speed.
m.jumpToFrame(0)
m.fillRequested.connect(lambda: None)
m.start()
seen = []
last = None
t0 = time.time()
while time.time() - t0 < 2.0:
    f = m.currentFrameNumber()
    if f != last:
        seen.append(f)
        last = f
    time.sleep(0.001)
    m.jumpToFrame(m.currentFrameNumber())  # keep alive
m.stop()

distinct = sorted(set(seen))
print('distinct frames over ~2s =', len(distinct), distinct)
