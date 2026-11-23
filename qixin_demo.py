"""双击演示入口；等价的命令是 python -m qixin --demo。"""

import sys

from qixin.app import main


if __name__ == "__main__":
    sys.argv.append("--demo")
    main()
