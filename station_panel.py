from localization import tr
from PySide6.QtCore import Qt,QUrl
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QComboBox,QTreeWidget,QTreeWidgetItem,QPlainTextEdit,QLabel,QHeaderView


class StationPanel(QWidget):
    def __init__(self,host):
        super().__init__(host)
        self.host=host
        layout=QVBoxLayout(self)
        self.kind=QComboBox();self.kind.addItems([tr(v) for v in ['Station','Cities & Frequencies','Satellite','Podcasts & Online','Applications']]);layout.addWidget(self.kind)
        self.query=QLineEdit();self.query.setPlaceholderText(tr('Find a city or satellite…'));layout.addWidget(self.query)
        self.table=QTreeWidget();self.table.setHeaderLabels([tr('Name'),tr('Published frequency / status')]);self.table.header().setSectionResizeMode(QHeaderView.Stretch);layout.addWidget(self.table)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail)
        self.kind.currentIndexChanged.connect(self.refresh);self.query.textChanged.connect(self.refresh)
        self.table.currentItemChanged.connect(self.show_row)
        self.refresh()

    def refresh(self,*_):
        self.table.clear();self.detail.clear()
        if not self.host.access_allowed('library'):return
        store=self.host.station
        if not store.data:self.detail.setPlainText(tr('Station reference is not installed.'));return
        if self.kind.currentIndex()==0:
            self.detail.setPlainText(((store.summary() + tr('\n\nChecked: ')) + store.data['checked_at']));return
        if self.kind.currentIndex()>=3:
            apps=self.kind.currentIndex()==4
            for row in store.data.get('apps' if apps else 'digital',[]):
                if self.query.text().casefold() not in (row['name']+' '+row.get('note','')+' '+row.get('reported_status','')).casefold():continue
                status=('Engineer: '+row['reported_status']+' · '+row['note']) if apps else row['status']
                item=QTreeWidgetItem([row['name'],status]);item.setData(0,Qt.UserRole,store.app_text(row) if apps else store.digital_text(row));self.table.addTopLevelItem(item)
            if self.table.topLevelItemCount():self.table.setCurrentItem(self.table.topLevelItem(0))
            return
        cities=self.kind.currentIndex()==1
        for row in store.data['cities' if cities else 'satellites']:
            name=row['city' if cities else 'name']
            if self.query.text().casefold() not in name.casefold():continue
            if cities:
                values=sorted({(o['frequency_mhz']+' MHz FM') if o['frequency_mhz'] else o['mode'] for o in row['observations']})
                status=' / '.join(values)+(' · CONFLICT' if row['conflict'] else '')
                if row.get('engineer_correction'):
                    status=row['engineer_correction']['frequency_mhz']+' MHz FM · Engineer correction; website differs'
                body=store.city_text(row)
            else:
                status='CONFLICT — review sources' if row['conflicting_fields'] else 'Source data · reception not verified'
                body=store.satellite_text(row)
            item=QTreeWidgetItem([name,status]);item.setData(0,Qt.UserRole,body+'\n\nChecked: '+store.data['checked_at']);self.table.addTopLevelItem(item)
        if self.table.topLevelItemCount():self.table.setCurrentItem(self.table.topLevelItem(0))

    def show_row(self,item,*_):
        if item:self.detail.setPlainText(item.data(0,Qt.UserRole))
