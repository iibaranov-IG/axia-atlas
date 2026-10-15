"""Explicit multi-source subscriptions with sustained, transition-based alarms."""
from localization import tr
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTreeWidget, QTreeWidgetItem, QLabel, QDoubleSpinBox)
from audio_monitor import AudioReceiver


class AlarmState:
    def __init__(self):
        self.since = {}
        self.active = set()

    def update(self, conditions, now, hold):
        active = set()
        for name, condition in conditions.items():
            if condition:
                self.since.setdefault(name, now)
                if now - self.since[name] >= hold:
                    active.add(name)
            else:
                self.since.pop(name, None)
        started, cleared = active - self.active, self.active - active
        self.active = active
        return started, cleared


class MultiHealthPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.watch = {}
        layout = QVBoxLayout(self)
        heading = QLabel(tr('Watch up to 8 selected sources · explicit subscriptions · alarms recorded in Events'))
        heading.setWordWrap(True)
        layout.addWidget(heading)
        row = QHBoxLayout()
        self.add = QPushButton(tr('Watch Selected Audio Source'))
        self.remove = QPushButton(tr('Remove Selected Watch'))
        self.stop = QPushButton(tr('Stop All Watches'))
        self.add.clicked.connect(self.add_selected)
        self.remove.clicked.connect(self.remove_selected)
        self.stop.clicked.connect(self.stop_all)
        for button in (self.add, self.remove, self.stop):
            row.addWidget(button)
        layout.addLayout(row)
        self.thresholds = {}
        row = QHBoxLayout()
        for name, label, minimum, maximum, default in (
            ('silence', 'Silence below dBFS', -100, -10, -60),
            ('clip', 'Overload above dBFS', -10, 0, -.1),
            ('loss', 'Gap threshold %', .1, 100, 1),
            ('hold', 'Hold seconds', .5, 120, 3)):
            if name == 'loss':
                layout.addLayout(row)
                row = QHBoxLayout()
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setValue(atlas.settings.value('health_' + name, default, type=float))
            spin.valueChanged.connect(lambda value, key=name: self.set_threshold(key, value))
            self.thresholds[name] = spin
            row.addWidget(QLabel(tr(label)))
            row.addWidget(spin)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([tr('Channel / Source'), tr('IP'), tr('State'), tr('L / R dBFS'), tr('Recent gaps %')])
        layout.addWidget(self.tree)
        self.status = QLabel(tr('Stopped. Selecting a channel does not start a watch.'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    def set_threshold(self, name, value):
        self.atlas.settings.setValue('health_' + name, value)
        for entry in self.watch.values():
            entry['alarms'] = AlarmState()
        self.atlas.record('Health threshold changed: ' + name + ' = ' + str(value))

    def add_selected(self):
        if not self.atlas.access.allowed('audio') or not self.atlas.access.allowed('diagnostics'):
            return
        source = self.atlas.player.source
        if not source or not source.get('channel') or source.get('enabled') is False or source.get('channels', 2) != 2:
            self.status.setText(tr('Select an enabled stereo source in Audio first.'))
            return
        interface = self.atlas.interface_objects.get(self.atlas.interfaces.currentData())
        if not interface:
            self.status.setText(tr('Select the broadcast network adapter first.'))
            return
        key = source['ip'], source['multicast']
        if key in self.watch:
            self.status.setText(tr('This source is already monitored.'))
            return
        if len(self.watch) >= 8:
            self.status.setText(tr('Eight-source limit reached. Remove a watch first.'))
            return
        receiver = AudioReceiver(source, interface.index())
        item = QTreeWidgetItem([f'{source["channel"]} · {source.get("name", "")}', source['ip'], 'Starting'])
        self.tree.addTopLevelItem(item)
        self.watch[key] = dict(receiver=receiver, item=item, alarms=AlarmState(),
                               packets=0, gaps=0, recent=[], started=time.monotonic())
        receiver.start()
        self.timer.start()
        self.status.setText(tr('{v0} active watches. Watches stop on sign-out and application exit.', v0=len(self.watch)))
        self.atlas.record(f'Health watch started: {source["channel"]}', ip=source['ip'])

    def tick(self):
        now = time.monotonic()
        if not self.atlas.access.allowed('audio') or not self.atlas.access.allowed('diagnostics'):
            self.stop_all()
            return
        for entry in self.watch.values():
            receiver = entry['receiver']
            b = receiver.buffer
            with b.lock:
                packets, gaps, last, error = b.packets, b.gaps, b.last_packet, b.error
                left, right = b.window_left, b.window_right
                b.window_left = b.window_right = -100.0
                b.pcm.clear()
            entry['recent'].append((now, packets - entry['packets'], gaps - entry['gaps']))
            entry['packets'], entry['gaps'] = packets, gaps
            entry['recent'] = [r for r in entry['recent'] if now - r[0] <= 2]
            rp = sum(r[1] for r in entry['recent'])
            rg = sum(r[2] for r in entry['recent'])
            loss = 100 * rg / max(1, rp + rg)
            receiving = bool(last and now - last < .5)
            got_audio = entry['recent'][-1][1] > 0
            conditions = {'No stream': not receiving, 'Receiver error': bool(error),
                'Silence': receiving and got_audio and max(left, right) < self.thresholds['silence'].value(),
                'Overload': receiving and got_audio and max(left, right) >= self.thresholds['clip'].value(),
                'Packet gaps': receiving and loss >= self.thresholds['loss'].value()}
            started, cleared = entry['alarms'].update(conditions, now, self.thresholds['hold'].value())
            for alarm in sorted(started):
                self.atlas.record(f'Health alarm: channel {receiver.source["channel"]} · {alarm}', severity='Warning', ip=receiver.source['ip'])
            for alarm in sorted(cleared):
                self.atlas.record(f'Health recovered: channel {receiver.source["channel"]} · {alarm}', ip=receiver.source['ip'])
            entry['item'].setText(2, error or ', '.join(sorted(entry['alarms'].active)) or ('Receiving' if receiving else 'Waiting'))
            entry['item'].setText(3, f'{left:.1f} / {right:.1f}' if got_audio else 'Not measured')
            entry['item'].setText(4, f'{loss:.2f}' if rp + rg else 'Not measured')

    def remove_selected(self):
        item = self.tree.currentItem()
        for key, entry in list(self.watch.items()):
            if entry['item'] is item:
                self.stop_entry(key)

    def stop_entry(self, key):
        entry = self.watch.pop(key)
        receiver = entry['receiver']
        receiver.requestInterruption()
        receiver.wait()
        receiver.deleteLater()
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(entry['item']))
        self.atlas.record(f'Health watch stopped: channel {receiver.source["channel"]}', ip=receiver.source['ip'])
        if not self.watch:
            self.timer.stop()
            self.status.setText(tr('All watches stopped.'))

    def stop_all(self):
        for key in list(self.watch):
            self.stop_entry(key)
