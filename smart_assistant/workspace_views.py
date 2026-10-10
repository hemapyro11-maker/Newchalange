"""Dedicated local browsing surfaces; navigation never submits a chat message."""
import pathlib
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QLineEdit,QPushButton,QTextBrowser,QComboBox
import brain
import sessions
from jarvis_dashboard import read_state


class WorkspaceView(QWidget):
    def __init__(self, desktop, section):
        super().__init__();self.desktop=desktop;self.section=section
        body=QVBoxLayout(self);body.setContentsMargins(24,24,24,24)
        titles={'tools':('Tools & skills','الأدوات والمهارات'),'tasks':('Tasks & scheduled work','المهام والجدولة'),'projects':('Projects & files','المشاريع والملفات'),'connectors':('Connectors','المنصات المتصلة'),'chats':('Conversations','المحادثات')}
        title=QLabel(desktop.tr_pair(*titles[section]));title.setObjectName('workspaceTitle');body.addWidget(title)
        self.search=QLineEdit();self.search.setPlaceholderText(desktop.tr_pair('Filter this list…','ابحث في القائمة…'));self.search.textChanged.connect(self.filter);body.addWidget(self.search)
        self.list=QListWidget();self.list.itemClicked.connect(self.describe);body.addWidget(self.list,2)
        self.detail=QTextBrowser();self.detail.setOpenExternalLinks(False);self.detail.setMaximumHeight(150);body.addWidget(self.detail)
        self.action=QPushButton(desktop.tr_pair('Open selected conversation','افتح المحادثة') if section=='chats' else desktop.tr_pair('Prepare in a new conversation','جهّز في محادثة جديدة'))
        self.action.clicked.connect(self.open_selected);body.addWidget(self.action)
        self.list.itemDoubleClicked.connect(lambda _:self.open_selected())

    def refresh(self):
        selected=self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
        self.list.clear();d=self.desktop;rows=[]
        if self.section=='chats':
            rows=[(s['title'],s['id'],f"{s['turns']} messages · {s['updated']}") for s in sessions.list_all()]
        elif self.section=='tools':
            rows=[(c.name,c.name+' ',c.description) for c in d.engine.registry.list_commands()]
        elif self.section=='projects':
            rows=[(str(d.engine.project_dir),'project ',d.tr_pair('Current project. Choose another folder using the project command.','المشروع الحالي. استخدم أمر project لاختيار مجلد آخر.'))]
            rows += [(self.desktop.sources.item(i).text(),'',self.desktop.sources.item(i).text()) for i in range(self.desktop.sources.count())]
        elif self.section=='tasks':
            data=read_state(brain._base_dir()/'todo.json',[])
            if isinstance(data,list):rows += [(('✓ ' if t.get('done') else '○ ')+str(t.get('text','')),f"todo done {t.get('id')}",str(t.get('text',''))) for t in data if isinstance(t,dict)]
            schedule=read_state(brain._base_dir()/'schedule.json',{})
            if isinstance(schedule,dict):rows += [(str(j.get('command','')), 'schedule list',str(j.get('next_run',''))) for j in schedule.get('jobs',[]) if isinstance(j,dict)]
        elif self.section=='connectors':
            from plugins.connectors_plugin import CONNECTOR_CATALOG
            configured=read_state(brain._base_dir()/'connectors.json',{})
            for name,meta in CONNECTOR_CATALOG.items():
                rows.append((name,'connectors add '+name,meta['description']+'\n'+d.tr_pair('Setup required; this list does not imply an active connection.','يلزم إعداد الاتصال؛ ظهور المنصة هنا لا يعني أنها متصلة.')))
        for title,value,description in rows:
            item=QListWidgetItem(title);item.setData(Qt.ItemDataRole.UserRole,value);item.setData(Qt.ItemDataRole.UserRole+1,description);item.setToolTip(description);self.list.addItem(item)
            if value==selected:self.list.setCurrentItem(item)
        self.detail.setPlainText(d.tr_pair('Select an item to see its details.','اختار عنصر لعرض التفاصيل.') if rows else d.tr_pair('Nothing here yet.','القائمة فاضية حاليًا.'))
        self.filter(self.search.text())

    def filter(self,text):
        for i in range(self.list.count()):
            item=self.list.item(i);item.setHidden(text.casefold() not in (item.text()+' '+str(item.data(Qt.ItemDataRole.UserRole+1))).casefold())

    def describe(self,item):
        self.detail.setPlainText(str(item.data(Qt.ItemDataRole.UserRole+1)))

    def open_selected(self):
        item=self.list.currentItem()
        if not item:return
        if self.section=='chats':self.desktop.resume(item)
        else:
            value=item.data(Qt.ItemDataRole.UserRole)
            if value:self.desktop.new_chat();self.desktop.seed(value)
