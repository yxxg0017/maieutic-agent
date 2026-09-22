"""PyInstaller 入口。冻结时以脚本方式运行，需要一个包外入口来保留包上下文。"""

from kel.main import main

if __name__ == "__main__":
    raise SystemExit(main())
