"""Plain-text messenger layout. Message contents never become HTML or commands."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QScrollArea,QWidget,QVBoxLayout,QHBoxLayout,QFrame,QLabel,QSizePolicy


from localization import tr

class ChatView(QScrollArea):
    answer_added=Signal(str,str)
    cleared=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName("engineerChat")
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAccessibleName('Переписка')
        self.content=QWidget()
        self.content.setObjectName("chatSurface")
        self.stack=QVBoxLayout(self.content)
        self.stack.setContentsMargins(8,10,8,10)
        self.stack.setSpacing(10)
        self.welcome=QLabel(tr('What shall we check?')+'\n\n'+tr('Who is on duty?')+'\n'+tr('How can I check audio packet loss?'))
        self.welcome.setObjectName('chatWelcome')
        self.welcome.setWordWrap(True)
        self.welcome.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.welcome)
        self.stack.addStretch(1)
        self.setWidget(self.content)
        self.messages=[]
        self.rows=[]
        self.follow_bottom=True
        self.scroll_timer=QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_if_following)
        self.verticalScrollBar().rangeChanged.connect(self.scroll_if_following)

    def scroll_if_following(self,*_):
        if self.follow_bottom:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def appendPlainText(self,text):
        role='notice';body=text
        for prefix,candidate in [('You: ','user'),('Assistant: ','assistant'),('Виртуальный инженер: ','assistant')]:
            if text.startswith(prefix):
                role=candidate;body=text[len(prefix):];break
        self.add_message(role,body,original=text)

    def add_message(self,role,text,original=None):
        if role not in ('user','assistant','notice'):
            raise ValueError('Unknown conversation role')
        self.welcome.hide()
        scroll=self.verticalScrollBar()
        self.follow_bottom=scroll.maximum()-scroll.value()<30
        row=QWidget()
        line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0)
        bubble=QFrame()
        bubble.setObjectName('messageBubble')
        bubble.setProperty('speaker',role)
        parts=QVBoxLayout(bubble);parts.setContentsMargins(11,8,11,10);parts.setSpacing(5)
        label=QLabel(text if role!='assistant' or len(text)<900 else text[:240]+'…')
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        parts.addWidget(label)
        question = next((r[2].text() for r in reversed(self.rows) if r[3]=='user'), '')
        if role=='user':line.addStretch(1)
        line.addWidget(bubble,0,Qt.AlignTop)
        if role!='user':line.addStretch(1)
        self.stack.insertWidget(self.stack.count()-1,row)
        self.rows.append((row,bubble,label,role))
        self.messages.append(original if original is not None else text)
        self.resize_bubbles()
        if role=='assistant':self.answer_added.emit(question,text)
        self.scroll_timer.start(0)

    def resize_bubbles(self):
        width=max(60,min(520,int((self.viewport().width()-16)*.84)))
        for _,bubble,_,_ in self.rows:
            bubble.setFixedWidth(width)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.resize_bubbles()

    def toPlainText(self):
        return '\n'.join(self.messages)

    def clear(self):
        self.scroll_timer.stop()
        for row,_,_,_ in self.rows:
            self.stack.removeWidget(row)
            row.deleteLater()
        self.rows.clear();self.messages.clear()
        self.welcome.show()
        self.cleared.emit()
        self.follow_bottom=True
