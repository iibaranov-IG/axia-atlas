"""Operator UI for a local roster; identities are entered by administrators."""
from localization import tr
from datetime import date, timedelta
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QDateEdit,QTableWidget,QTableWidgetItem,QMessageBox,QInputDialog)
from duty_roster import DutyRoster, MOSCOW
from datetime import datetime


class DutyPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas=atlas
        self.store=atlas.roster
        layout=QVBoxLayout(self)
        self.info=QLabel(tr('Duty roster · local workstation · vacation dates are inclusive'))
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.calendar=QTableWidget(0,3)
        self.calendar.setHorizontalHeaderLabels([tr('Date'),tr('Scheduled engineer'),tr('Status')])
        self.calendar.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.calendar)
        row=QHBoxLayout()
        self.person=QComboBox();row.addWidget(self.person)
        self.first=QDateEdit(QDate.currentDate()); self.first.setCalendarPopup(True)
        self.last=QDateEdit(QDate.currentDate()); self.last.setCalendarPopup(True)
        for widget in (self.first,self.last): widget.setDisplayFormat('yyyy-MM-dd');row.addWidget(widget)
        layout.addLayout(row)
        actions=QHBoxLayout()
        add=QPushButton(tr('Save Vacation'));add.clicked.connect(self.add_leave);actions.addWidget(add)
        replace=QPushButton(tr('Assign Replacement for Start Date'));replace.clicked.connect(self.replace);actions.addWidget(replace)
        layout.addLayout(actions)
        self.leaves=QComboBox();layout.addWidget(self.leaves)
        cancel=QPushButton(tr('Cancel Selected Vacation'));cancel.clicked.connect(self.cancel_leave);layout.addWidget(cancel)
        configure=QPushButton(tr('Configure Rotation…'));configure.clicked.connect(self.configure);layout.addWidget(configure)
        refresh=QPushButton(tr('Refresh'));refresh.clicked.connect(self.refresh);layout.addWidget(refresh)
        self.edit_buttons=(add,replace,cancel,configure)
        self.refresh()

    def permitted(self):
        if not self.atlas.access.allowed('roster_edit'):
            self.info.setText(tr('Access denied: duty roster editing'))
            return False
        return True

    def actor(self):
        user=self.atlas.access.user
        return user['name'] if user else 'Local setup'

    def refresh(self):
        if not self.atlas.access.allowed('roster_view'):
            self.calendar.setRowCount(0);self.person.clear();self.leaves.clear();self.setEnabled(False);return
        config=self.store.config()
        previous=self.person.currentText();self.person.clear()
        self.person.addItems(config['cycle'] if config else [])
        if previous:self.person.setCurrentText(previous)
        self.leaves.clear()
        for entry in self.store.vacations():
            self.leaves.addItem(f"{entry['person']}: {entry['first']} — {entry['last']}",entry['id'])
        self.calendar.setRowCount(14 if config else 0)
        today=datetime.now(MOSCOW).date()
        for i in range(self.calendar.rowCount()):
            entry=self.store.duty(today+timedelta(days=i))
            status='On vacation — replacement required' if entry['on_leave'] else 'Replacement assigned' if entry['replacement'] else 'Rotation'
            for col,value in enumerate((entry['day'],entry['person'],status)):
                self.calendar.setItem(i,col,QTableWidgetItem(value))
        self.calendar.resizeColumnsToContents()
        for button in self.edit_buttons:button.setEnabled(self.atlas.access.allowed('roster_edit'))
        self.info.setText((((tr('Saved on this workstation · Handover: ') + str(config['handover'] or 'not set')) + tr(' Moscow')) if config else tr('Rotation has not been configured.')))

    def add_leave(self):
        if not self.permitted():return
        try:
            self.store.add_vacation(self.person.currentText(),self.first.date().toString('yyyy-MM-dd'),self.last.date().toString('yyyy-MM-dd'),self.actor())
            self.refresh()
        except (ValueError,OSError) as exc:self.info.setText(str(exc))

    def cancel_leave(self):
        if not self.permitted() or self.leaves.currentData() is None:return
        if QMessageBox.question(self,tr('Cancel Vacation'),tr('Cancel this vacation entry? The audit history is retained.'))!=QMessageBox.Yes:return
        self.store.cancel_vacation(self.leaves.currentData(),self.actor());self.refresh()

    def replace(self):
        if not self.permitted():return
        day=self.first.date().toString('yyyy-MM-dd');person=self.person.currentText()
        if QMessageBox.question(self,tr('Assign Replacement'),tr('{v0}: assign {v1}? The rotation on other dates stays unchanged.', v0=day, v1=person))!=QMessageBox.Yes:return
        try:self.store.replace(day,person,self.actor());self.refresh()
        except ValueError as exc:self.info.setText(str(exc))

    def configure(self):
        if not self.permitted():return
        old=self.store.config()
        text,ok=QInputDialog.getMultiLineText(self,'Rotation','One staff name per line, in rotation order:', '\n'.join(old['cycle']) if old else '')
        if not ok:return
        anchor,ok=QInputDialog.getText(self,tr('Rotation'),tr('Date on which the first person starts (YYYY-MM-DD):'),text=old['anchor'] if old else date.today().isoformat())
        if not ok:return
        handover,ok=QInputDialog.getText(self,tr('Rotation'),tr('Handover time in Moscow (HH:MM):'),text=old['handover'] or '' if old else '')
        if not ok:return
        try:self.store.configure(text.splitlines(),anchor,handover,actor=self.actor(),expected=old);self.refresh()
        except ValueError as exc:self.info.setText(str(exc))
