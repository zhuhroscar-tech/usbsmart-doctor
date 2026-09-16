# usbsmart-doctor

[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

为 USB 外接硬盘或 SSD 找到可用的 `smartctl` 设备类型，并汇总 SMART 健康信息。这个 Linux CLI 会在自动识别失败时尝试不同 USB 桥接类型，也可以记住成功的类型，供后续检查使用。

![SMART 报告示例](docs/images/example-output.png)

## 环境要求与安装

需要 Linux、Python 3.9+，以及 PATH 中可用的 `smartmontools` / `smartctl`。读取 SMART 通常需要较高权限；Python 运行时代码仅使用标准库。

```bash
# Debian/Ubuntu；其他发行版请使用对应包管理器
sudo apt install smartmontools
git clone https://github.com/zhuhroscar-tech/usbsmart-doctor.git
cd usbsmart-doctor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
usbsmart-doctor --help
```

[GitHub Releases](https://github.com/zhuhroscar-tech/usbsmart-doctor/releases) 也提供独立 `.pyz`。下载前请确认对应 release 的附件；从源码安装不依赖 PyPI 发布状态。

## 使用方法

把 `/dev/sdb` 换成已确认的目标磁盘路径，不要凭猜测选择设备。

```bash
usbsmart-doctor /dev/sdb
usbsmart-doctor /dev/sdb --json
usbsmart-doctor /dev/sdb --type sat
usbsmart-doctor /dev/sdb --no-cache
```

如果设备权限要求 root，可在仓库目录显式调用虚拟环境内的程序：`sudo .venv/bin/usbsmart-doctor /dev/sdb`。

报告展示设备能够提供的温度、扇区、磨损和自检状态。`--type` 跳过常规候选类型列表；`--no-cache` 禁用缓存读写。

| 退出码 | 含义 |
| --- | --- |
| `0` | 检查项未报告警告，不代表磁盘一定健康 |
| `1` | 没有找到可用的设备类型 |
| `2` | 找不到 `smartctl` |
| `3` | SMART 总体健康自评失败 |
| `4` | 存在其他警告 |

## 安全与隐私

工具只发出读取命令，不向磁盘写入数据，也不启动自检；不会发起网络请求。不支持的桥接芯片或缺失的 SMART 字段仍可能影响诊断。无论报告如何，都应保持备份。

可选缓存位于 `~/.cache/usbsmart-doctor/known_bridges.json`，在信息可用时按 USB 身份记录类型。报告可能含硬盘序列号，分享前请脱敏；删除缓存即可清除记忆的类型。

## 开发

```bash
pip install -e ".[dev]"
pytest -v
```

测试覆盖解析及模拟探测，不代表所有实体硬盘盒都已验证。[MIT 许可证](LICENSE)。
