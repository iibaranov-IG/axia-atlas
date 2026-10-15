"""Two presentation profiles. No changes to operational state or window ownership."""
from PySide6.QtGui import QColor, QFont, QPalette

SKINS = {'windows': 'Windows', 'macos': 'macOS'}

TOKENS = {
    'windows': dict(window='#f3f3f3', panel='#f8f9fb', base='#ffffff', ink='#202020',
                    secondary='#565d68', border='#bdc5d0', accent='#0067c0', hover='#e7f0fa',
                    selected='#d9eafa', radius=3, padding=4, row=24, font=9,
                    button='#ffffff', toolbar='#f6f6f6', title='#e8edf3', bubble=5),
    'macos': dict(window='#eeedf1', panel='#e9e8ed', base='#ffffff', ink='#25252b',
                  secondary='#5c5b66', border='#c8c6cf', accent='#0069d9', hover='#e4ebf6',
                  selected='#dfebff', radius=9, padding=6, row=28, font=9,
                  button='#fafafa', toolbar='#e5e4e9', title='#e9e8ed', bubble=13),
}


def stylesheet(skin):
    t = TOKENS[skin]
    return f'''
    QMainWindow {{ background: {t['window']}; }}
    QWidget {{ color: {t['ink']}; }}
    QWidget:disabled {{ color: #737780; }}
    QWidget#workspacePanel, QWidget#assistantPanel {{ background: {t['panel']}; }}
    QMenuBar {{ background: {t['toolbar']}; padding: 3px; border-bottom: 1px solid {t['border']}; }}
    QMenuBar::item {{ padding: 4px 8px; background: transparent; border-radius: {t['radius']}px; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {t['selected']}; color: {t['ink']}; }}
    QMenu {{ background: {t['base']}; border: 1px solid {t['border']}; padding: 5px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: {t['radius']}px; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
    QToolBar {{ background: {t['toolbar']}; border: none; border-bottom: 1px solid {t['border']}; spacing: 5px; padding: 5px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {t['radius']}px; padding: 4px 7px; }}
    QToolButton:hover {{ background: {t['hover']}; border-color: {t['border']}; }}
    QToolButton:pressed {{ background: {t['selected']}; }}
    QDockWidget::title {{ background: {t['title']}; padding: 7px 9px; font-weight: 600; }}
    QMainWindow::separator {{ background: {t['window']}; width: 6px; height: 6px; }}
    QMainWindow::separator:hover {{ background: {t['accent']}; }}
    QTabWidget::pane {{ background: {t['base']}; border: 1px solid {t['border']}; border-radius: {t['radius']}px; }}
    QTabBar::tab {{ background: {t['panel']}; color: {t['secondary']}; border: 1px solid transparent;
        padding: {t['padding'] + 2}px {t['padding'] + 3}px; margin: 2px 1px; border-radius: {t['radius']}px; }}
    QTabBar::tab:selected {{ background: {t['base']}; color: {t['ink']}; border-color: {t['border']}; }}
    QTabBar::tab:hover:!selected {{ background: {t['hover']}; }}
    QTabBar::tab:disabled {{ color: #737780; }}
    QPushButton {{ background: {t['button']}; border: 1px solid {t['border']}; border-radius: {t['radius']}px;
        padding: {t['padding']}px 10px; min-height: 18px; }}
    QPushButton:hover {{ background: {t['hover']}; border-color: {t['accent']}; }}
    QPushButton:pressed {{ background: {t['selected']}; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {t['accent']}; }}
    QPushButton[intent="primary"] {{ background: {t['accent']}; border-color: {t['accent']}; color: white; }}
    QPushButton[intent="primary"]:hover {{ background: #0056ab; }}
    QPushButton:disabled, QPushButton[intent="primary"]:disabled {{ background: {t['panel']}; color: #737780; border-color: {t['border']}; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background: {t['base']}; border: 1px solid {t['border']}; border-radius: {t['radius']}px;
        padding: {t['padding']}px; selection-background-color: {t['accent']}; selection-color: white; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QComboBox {{ padding-right: 20px; min-height: 18px; }}
    QComboBox::drop-down {{ width: 20px; border: none; }}
    QAbstractItemView {{ background: {t['base']}; alternate-background-color: {t['panel']};
        border: 1px solid {t['border']}; border-radius: {t['radius']}px;
        selection-background-color: {t['selected']}; selection-color: {t['ink']}; outline: 0; }}
    QTreeView::item, QListView::item {{ min-height: {t['row']}px; padding: 2px 3px; }}
    QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{ background: {t['selected']}; color: {t['ink']}; }}
    QHeaderView::section {{ background: {t['panel']}; color: {t['secondary']}; border: none;
        border-bottom: 1px solid {t['border']}; padding: 6px; font-weight: 600; }}
    QGroupBox {{ border: 1px solid {t['border']}; border-radius: {t['radius']}px; margin-top: 12px; padding: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QCheckBox, QRadioButton {{ spacing: 6px; padding: 2px; }}
    QProgressBar {{ border: 1px solid {t['border']}; border-radius: {t['radius']}px; background: {t['panel']};
        min-height: 12px; text-align: center; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: {max(1, t['radius']-2)}px; }}
    QScrollBar:vertical {{ background: {t['panel']}; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #a1a5ae; min-height: 28px; border: 3px solid {t['panel']}; border-radius: 5px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QStatusBar {{ background: {t['toolbar']}; color: {t['secondary']}; border-top: 1px solid {t['border']}; padding: 3px; }}
    QStatusBar::item {{ border: none; }}
    QScrollArea#engineerChat, QWidget#chatSurface {{ background: {t['panel']}; border: none; }}
    QLabel#chatWelcome {{ color: {t['secondary']}; padding: 28px 12px; font-size: 13px; }}
    QWidget#chatComposer {{ background: {t['base']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    QPlainTextEdit#chatInput {{ background: transparent; border: none; padding: 4px; }}
    QFrame#messageBubble {{ border: 1px solid {t['border']}; border-radius: 12px; background: {t['base']}; }}
    QFrame#messageBubble[speaker="user"] {{ background: {t['selected']}; }}
    QFrame#messageBubble[speaker="notice"] {{ background: #fff5d8; }}
    QFrame#messageBubble QLabel {{ background: transparent; border: none; color: {t['ink']}; }}
    QToolTip {{ background: #fffbe8; color: #202020; border: 1px solid {t['border']}; padding: 5px; }}
    '''


def apply_skin(window, requested):
    skin = requested if requested in SKINS else 'windows'
    t = TOKENS[skin]
    palette = QPalette(window.palette())
    for role, value in ((QPalette.Window,t['window']), (QPalette.WindowText,t['ink']),
                        (QPalette.Base,t['base']), (QPalette.AlternateBase,t['panel']),
                        (QPalette.Text,t['ink']), (QPalette.Button,t['button']),
                        (QPalette.ButtonText,t['ink']), (QPalette.Highlight,t['accent']),
                        (QPalette.HighlightedText,'#ffffff')):
        palette.setColor(role, QColor(value))
    window.setPalette(palette)
    window.setFont(QFont('Segoe UI', t['font']))
    window.setStyleSheet(stylesheet(skin))
    window.setProperty('atlasSkin', skin)
    return skin
