# BA_Tools: Building Automation & Revit Productivity Suite

## 🚀 Overview
**BA_Tools** is a high-performance Revit extension developed using the **pyRevit** framework. It provides a suite of automated tools designed to streamline Building Automation (BA) workflows, modeling efficiency, and documentation accuracy.

This project demonstrates expertise in:
- **Revit API Development** (Python/C# interop)
- **WPF/XAML UI Design** (Modern, dark-themed interfaces)
- **Computational Geometry** (Automated element placement and manipulation)
- **Workflow Automation** (Reducing repetitive manual tasks)

---

## 🏗️ Technical Architecture

### 1. Centralized Resource Management
To ensure a consistent look and feel across 30+ tools, I implemented a centralized styling system.
- **`Resources/BAWindowStyles.xaml`**: A shared ResourceDictionary containing standardized styles for buttons, scrollbars, and layouts.
- **`ba_ui_helper.py`**: A custom utility to dynamically merge these shared resources into WPF windows at runtime, overcoming Revit's assembly loading constraints.

```python
# Technical Highlight: Dynamic Resource Merging
def merge_ba_window_styles(window, script_dir):
    path = _find_ba_styles_path(script_dir)
    with StreamReader(path) as stream:
        rd = XamlReader.Load(stream.BaseStream)
        if rd and hasattr(window, 'Resources'):
            window.Resources.MergedDictionaries.Insert(0, rd)
```

### 2. UI/UX Strategy
The suite features a "Modern Dark" aesthetic, prioritizing high contrast and slim components to maximize Revit's screen real estate.
- **Slim Scrollbars**: Custom WPF templates for unobtrusive navigation.
- **Branded Components**: Consistent use of `PrimaryButton`, `SecondaryButton`, and corporate branding.

---

## 🛠️ Key Feature Pillars

### 🔹 Modeling Automation
*Example: [Create Slab from Line](Spotlight/Modeling_Automation.md)*
Automates the generation of complex floor systems from 2D geometry (Lines/Arcs).
- Handles perpendicular offsets for slab boundaries.
- Support for automated segment splitting and joint gap calculation.

### 🔹 Intelligent Annotation
*Example: [ReNumber Utility](Spotlight/Annotation_Efficiency.md)*
A smart renumbering engine that handles sequential naming with collision detection.
- **Interactive Selection**: Uses Revit's `PickObjects` for intuitive user flow.
- **Collision Handling**: Automatically shifts existing numbers to avoid duplicates.

### 🔹 Project Management & Export
- **Workset Management**: Automated 3D view generation based on worksets.
- **Bulk Export**: One-click NWC and PDF/Sheet export utilities.

---

## 📈 Impact
- **Efficiency**: Reduced manual modeling time for slab systems by ~80%.
- **Accuracy**: Eliminated duplicate numbering errors in large-scale projects.
- **Standardization**: Provided a unified interface for diverse project teams.

---

## 🔍 Deep Dives
- [Modeling Automation Spotlight](Spotlight/Modeling_Automation.md)
- [Annotation Efficiency Spotlight](Spotlight/Annotation_Efficiency.md)

---
*Created for interview presentation purposes.*
