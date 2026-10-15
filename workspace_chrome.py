"""Workspace chrome: collapse changes presentation only, never media lifecycle."""
import json
from PySide6.QtCore import QObject, Qt, QSize
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QToolBar, QStyle, QPushButton
from localization import tr

def compact_icon(name):
    paths = {'home': 'M3 9 L10 3 L17 9 M5 8 V17 H8 V12 H12 V17 H15 V8',
             'add': 'M10 4 V16 M4 10 H16',
             'back': 'M12 4 L6 10 L12 16',
             'forward': 'M8 4 L14 10 L8 16'}
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><path d="'+paths[name]+'" fill="none" stroke="#4e5a67" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pixmap=QPixmap();pixmap.loadFromData(svg.encode(),'SVG')
    return QIcon(pixmap)

class WorkspaceChrome(QObject):
    def __init__(self, window, toolbar):
        super().__init__(window)
        self.window = window
        self.docks = (window.network_dock, window.assistant_dock)
        self.widths = [d.width() for d in self.docks]
        self.focus_saved = None
        for index, area in enumerate((Qt.LeftToolBarArea, Qt.RightToolBarArea)):
            rail = QToolBar(window)
            rail.setObjectName('workspaceEdge'+str(index))
            rail.setMovable(False);rail.setFloatable(False)
            rail.setIconSize(QSize(16,16))
            rail.setStyleSheet("QToolBar { padding: 0px; spacing: 0px; } QToolButton { padding: 3px; }")
            action = QAction(window.style().standardIcon(QStyle.SP_ArrowRight if index == 0 else QStyle.SP_ArrowLeft),
                             tr('Show / hide workspace') if index == 0 else tr('Show / hide engineer'), window)
            action.setIcon(compact_icon('back' if index == 0 else 'forward'))
            self.docks[index].visibilityChanged.connect(lambda visible,i=index,a=action:a.setIcon(
                compact_icon('back' if (i==0)==visible else 'forward')))
            action.triggered.connect(lambda checked=False,i=index:self.toggle(i))
            rail.addAction(action);window.addToolBar(area,rail)
        self.focus = QAction(window.style().standardIcon(QStyle.SP_TitleBarMaxButton),tr('Expand workspace / restore panels'),window)
        self.focus.setCheckable(True);self.focus.setShortcut('Ctrl+Shift+Space')
        self.focus.triggered.connect(self.toggle_focus);toolbar.addSeparator();toolbar.addAction(self.focus)
        self.badge = QPushButton()
        self.badge.setToolTip(tr('Open audio monitor'))
        self.badge.clicked.connect(window.open_audio)
        window.statusBar().addPermanentWidget(self.badge)
        self.badge.hide()
        window.left_tabs.currentChanged.connect(self.update_player)
        self.update_player()

    def persist(self):
        self.window.settings.setValue('layout',self.window.saveState())
        self.window.settings.sync()

    def update_player(self,*_):
        self.window.player.setVisible(self.window.left_tabs.currentIndex()==1 and self.window.access.allowed('audio'))

    def toggle(self,index):
        dock=self.docks[index]
        if not dock.isHidden():
            self.widths[index]=dock.width();dock.hide()
        else:
            dock.show()
            self.window.resizeDocks([dock],[max(270,self.widths[index])],Qt.Horizontal)
        self.focus_saved=None;self.focus.setChecked(False)
        self.persist()

    def toggle_focus(self,checked):
        if checked:
            self.focus_saved=[not d.isHidden() for d in self.docks]
            self.widths=[d.width() for d in self.docks]
            for dock in self.docks:dock.hide()
        else:
            for dock,visible in zip(self.docks,self.focus_saved or [True,True]):dock.setVisible(visible)
            self.window.resizeDocks(list(self.docks),[max(270,w) for w in self.widths],Qt.Horizontal)
            self.focus_saved=None
        self.persist()

    def update_badge(self):
        player=self.window.player
        active=bool(player.receiver or player.recorder)
        self.badge.setVisible(active and self.window.access.allowed('audio'))
        if active:
            channel=(player.source or {}).get('channel') or '—'
            self.badge.setText(('● '+tr('Recording') if player.recorder else '▶ '+tr('Audio'))+' · '+str(channel))
