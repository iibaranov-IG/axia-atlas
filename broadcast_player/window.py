"""Independent desktop workspace for library, queue and local rehearsal."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QTranslator, QLibraryInfo
from PySide6.QtGui import QAction, QKeySequence, QColor
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QFileDialog, QMessageBox, QInputDialog,
    QSlider, QProgressBar, QCheckBox, QGroupBox, QMenu, QAbstractItemView, QApplication, QDoubleSpinBox)

from . import VERSION
from .store import PlayerStore
from .media import ImportWorker, availability
from .deck import LocalDeck
from .playout import QueueDeck


def duration_text(milliseconds):
    seconds = max(0, int(milliseconds) // 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'


ERRORS = {
    'missing': ('Файл не найден. Добавьте его заново из нового расположения.', 'File missing. Import it again from its new location.'),
    'unreadable': ('Нет доступа к файлу.', 'The file cannot be read.'),
    'changed': ('Файл изменился. Добавьте его заново для проверки.', 'File changed. Import it again to validate it.'),
    'decode_failed': ('Не удалось прочитать звук. Проверьте файл.', 'Audio decoding failed. Check the file.'),
    'truncated': ('Файл обрезан: звук короче заявленной длительности.', 'Truncated file: audio is shorter than its declared duration.'),
    'unsupported': ('Этот формат пока не поддерживается.', 'This file format is not supported yet.'),
    'audio_only': ('Нужен аудиофайл с одной звуковой дорожкой, без видео.', 'Use an audio-only file with one audio track.'),
    'mono_stereo': ('Поддерживается только моно и стерео.', 'Only mono and stereo are supported.'),
    'format_changed': ('Формат звука меняется внутри файла.', 'Audio format changes within the file.'),
    'empty_audio': ('Файл не содержит звука.', 'The file contains no audio frames.'),
    'output_missing': ('Выберите доступное устройство вывода звука.', 'Select an available audio output device.'),
    'stalled': ('Воспроизведение не продвигается. Проверьте файл и устройство вывода.', 'Playback stalled. Check the file and output device.'),
    'output_format': ('Выход не поддерживает подходящий стереоформат. Выберите другой выход.', 'This output has no supported stereo format. Select another output.'),
    'output_open': ('Не удалось открыть звуковой выход.', 'Could not open the audio output.'),
    'output_write': ('Не удалось передать звук на выход.', 'Could not write audio to the output.'),
    'output_underrun': ('Буфер звукового выхода опустел. Воспроизведение остановлено; проверьте нагрузку компьютера.', 'The audio output buffer ran empty. Playback stopped; check computer load.'),
    'output_late': ('Подача звука задержалась. Непрерывность не подтверждена; очередь остановлена. Проверьте нагрузку компьютера.', 'Audio delivery was delayed. Continuity is unconfirmed; the queue stopped. Check computer load.'),
    'not_prepared': ('Следующий материал не успел подготовиться. Очередь остановлена после текущего.', 'The next item was not prepared in time. The queue stopped after the current item.'),
    'cache_space': ('Не удалось подготовить звук на диске. Проверьте свободное место и доступ к папке плеера.', 'Could not prepare audio on disk. Check free space and access to the player folder.'),
    'cache_read': ('Не удалось прочитать подготовленный звук. Запустите очередь заново.', 'Could not read prepared audio. Start the queue again.'),
}

STYLES = '''
QMainWindow, QWidget#root { background: #f3f5f8; color: #182435; }
QWidget { font-family: "Segoe UI"; font-size: 10pt; }
QLabel { color: #182435; }
QLabel#brand { font-size: 21pt; font-weight: 700; }
QLabel#muted { color: #586a7d; }
QLabel#nowTitle { font-size: 20pt; font-weight: 600; }
QLabel#time { font-family: "Consolas"; font-size: 16pt; }
QLabel#badge { background: #e4ecf8; color: #285d95; padding: 7px 12px; border-radius: 5px; }
QLabel#notice { background: #fff2d7; color: #754f10; padding: 8px; border-radius: 4px; }
QGroupBox { background: white; border: 1px solid #cdd6e0; border-radius: 6px; margin-top: 12px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #b9c8d8; border-radius: 4px; padding: 7px 12px; }
QPushButton:hover { background: #eaf2fb; border-color: #2775c5; }
QPushButton:pressed { background: #d9e8f9; }
QPushButton:disabled { color: #8995a4; background: #eff2f5; border-color: #d4dce5; }
QPushButton#primary { background: #1267b5; color: white; border-color: #1267b5; font-weight: 600; }
QPushButton#primary:disabled { background: #e0e6ed; border-color: #d4dce5; color: #758397; }
QPushButton#jingle { text-align: left; padding: 10px; min-height: 45px; background: #f2f7fc; }
QLineEdit, QComboBox { background: white; border: 1px solid #b9c8d8; border-radius: 4px; padding: 6px; }
QTreeWidget { background: white; alternate-background-color: #f6f8fb; border: 1px solid #cdd6e0; border-radius: 4px; }
QTreeWidget::item { min-height: 29px; }
QTreeWidget::item:selected { background: #deedfc; color: #132f4f; }
QHeaderView::section { background: #edf2f7; padding: 7px; border: none; border-bottom: 1px solid #cdd6e0; color: #4b5f73; }
QProgressBar { border: none; border-radius: 3px; background: #e7edf3; height: 8px; }
QProgressBar::chunk { background: #2d9c74; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 9px 16px; background: #edf2f7; }
QTabBar::tab:selected { color: #1267b5; background: white; }
QStatusBar { background: #eaf0f6; color: #4b5f73; }
QMenuBar { background: #f3f5f8; }
QMenu { background: white; }
QMenu::item:selected { background: #deedfc; }
QSplitter::handle { background: #f3f5f8; }
'''


class PlayerWindow(QMainWindow):
    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.store = PlayerStore(self.data_dir / 'player.sqlite3')
        self.lang = self.store.setting('language', 'ru')
        self.queue = self.store.setting('queue', [])
        self.index = -1
        self.running = False
        self.generation = 0
        self.worker = None
        self.import_errors = 0
        self.import_count = 0
        self.last_started = None
        self.close_pending = False
        self.translator = QTranslator(self)
        self.deck = QueueDeck(self.data_dir / 'audio-cache', self)
        self.cue = LocalDeck(self)
        self.deck.ended.connect(self.advance)
        self.deck.started.connect(self.track_started)
        self.deck.completed.connect(lambda index: self.log('completed', self.deck.items[index]['title']))
        self.deck.interrupted.connect(lambda index: self.log('tail_interrupted', self.deck.items[index]['title']))
        self.deck.transition.connect(lambda index, milliseconds: self.log('transition',
            self.deck.items[index]['title'] + f' · {milliseconds / 1000:g} ' + self.t('с', 's')))
        self.deck.failed.connect(lambda error: self.playback_failed('queue', error))
        self.cue.failed.connect(lambda error: self.playback_failed('cue', error))
        self.deck.changed.connect(self.update_transport)
        self.cue.changed.connect(self.update_cue)
        self.cue.ended.connect(lambda: self.log('cue_completed', self.cue.item['title']))
        self.deck.position.connect(self.position_changed)
        self.cue.position.connect(self.cue_position)
        self.deck.levels.connect(self.show_levels)
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self.refresh_outputs)
        self.setAcceptDrops(True)
        self.setWindowTitle(f'ATLAS Broadcast Player — {VERSION}')
        self.resize(1240, 850)
        self.setMinimumSize(980, 690)
        self.setStyleSheet(STYLES)
        self.build()
        self.log('session_opened', VERSION)

    def t(self, ru, en):
        return ru if self.lang == 'ru' else en

    def error_text(self, error):
        if error.startswith('playback_error:'):
            return self.t('Ошибка воспроизведения: ', 'Playback error: ') + error.partition(':')[2].strip()
        return self.t(*ERRORS[error]) if error in ERRORS else error

    def button(self, ru, en, callback, primary=False):
        button = QPushButton(self.t(ru, en))
        if primary:
            button.setObjectName('primary')
        button.clicked.connect(callback)
        return button

    def label(self, text, name=None):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        if name:
            label.setObjectName(name)
        return label

    def table(self, headings):
        tree = QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setHeaderLabels([self.t(*text) for text in headings])
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(headings)):
            tree.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        return tree

    def build(self):
        app = QApplication.instance()
        app.removeTranslator(self.translator)
        if self.lang == 'ru' and self.translator.load('qtbase_ru', QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(self.translator)
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu(self.t('Файл', 'File'))
        self.import_action = QAction(self.t('Добавить аудиофайлы…', 'Import audio files…'), file_menu)
        self.import_action.setShortcut(QKeySequence.Open)
        self.import_action.triggered.connect(self.choose_files)
        file_menu.addAction(self.import_action)
        save_action = QAction(self.t('Сохранить плейлист…', 'Save playlist…'), file_menu)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_playlist)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.t('Выход', 'Exit'), self.close)
        help_menu = self.menuBar().addMenu(self.t('Справка', 'Help'))
        help_menu.addAction(self.t('Как начать', 'Getting started'), self.help)
        root = QWidget()
        root.setObjectName('root')
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(self.label('ATLAS Broadcast Player', 'brand'))
        top.addStretch()
        top.addWidget(self.label(self.t('ЛОКАЛЬНАЯ РЕПЕТИЦИЯ', 'LOCAL REHEARSAL'), 'badge'))
        self.language = QComboBox()
        self.language.addItem('Русский', 'ru')
        self.language.addItem('English', 'en')
        self.language.setCurrentIndex(0 if self.lang == 'ru' else 1)
        self.language.currentIndexChanged.connect(self.change_language)
        top.addWidget(self.language)
        layout.addLayout(top)
        station_row = QHBoxLayout()
        station_row.addWidget(self.label(self.t('Станция', 'Station')))
        self.station = QLineEdit(self.store.setting('station', ''))
        self.station.setPlaceholderText(self.t('Название вашей радиостанции', 'Your radio station name'))
        self.station.editingFinished.connect(lambda: self.store.set_setting('station', self.station.text().strip()))
        station_row.addWidget(self.station, 1)
        station_row.addWidget(self.label(self.t('Подготовка плейлистов и проверка на локальном выходе',
                                              'Prepare playlists and check them on a local output'), 'muted'))
        layout.addLayout(station_row)
        self.notice = self.label('', 'notice')
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        transport = QGroupBox(self.t('Воспроизведение очереди', 'Queue playback'))
        box = QVBoxLayout(transport)
        outputs = QHBoxLayout()
        outputs.addWidget(self.label(self.t('Выход', 'Output')))
        self.output = QComboBox()
        self.output.setMinimumWidth(280)
        outputs.addWidget(self.output, 1)
        self.state_label = self.label('', 'badge')
        outputs.addWidget(self.state_label)
        box.addLayout(outputs)
        self.now = self.label(self.t('Добавьте первый материал в очередь', 'Add the first item to the queue'), 'nowTitle')
        self.now.setWordWrap(True)
        box.addWidget(self.now)
        self.next_label = self.label('', 'muted')
        box.addWidget(self.next_label)
        timeline = QHBoxLayout()
        self.elapsed = self.label('0:00', 'time')
        self.remaining = self.label('−0:00', 'time')
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderReleased.connect(lambda: self.deck.seek(self.seek.value()))
        for widget in (self.elapsed, self.seek, self.remaining):
            timeline.addWidget(widget, 1 if widget is self.seek else 0)
        box.addLayout(timeline)
        controls = QHBoxLayout()
        self.play = self.button('▶  Старт', '▶  Start', self.start_queue, True)
        self.pause = self.button('Пауза', 'Pause', self.deck.toggle_pause)
        self.stop = self.button('■  Стоп', '■  Stop', self.stop_queue)
        self.next_button = self.button('Следующий  ▶|', 'Next  ▶|', self.skip)
        self.stop_after = QCheckBox(self.t('Стоп после текущего', 'Stop after current'))
        self.stop_after.toggled.connect(self.deck.set_stop_after)
        for widget in (self.play, self.pause, self.stop, self.next_button, self.stop_after):
            controls.addWidget(widget)
        controls.addStretch()
        controls.addWidget(self.label(self.t('Громкость', 'Volume')))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(round(self.deck.volume * 100))
        self.volume.setMaximumWidth(110)
        self.volume.valueChanged.connect(self.deck.set_volume)
        controls.addWidget(self.volume)
        meters = QVBoxLayout()
        self.meters = []
        for channel in ('L', 'R'):
            row = QHBoxLayout()
            row.addWidget(self.label(channel))
            meter = QProgressBar()
            meter.setRange(0, 60)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setFixedWidth(110)
            row.addWidget(meter)
            meters.addLayout(row)
            self.meters.append(meter)
        controls.addLayout(meters)
        box.addLayout(controls)
        transition_row = QHBoxLayout()
        transition_row.addWidget(self.label(self.t('Плавный переход, с', 'Crossfade, s')))
        self.crossfade = QDoubleSpinBox()
        self.crossfade.setRange(0, 10)
        self.crossfade.setDecimals(1)
        self.crossfade.setSingleStep(.5)
        self.crossfade.setValue(self.store.setting('crossfade_ms', 0) / 1000)
        self.crossfade.setMinimumWidth(70)
        self.crossfade.setToolTip(self.t('0 — стык без наложения. Короткие файлы: не более половины каждого.',
                                        '0: no overlap. Short files: at most half of each item.'))
        self.crossfade.valueChanged.connect(self.transition_setting_changed)
        transition_row.addWidget(self.crossfade)
        transition_row.addWidget(self.label(self.t('0 — без наложения · настройка до старта',
                                                 '0: no overlap · set before starting'), 'muted'))
        transition_row.addStretch()
        self.preload_status = self.label('', 'muted')
        transition_row.addWidget(self.preload_status)
        box.addLayout(transition_row)
        layout.addWidget(transport)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 5, 0)
        self.library_tabs = QTabWidget()
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        library_layout.setContentsMargins(0, 10, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t('Поиск по названию или пути…', 'Search title or path…'))
        self.search.textChanged.connect(self.filter_library)
        library_layout.addWidget(self.search)
        library_buttons = QHBoxLayout()
        self.import_button = self.button('＋ Аудиофайлы', '＋ Audio files', self.choose_files)
        self.add_button = self.button('В очередь →', 'Add to queue →', self.add_selected)
        library_buttons.addWidget(self.import_button)
        library_buttons.addWidget(self.add_button)
        library_layout.addLayout(library_buttons)
        self.library = self.table([('Название', 'Title'), ('Время', 'Time'), ('Формат', 'Format'), ('Проверка', 'Check')])
        self.library.itemDoubleClicked.connect(lambda item, column: self.add_selected())
        library_layout.addWidget(self.library, 1)
        self.import_status = self.label(self.t('Перетащите WAV, MP3, FLAC, OGG, M4A или AAC сюда.',
                                              'Drop WAV, MP3, FLAC, OGG, M4A or AAC files here.'), 'muted')
        self.import_status.setWordWrap(True)
        library_layout.addWidget(self.import_status)
        self.cancel_import = self.button('Отменить проверку', 'Cancel validation', self.cancel_validation)
        self.cancel_import.hide()
        library_layout.addWidget(self.cancel_import)
        self.library_tabs.addTab(library_page, self.t('Медиатека', 'Media library'))
        events_page = QWidget()
        events_layout = QVBoxLayout(events_page)
        events_layout.setContentsMargins(0, 10, 0, 0)
        self.history = self.table([('Событие', 'Event'), ('Время', 'Time')])
        events_layout.addWidget(self.history)
        events_layout.addWidget(self.button('Сохранить журнал…', 'Export history…', self.export_events))
        self.library_tabs.addTab(events_page, self.t('Журнал', 'History'))
        left_layout.addWidget(self.library_tabs)
        cue_box = QGroupBox(self.t('Подслушка выбранного материала', 'Selected item preview'))
        cue_layout = QVBoxLayout(cue_box)
        self.cue_output = QComboBox()
        cue_layout.addWidget(self.cue_output)
        cue_buttons = QHBoxLayout()
        self.preview_button = self.button('▶ Прослушать', '▶ Preview', self.preview_selected)
        self.cue_stop = self.button('■ Стоп', '■ Stop', self.stop_cue)
        cue_buttons.addWidget(self.preview_button)
        cue_buttons.addWidget(self.cue_stop)
        cue_layout.addLayout(cue_buttons)
        self.cue_status = self.label(self.t('Подслушка остановлена', 'Preview stopped'), 'muted')
        self.cue_status.setWordWrap(True)
        cue_layout.addWidget(self.cue_status)
        left_layout.addWidget(cue_box)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(5, 0, 0, 0)
        playlist_row = QHBoxLayout()
        self.playlists = QComboBox()
        self.refresh_playlists()
        self.load_button = self.button('Открыть', 'Load', self.load_playlist)
        self.save_button = self.button('Сохранить…', 'Save…', self.save_playlist)
        playlist_row.addWidget(self.playlists, 1)
        playlist_row.addWidget(self.load_button)
        playlist_row.addWidget(self.save_button)
        right_layout.addLayout(playlist_row)
        self.queue_table = self.table([('Очередь', 'Queue'), ('Время', 'Time'), ('Состояние', 'State')])
        self.queue_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queue_table.itemSelectionChanged.connect(self.update_transport)
        right_layout.addWidget(self.queue_table, 1)
        row = QHBoxLayout()
        self.up_button = self.button('↑', '↑', lambda: self.move_item(-1))
        self.down_button = self.button('↓', '↓', lambda: self.move_item(1))
        self.remove_button = self.button('Убрать', 'Remove', self.remove_item)
        self.clear_button = self.button('Очистить', 'Clear', self.clear_queue)
        self.up_button.setToolTip(self.t('Переместить вверх', 'Move up'))
        self.down_button.setToolTip(self.t('Переместить вниз', 'Move down'))
        for widget in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            row.addWidget(widget)
        row.addStretch()
        self.total = self.label('', 'muted')
        row.addWidget(self.total)
        right_layout.addLayout(row)
        jingle_box = QGroupBox(self.t('Джинглы · подслушка', 'Jingles · preview'))
        jingles = QGridLayout(jingle_box)
        self.jingle_buttons = []
        self.jingle_actions = getattr(self, 'jingle_actions', [])
        for action in self.jingle_actions:
            self.removeAction(action)
            action.deleteLater()
        self.jingle_actions = []
        for slot in range(8):
            button = QPushButton()
            button.setObjectName('jingle')
            button.clicked.connect(lambda checked=False, s=slot: self.jingle(s))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point, s=slot: self.jingle_menu(s, point))
            jingles.addWidget(button, slot // 4, slot % 4)
            self.jingle_buttons.append(button)
            action = QAction(self)
            action.setShortcut(f'Ctrl+{slot + 1}')
            action.triggered.connect(lambda checked=False, s=slot: self.jingle(s))
            self.addAction(action)
            self.jingle_actions.append(action)
        right_layout.addWidget(jingle_box)
        hint = self.label(self.t('Пустая кнопка — назначить выбранный файл. Правая кнопка — изменить.',
                                'Empty pad: assign selected file. Right-click: change assignment.'), 'muted')
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        split.addWidget(right)
        split.setSizes([480, 660])
        layout.addWidget(split, 1)
        self.output.currentIndexChanged.connect(self.update_transport)
        self.cue_output.currentIndexChanged.connect(self.update_cue)
        self.refresh_outputs()
        self.refresh_library()
        self.refresh_queue()
        self.refresh_jingles()
        self.refresh_history()
        self.update_cue()
        self.statusBar().showMessage(self.t('Очередь сохраняется автоматически. При открытии звук всегда остановлен.',
                                            'Queue is saved automatically. Playback is always stopped on startup.'))

    def change_language(self):
        if self.running or self.cue.active or self.worker:
            return
        self.store.set_setting('station', self.station.text().strip())
        self.lang = self.language.currentData()
        self.store.set_setting('language', self.lang)
        self.build()

    def refresh_outputs(self):
        devices = QMediaDevices.audioOutputs()
        for combo in (self.output, self.cue_output):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self.t('Выберите устройство вывода…', 'Select an output device…'), None)
            for device in devices:
                combo.addItem(device.description(), bytes(device.id()))
            index = combo.findData(selected) if selected is not None else 0
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        self.update_transport()
        self.update_cue()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t('Добавить аудиофайлы', 'Import audio files'),
            self.store.setting('last_folder', str(Path.home() / 'Music')),
            self.t('Аудиофайлы', 'Audio') + ' (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;' +
            self.t('Все файлы', 'All files') + ' (*)', options=QFileDialog.DontUseNativeDialog)
        if paths:
            self.store.set_setting('last_folder', str(Path(paths[0]).parent))
            self.import_files(paths)

    def import_files(self, paths):
        if self.worker or self.running or self.cue.active:
            self.notify(self.t('Остановите воспроизведение и дождитесь текущей проверки.',
                               'Stop playback and wait for the current validation to finish.'))
            return
        self.import_count = self.import_errors = 0
        self.worker = ImportWorker(paths, self)
        self.worker.inspected.connect(self.import_result)
        self.worker.progress.connect(self.import_progress)
        self.worker.failed.connect(self.notify)
        self.worker.finished.connect(self.import_finished)
        self.import_button.setEnabled(False)
        self.import_action.setEnabled(False)
        self.cancel_import.show()
        self.notice.hide()
        self.update_transport()
        self.update_cue()
        self.worker.start()

    def import_result(self, media):
        self.store.put_media(media)
        self.import_count += 1
        if media['status'] != 'ready':
            self.import_errors += 1
        self.log('imported' if media['status'] == 'ready' else 'rejected', media['path'])

    def import_progress(self, index, total, name):
        self.import_status.setText(self.t('Проверка звука', 'Validating audio') + f' · {index}/{total} · {name}')

    def cancel_validation(self):
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_import.setEnabled(False)

    def import_finished(self):
        worker, self.worker = self.worker, None
        cancelled = worker.isInterruptionRequested()
        worker.deleteLater()
        self.cancel_import.hide()
        self.cancel_import.setEnabled(True)
        prefix = self.t('Проверка отменена. ', 'Validation cancelled. ') if cancelled else ''
        self.import_status.setText(prefix + self.t('Обработано: ', 'Processed: ') + str(self.import_count) +
                                  self.t(' · ошибок: ', ' · errors: ') + str(self.import_errors))
        self.refresh_library()
        self.refresh_queue()
        self.update_transport()
        self.update_cue()
        if self.close_pending:
            QTimer.singleShot(0, self.close)

    def refresh_library(self):
        selected = {item.data(0, Qt.UserRole) for item in self.library.selectedItems()}
        self.library.clear()
        for media in self.store.library():
            error = availability(media)
            item = QTreeWidgetItem([media['title'], duration_text(media['duration_ms']),
                                   f"{Path(media['path']).suffix[1:].upper()} · {media['sample_rate'] / 1000:g} " + self.t('кГц', 'kHz'),
                                   self.t('Ошибка', 'Error') if error else self.t('Проверен', 'Checked')])
            item.setData(0, Qt.UserRole, media['id'])
            for column in range(4):
                item.setToolTip(column, media['path'] + f"\n{media['codec']} · " +
                                (self.t('моно', 'mono') if media['channels'] == 1 else self.t('стерео', 'stereo')) +
                                ('\n' + self.error_text(error) if error else ''))
            if error:
                item.setForeground(3, QColor('#b14435'))
            self.library.addTopLevelItem(item)
            item.setSelected(media['id'] in selected)
        self.filter_library()

    def filter_library(self):
        query = self.search.text().casefold()
        for index in range(self.library.topLevelItemCount()):
            item = self.library.topLevelItem(index)
            item.setHidden(query not in (item.text(0) + item.toolTip(0)).casefold())

    def selected_media(self):
        return [self.store.media(item.data(0, Qt.UserRole)) for item in self.library.selectedItems()
                if not item.isHidden()]

    def add_selected(self):
        if self.running or self.worker:
            return
        for media in self.selected_media():
            error = availability(media)
            if error:
                self.notify(media['title'] + ': ' + self.error_text(error))
                continue
            self.queue.append(media['id'])
        self.queue_changed()

    def queue_changed(self):
        self.index = -1
        self.store.set_setting('queue', self.queue)
        self.refresh_queue()
        self.log('queue_edited', str(len(self.queue)))

    def refresh_queue(self):
        selected = self.queue_table.indexOfTopLevelItem(self.queue_table.currentItem())
        self.queue_table.blockSignals(True)
        self.queue_table.clear()
        total = 0
        durations = []
        for index, media_id in enumerate(self.queue):
            media = self.store.media(media_id)
            error = availability(media)
            title = media['title'] if media else self.t('Неизвестный файл', 'Unknown file')
            duration = media['duration_ms'] if media else 0
            total += duration
            durations.append(duration)
            state = self.t('Ошибка', 'Error') if error else ''
            if index == self.index:
                state = self.t('Сейчас', 'Current') if self.running else self.t('Последний', 'Last played')
            elif self.running and index == self.index + 1:
                state = self.t('Далее', 'Next')
            item = QTreeWidgetItem([f'{index + 1:02}   {title}', duration_text(duration), state])
            if error:
                item.setToolTip(0, self.error_text(error))
                item.setForeground(2, QColor('#b14435'))
            self.queue_table.addTopLevelItem(item)
        if 0 <= selected < len(self.queue):
            self.queue_table.setCurrentItem(self.queue_table.topLevelItem(selected))
        self.queue_table.blockSignals(False)
        overlap = round(self.crossfade.value() * 1000)
        total -= sum(min(overlap, a // 2, b // 2) for a, b in zip(durations, durations[1:]))
        self.total.setText(f'{len(self.queue)} · ' + ('≈ ' if overlap else '') + duration_text(total))
        self.total.setToolTip(self.t('Расчёт с учётом переходов; точное время определяется подготовленным звуком.',
                                     'Includes overlaps; exact timing is determined by prepared audio.'))
        self.update_transport()

    def move_item(self, delta):
        index = self.queue_table.indexOfTopLevelItem(self.queue_table.currentItem())
        if not self.running and index >= 0 and 0 <= index + delta < len(self.queue):
            self.queue[index], self.queue[index + delta] = self.queue[index + delta], self.queue[index]
            self.queue_changed()
            self.queue_table.setCurrentItem(self.queue_table.topLevelItem(index + delta))

    def remove_item(self):
        index = self.queue_table.indexOfTopLevelItem(self.queue_table.currentItem())
        if not self.running and index >= 0:
            self.queue.pop(index)
            self.queue_changed()

    def clear_queue(self):
        if not self.running and self.queue and QMessageBox.question(self, self.t('Очистить очередь', 'Clear queue'),
                self.t('Убрать все позиции из очереди? Файлы останутся в медиатеке.',
                       'Remove all queue items? Files will remain in the library.')) == QMessageBox.Yes:
            self.queue = []
            self.queue_changed()

    def refresh_playlists(self):
        self.playlists.clear()
        self.playlists.addItem(self.t('Сохранённые плейлисты…', 'Saved playlists…'), None)
        for name in self.store.playlists():
            self.playlists.addItem(name, name)

    def save_playlist(self):
        if not self.queue:
            return
        name, ok = QInputDialog.getText(self, self.t('Сохранить плейлист', 'Save playlist'), self.t('Название', 'Name'))
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.store.playlists() and QMessageBox.question(self, name,
                self.t('Заменить сохранённый плейлист?', 'Replace the saved playlist?')) != QMessageBox.Yes:
            return
        self.store.save_playlist(name, self.queue)
        self.refresh_playlists()
        self.playlists.setCurrentIndex(self.playlists.findData(name))
        self.log('playlist_saved', name)

    def load_playlist(self):
        name = self.playlists.currentData()
        if not self.running and not self.worker and name is not None:
            self.queue = self.store.playlist(name)
            self.queue_changed()
            self.log('playlist_loaded', name)

    def start_queue(self):
        if self.running or self.worker or not self.queue:
            return
        output = self.output.currentData()
        if output is None:
            self.notify(self.error_text('output_missing'))
            return
        index = self.queue_table.indexOfTopLevelItem(self.queue_table.currentItem())
        self.index = max(0, index)
        # Preflight every remaining entry so an already missing file is caught before start.
        for media_id in self.queue[self.index:]:
            media = self.store.media(media_id)
            error = availability(media)
            if error:
                self.notify((media['title'] + ': ' if media else '') + self.error_text(error))
                self.refresh_library()
                return
        if self.cue.active and self.cue.device_id == output:
            self.stop_cue()
        self.notice.hide()
        self.running = True
        self.generation += 1
        self.play_index()

    def play_index(self):
        self.last_started = None
        media = self.store.media(self.queue[self.index])
        self.refresh_queue()
        self.position_changed(0, media['duration_ms'] if media else 0)
        self.deck.start_queue([self.store.media(media_id) for media_id in self.queue],
                              self.index, self.output.currentData(),
                              round(self.crossfade.value() * 1000), self.stop_after.isChecked())

    def transition_setting_changed(self):
        self.store.set_setting('crossfade_ms', round(self.crossfade.value() * 1000))
        self.refresh_queue()

    def track_started(self, index):
        self.index = index
        self.log('started', self.deck.items[index]['title'])
        self.refresh_queue()

    def advance(self):
        if not self.running:
            return
        self.running = False
        self.refresh_queue()

    def skip(self):
        if not self.running:
            return
        self.log('skipped', self.deck.item['title'] if self.deck.item else '')
        self.deck.stop()
        self.generation += 1
        if self.index + 1 < len(self.queue):
            self.index += 1
            self.play_index()
        else:
            self.running = False
            self.update_transport()

    def stop_queue(self):
        was_running = self.running
        self.running = False
        self.generation += 1
        self.deck.stop()
        if was_running:
            self.log('stopped', self.deck.item['title'] if self.deck.item else '')
        self.refresh_queue()

    def playback_failed(self, origin, error):
        if origin == 'queue':
            self.running = False
            self.generation += 1
        message = self.error_text(error)
        self.notify(message)
        self.log('error', origin + ': ' + message)
        self.refresh_library()
        self.refresh_queue()
        self.update_cue()

    def update_transport(self):
        if not hasattr(self, 'play') or not hasattr(self, 'queue_table'):
            return
        active = self.running
        busy = bool(self.worker)
        self.play.setEnabled(bool(self.queue) and not active and not busy and self.output.currentData() is not None)
        self.pause.setEnabled(self.deck.state in ('playing', 'paused'))
        self.pause.setText(self.t('Продолжить', 'Resume') if self.deck.state == 'paused' else self.t('Пауза', 'Pause'))
        self.stop.setEnabled(active or self.deck.active)
        self.next_button.setEnabled(active and self.index + 1 < len(self.queue))
        self.output.setEnabled(not active)
        self.seek.setEnabled(self.deck.state in ('playing', 'paused') and self.deck.can_change_stop)
        self.stop_after.setEnabled(not active or self.deck.can_change_stop)
        self.crossfade.setEnabled(not active)
        preparation = {'ready': self.t('Следующий подготовлен', 'Next item prepared'),
                       'preparing': self.t('Готовится следующий…', 'Preparing next item…'),
                       'error': self.t('Следующий: ошибка подготовки', 'Next item: preparation failed'), '': ''}
        self.preload_status.setText(preparation[self.deck.next_state])
        for widget in (self.add_button, self.up_button, self.down_button, self.remove_button,
                       self.clear_button, self.load_button, self.playlists):
            widget.setEnabled(not active and not busy)
        for widget in (self.import_button, self.import_action):
            widget.setEnabled(not active and not busy and not self.cue.active)
        self.language.setEnabled(not active and not busy and not self.cue.active)
        state = {'stopped': self.t('ОСТАНОВЛЕН', 'STOPPED'), 'playing': self.t('ВОСПРОИЗВЕДЕНИЕ', 'PLAYING'),
                 'loading': self.t('ЗАГРУЗКА', 'LOADING'), 'paused': self.t('ПАУЗА', 'PAUSED'),
                 'error': self.t('ОШИБКА', 'ERROR')}
        self.state_label.setText(state[self.deck.state])
        index = self.index if self.index >= 0 else max(0, self.queue_table.indexOfTopLevelItem(self.queue_table.currentItem()))
        current = self.store.media(self.queue[index]) if index < len(self.queue) else None
        self.now.setText(current['title'] if current else self.t('Добавьте первый материал в очередь', 'Add the first item to the queue'))
        following = self.store.media(self.queue[index + 1]) if index + 1 < len(self.queue) else None
        self.next_label.setText(self.t('Далее: ', 'Next: ') + (following['title'] if following else '—'))

    def position_changed(self, position, duration):
        if not self.seek.isSliderDown():
            self.seek.setRange(0, max(0, duration))
            self.seek.setValue(position)
        self.elapsed.setText(duration_text(position))
        self.remaining.setText('−' + duration_text(max(0, duration - position)))

    def show_levels(self, left, right):
        if hasattr(self, 'meters'):
            for meter, level in zip(self.meters, (left, right)):
                meter.setValue(round(max(0, min(60, level + 60))))
                meter.setToolTip(f'{level:.1f} dBFS · ' + self.t('уровень смеси до регулятора громкости', 'mix level before volume control'))

    def preview_selected(self):
        selection = self.selected_media()
        if selection:
            self.preview(selection[0])
        else:
            self.notify(self.t('Выберите материал в медиатеке.', 'Select an item in the media library.'))

    def preview(self, media):
        if self.worker:
            return
        output = self.cue_output.currentData()
        if self.running and output == self.deck.device_id:
            self.notify(self.t('Подслушка и очередь используют один выход. Остановите очередь или выберите другой выход подслушки.',
                               'Preview and queue use the same output. Stop the queue or select a different preview output.'))
            return
        if output is None:
            self.notify(self.error_text('output_missing'))
            return
        self.notice.hide()
        if self.cue.start(media, output):
            self.log('cue_requested', media['title'])

    def stop_cue(self):
        was_active = self.cue.active
        self.cue.stop()
        if was_active:
            self.log('cue_stopped', self.cue.item['title'])

    def update_cue(self):
        if not hasattr(self, 'cue_status'):
            return
        self.cue_output.setEnabled(not self.cue.active)
        self.preview_button.setEnabled(self.cue_output.currentData() is not None and not self.worker)
        self.cue_stop.setEnabled(self.cue.active)
        if self.cue.active:
            prefix = self.t('Загрузка: ', 'Loading: ') if self.cue.state == 'loading' else self.t('Подслушка: ', 'Preview: ')
            self.cue_status.setText(prefix + self.cue.item['title'])
        else:
            self.cue_status.setText(self.t('Подслушка остановлена', 'Preview stopped'))
        if hasattr(self, 'jingle_buttons'):
            assigned = self.store.jingles()
            for slot, button in enumerate(self.jingle_buttons):
                button.setEnabled(not self.worker and (slot not in assigned or self.cue_output.currentData() is not None))
        self.update_transport()

    def cue_position(self, position, duration):
        if self.cue.item and self.cue.active:
            self.cue_status.setText(self.cue.item['title'] + f' · {duration_text(position)} / {duration_text(duration)}')

    def refresh_jingles(self):
        assigned = self.store.jingles()
        for slot, button in enumerate(self.jingle_buttons):
            media = self.store.media(assigned[slot]) if slot in assigned else None
            title = media['title'] if media else self.t('Назначить', 'Assign')
            button.setText(f'Ctrl+{slot + 1}\n' + (title[:20] + '…' if len(title) > 20 else title))
            button.setToolTip(title)

    def jingle(self, slot):
        assigned = self.store.jingles()
        if slot in assigned:
            self.preview(self.store.media(assigned[slot]))
        else:
            self.assign_jingle(slot)

    def assign_jingle(self, slot):
        selected = self.selected_media()
        if not selected:
            self.notify(self.t('Сначала выберите джингл в медиатеке.', 'First select a jingle in the library.'))
            return
        error = availability(selected[0])
        if error:
            self.notify(self.error_text(error))
            return
        self.store.assign_jingle(slot, selected[0]['id'])
        self.log('jingle_assigned', f'{slot + 1}: ' + selected[0]['title'])
        self.refresh_jingles()
        self.update_cue()

    def jingle_menu(self, slot, point):
        menu = QMenu(self)
        menu.addAction(self.t('Назначить выбранный материал', 'Assign selected item'), lambda: self.assign_jingle(slot))
        menu.addAction(self.t('Очистить кнопку', 'Clear pad'), lambda: self.clear_jingle(slot))
        menu.exec(self.jingle_buttons[slot].mapToGlobal(point))

    def clear_jingle(self, slot):
        self.store.assign_jingle(slot, None)
        self.refresh_jingles()
        self.update_cue()

    def notify(self, message):
        self.notice.setText(str(message))
        self.notice.show()

    def log(self, action, detail):
        self.store.event(action, detail)
        if hasattr(self, 'history'):
            self.refresh_history()

    def event_name(self, action):
        names = {
            'session_opened': ('Плеер открыт', 'Player opened'), 'imported': ('Файл проверен', 'File validated'),
            'rejected': ('Файл отклонён', 'File rejected'), 'queue_edited': ('Очередь изменена', 'Queue edited'),
            'playlist_saved': ('Плейлист сохранён', 'Playlist saved'), 'playlist_loaded': ('Плейлист открыт', 'Playlist loaded'),
            'started': ('Воспроизведение', 'Playback started'), 'completed': ('Завершён', 'Completed'),
            'stopped': ('Остановлен', 'Stopped'), 'skipped': ('Пропущен оператором', 'Skipped by operator'),
            'cue_requested': ('Запрошена подслушка', 'Preview requested'), 'cue_completed': ('Подслушка завершена', 'Preview completed'),
            'cue_stopped': ('Подслушка остановлена', 'Preview stopped'), 'jingle_assigned': ('Джингл назначен', 'Jingle assigned'),
            'error': ('Ошибка', 'Error'),
            'transition': ('Плавный переход', 'Crossfade'),
            'tail_interrupted': ('Хвост перехода прерван', 'Transition tail interrupted'),
        }
        return self.t(*names[action]) if action in names else action

    def refresh_history(self):
        self.history.clear()
        for event in self.store.events():
            when = datetime.fromisoformat(event['time']).astimezone().strftime('%d.%m %H:%M:%S')
            item = QTreeWidgetItem([self.event_name(event['action']) + ' · ' + event['detail'], when])
            item.setToolTip(0, event['detail'])
            self.history.addTopLevelItem(item)

    def export_events(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t('Сохранить журнал', 'Export history'),
            'atlas-player-history.txt', self.t('Текст', 'Text') + ' (*.txt)', options=QFileDialog.DontUseNativeDialog)
        if path:
            try:
                lines = [f"{e['time']}\t{self.event_name(e['action'])}\t{e['detail']}" for e in reversed(self.store.events(10000))]
                Path(path).write_text('\n'.join(lines), encoding='utf-8')
            except OSError as exc:
                self.notify(str(exc))

    def help(self):
        QMessageBox.information(self, 'ATLAS Broadcast Player', self.t(
            '1. Добавьте аудиофайлы и дождитесь проверки.\n2. Выберите материалы и нажмите «В очередь».\n'
            '3. Выберите локальный выход и нажмите «Старт». Старт начинается с выделенной строки.\n'
            '4. Для предварительного прослушивания выберите выход подслушки.\n'
            '5. Сохраните плейлист; назначьте джинглы из медиатеки.\n\n'
            'Перед стартом задайте плавный переход: 0 — без наложения, до 10 секунд — смешивание. '
            'Для коротких файлов переход ограничен половиной каждого файла. Следующий материал готовится заранее. '
            'Перемотка и «Стоп после текущего» временно недоступны во время перехода.\n\n'
            'Preview: локальная репетиция. '
            'Эфирное расписание, резерв, сетевой выход AES67 и интернет-вещание ещё не подключены.',
            '1. Import audio files and wait for validation.\n2. Select items and add them to the queue.\n'
            '3. Select a local output and press Start. Playback starts at the selected row.\n'
            '4. Select a preview output to audition library items.\n5. Save playlists and assign jingle pads.\n\n'
            'Before starting, set crossfade: 0 for no overlap, up to 10 seconds for mixing. '
            'Short files limit the overlap to half of each file. The next item is prepared in advance. '
            'Seek and Stop after current are temporarily unavailable during a transition.\n\n'
            'Preview: local rehearsal. '
            'On-air scheduling, fallback, AES67 output and Internet publishing are not connected yet.'))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.import_files(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.worker:
            self.close_pending = True
            self.cancel_validation()
            self.notify(self.t('Завершаю проверку файла и закрываю плеер…',
                               'Stopping file validation and closing the player…'))
            event.ignore()
            return
        if (self.running or self.cue.active) and QMessageBox.question(self, self.t('Закрыть плеер', 'Close player'),
                self.t('Остановить звук и закрыть плеер?', 'Stop audio and close the player?')) != QMessageBox.Yes:
            event.ignore()
            return
        self.stop_queue()
        self.stop_cue()
        self.deck.shutdown()
        self.store.set_setting('station', self.station.text().strip())
        self.devices.audioOutputsChanged.disconnect(self.refresh_outputs)
        QApplication.instance().removeTranslator(self.translator)
        self.store.close()
        event.accept()
