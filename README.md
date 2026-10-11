# 👉 Loop Resample 👈

### Quickly adjust segment counts while preserving attributes

In Edit Mode, select connected edges, right-click to open **Loop Resample**, then use the mouse wheel to control the segment count. The mesh updates in real time. No need to unwrap UVs or repaint weights after editing—UVs, seams, vertex colors, and more are preserved.

## ✨ What It Can Do

- 🖱️ **Quick adjustment**: Use the mouse wheel to change the segment count. Left-click to confirm or right-click to cancel.
- 🔗 **Broad compatibility**: Rebuild triangle faces, open chains, closed loops, poles, and single arcs. It supports a wide range of mesh layouts.
- 🌊 **Smooth curves**: Hold `Shift` while scrolling to smooth the curve.
- 📏 **Even spacing**: Hold `Ctrl` while scrolling to quickly distribute points evenly.
- 🧲 **Attribute preservation**: UVs, seams, sharp edges, crease/bevel weights, vertex colors, and vertex group weights are preserved whenever possible.

## 📍 Where to Find It

Enter Edit Mode, select the edges you want to modify, and right-click to find **Loop Resample**.

Supported languages: English, Simplified Chinese, Traditional Chinese, Japanese, Korean, German, French, Spanish, Italian, Polish, Portuguese, Russian, and Vietnamese.

---

## 1. Resample Edge Chains Directly

Select edges and use the mouse wheel to change the segment count. The endpoints stay in place while the middle section is rebuilt. Meshes with imperfect topology are supported as well.

<img width="908" height="540" alt="1" src="https://github.com/user-attachments/assets/2b9ec61a-bd0d-4d2e-8e20-5796dee2ceca" />

## 2. Resample Closed Loops

Closed edge loops are supported too.

<img width="908" height="540" alt="2" src="https://github.com/user-attachments/assets/6329d5dc-444d-4cdd-b668-93e5b5b95ea6" />

## 3. Resample Multiple Chains at Once

Select multiple edge chains and change their segment counts together with a single scroll.

<img width="908" height="540" alt="3" src="https://github.com/user-attachments/assets/5200a5be-bebd-43bf-aac3-ead4cf5d3d24" />

## 4. Shift + Scroll: Smooth the Curve

Hold `Shift` while scrolling to quickly smooth your curve.

<img width="908" height="540" alt="4" src="https://github.com/user-attachments/assets/5c6fc478-74f6-429e-a7ed-070243e6dd48" />

## 5. Ctrl + Scroll: Even Out the Spacing

Hold `Ctrl` while scrolling to distribute the points evenly along the curve.

<img width="908" height="540" alt="5" src="https://github.com/user-attachments/assets/9c7eeca8-1cc6-4c19-94e1-96e80ea370a7" />

---

## ⌨️ Common Operations

| Operation | Action |
| --- | --- |
| Mouse wheel | Increase / decrease segment count |
| Shift + scroll | Smooth the curve |
| Ctrl + scroll | Even out point spacing |
| Left-click | Confirm the operation |
| Right-click | Cancel the operation |

## 🧩 How Attributes Are Handled

UVs, seams, sharp edges, crease and bevel weights, vertex colors, and vertex group weights are transferred to new vertices and edges based on their original positions whenever possible.

Shape Keys, custom attribute layers, and Skin markers are currently not supported.

## ⚙️ System Requirements

Blender 4.2.0 or later

## 📄 License

GNU General Public License v3.0 or later
