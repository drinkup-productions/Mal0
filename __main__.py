from malo.core import runtime
from malo.ui.kivy.app import ChatApp


def main():
    rt = runtime.Runtime()
    ChatApp(rt).run()


if __name__ == "__main__":
    main()