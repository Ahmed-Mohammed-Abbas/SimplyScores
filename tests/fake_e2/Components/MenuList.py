from enigma import eListboxPythonStringContent
from Components.GUIComponent import GUIComponent


class MenuList(GUIComponent):
    def __init__(self, list, enableWrapAround=True, content=eListboxPythonStringContent):
        GUIComponent.__init__(self)
        self.list = list
        self.l = content()
        self.index = 0

    def setList(self, lst):
        self.list = lst
        self.l.setList(lst)
        if self.index >= len(lst):
            self.index = max(0, len(lst) - 1)

    def getCurrent(self):
        return self.list[self.index] if self.list else None

    def getSelectionIndex(self):
        return self.index

    def moveToIndex(self, i):
        self.index = i
