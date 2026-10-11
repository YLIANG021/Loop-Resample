# 👉 Loop Resample 👈

### 快速改段数，保留属性

在编辑模式里选中连续边，右键打开 **Loop Resample**，滚轮控制段数，网格实时调整。改完不用重新拆 UV、不用重新刷权重——UV、接缝、顶点色这些都会保留。

## ✨ 能干什么

- 🖱️ **快速调节**：滚轮快速改段数，左键确认、右键取消。
- 🔗 **兼容性好**：三角面，开口链、闭合圈、极点、单弧都能重构，各种网格都支持，兼容性好
- 🌊 **顺滑曲线**：按住 `Shift` 滚轮能把曲线抛光。
- 📏 **均匀布线**：按住 `Ctrl` 滚轮能快速让点等间距。
- 🧲 **属性保留**：UV、接缝、硬边、折痕/倒角权重、顶点色、顶点组权重尽量帮你保留


## 📍 在哪找它

进入编辑模式，选中要改的边，然后 `右键` 就能看到 **Loop Resample**。

支持语言：English、简体中文、繁體中文、日本語、한국어、Deutsch、Français、Español、Italiano、Polski、Português、Русский、Tiếng Việt。

---

## 1. 线段直接改

选中边，滚轮改段数。两头不动，中间重新划分，模型布线不够好也支持

<img width="908" height="540" alt="1" src="https://github.com/user-attachments/assets/2b9ec61a-bd0d-4d2e-8e20-5796dee2ceca" />




## 2. 圆环也能改

闭合的边也支持

<img width="908" height="540" alt="2" src="https://github.com/user-attachments/assets/6329d5dc-444d-4cdd-b668-93e5b5b95ea6" />

## 3. 同时改几根

多选几根边链，滚轮一滚一起改段数

<img width="908" height="540" alt="3" src="https://github.com/user-attachments/assets/5200a5be-bebd-43bf-aac3-ead4cf5d3d24" />




## 4. Shift + 滚轮：顺手把曲线捋顺

按住 Shift 调整滚轮，快速抛光你的曲线

<img width="908" height="540" alt="4" src="https://github.com/user-attachments/assets/5c6fc478-74f6-429e-a7ed-070243e6dd48" />


## 5. Ctrl + 滚轮：把点摊匀

按住 Ctrl 调整滚轮，把曲线变得均匀

<img width="908" height="540" alt="5" src="https://github.com/user-attachments/assets/9c7eeca8-1cc6-4c19-94e1-96e80ea370a7" />


---

## ⌨️ 常用操作

| 操作 | 作用 |
| --- | --- |
| 滚轮 | 加 / 减段数 |
| Shift + 滚轮 | 平滑曲线 |
| Ctrl + 滚轮 | 均分间距 |
| 左键 | 确认操作 |
| 右键 | 取消操作 |


## 🧩 属性怎么处理

UV、接缝、硬边、折痕和倒角权重、顶点颜色、顶点组权重，都会尽量按原来的位置算到新的顶点和边上。

（注：形态键 Shape Key、自定义属性层、皮肤标记 Skin 暂不支持处理。）

## ⚙️ 系统要求

Blender 4.2.0 或更高版本

## 📄 License

GNU General Public License v3.0 or later
