# 第三方组件许可声明

本仓库（AutoGameTool）**自有代码**以 [MIT License](LICENSE) 发布。

但发行版 `AutoGameTool-Setup.exe` / `AutoGameTool.exe` 中**打包了若干第三方组件**，它们各自遵循自己的许可协议，不因本项目采用 MIT 而改变。以下列出实际打包进发行版的组件及其许可。

> 版本号取自实际构建环境（2026-09 实测）。

---

## 一、打包进发行版的组件

### ⚠️ 需要特别注意的

| 组件 | 版本 | 许可 | 说明 |
|---|---|---|---|
| **pynput** | 1.8.2 | **LGPL-3.0** | 唯一非宽松许可的运行时依赖，义务见下文 |

### 宽松许可（MIT / BSD / Apache）

| 组件 | 版本 | 许可 |
|---|---|---|
| OpenCV（opencv-python） | 5.0.0.93 | Apache-2.0 |
| NumPy | 2.5.3 | BSD-3-Clause（含 0BSD / MIT / Zlib / CC0-1.0 等子组件） |
| FastAPI | 0.141.1 | MIT |
| Starlette | 1.6.0 | BSD-3-Clause |
| Uvicorn | 0.52.4 | BSD-3-Clause |
| Pydantic | 2.13.5 | MIT |
| websockets | 17.1 | BSD-3-Clause |
| anyio | — | MIT |
| mss | 10.2.0 | MIT |
| CPython / Python 标准库 | 3.13.x | PSF-2.0 |

### 构建工具（用于生成发行版，不作为运行时组件打包）

| 工具 | 版本 | 许可 |
|---|---|---|
| PyInstaller | 6.22.2 | GPL-2.0-or-later，**含 Bootloader Exception**——明确允许用它打包采用其他许可的程序 |
| NSIS | 3.10 | zlib/libpng（用其生成的安装包不构成对 NSIS 本身的再分发） |
| Pillow | 12.3.0 | MIT-CMU（仅 `tools/make_icon.py` 生成图标时使用） |

---

## 二、LGPL 义务（pynput）

`pynput` 采用 **GNU Lesser General Public License v3.0**。以库的形式随程序一起分发是被允许的，但需要满足：

1. **提供许可证全文**，并声明该组件名称与版本（见上表）；
2. **允许用户替换该库**——用户应能把 `pynput` 换成自己修改/重新编译的版本，并使其继续生效；
3. 若修改了 `pynput` 本身，需按 LGPL 公开相应修改部分。

> 合规提示：PyInstaller `--onefile` 会把所有依赖压进单个 exe，用户替换其中的 `pynput` 并不方便。若对合规性要求较高（尤其是商用分发），建议改用 `--onedir` 打包，让 `pynput` 以独立文件形式暴露在外，便于替换。

---

## 三、前端依赖（已编译进前端 bundle）

全部为 MIT / Apache-2.0：

| 组件 | 版本 | 许可 |
|---|---|---|
| Vue | 3.5.42 | MIT |
| Naive UI | 2.45.3 | MIT |
| Vue Flow（@vue-flow/core · background · controls） | 1.48.2 · 1.3.2 · 1.1.3 | MIT |
| Pinia | 3.0.4 | MIT |
| Vue Router | 4.6.4 | MIT |
| Vite | 6.4.3 | MIT |
| TypeScript | 5.6.3 | Apache-2.0 |

---

## 四、已声明但**未**打包的依赖

`engine/requirements.txt` 中列出了 OCR 相关依赖，但当前版本**尚未实现 OCR 节点**，因此 PyInstaller 不会把它们打进发行版：

| 组件 | 版本 | 许可 |
|---|---|---|
| rapidocr_onnxruntime | 1.2.3 | Apache-2.0 |
| onnxruntime | 1.29.0 | MIT |

一旦接入 OCR 节点，它们就会被打包进发行版，届时请把它们移入第一节。

---

## 五、免责

本文件仅出于合规说明目的整理，**不构成法律意见**。若需商用分发，建议自行复核上述各组件的许可原文。
