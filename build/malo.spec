a = Analysis(["../malo/__main__.py"], pathex=[".."], datas=[("../assets", "assets")],
             hiddenimports=["PIL._tkinter_finder", "pystray._win32"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="MalO", console=False,
          icon="../assets/malo.ico")
		  