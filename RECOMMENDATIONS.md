# Roadmap for Future Improvements & Automation

Based on an analysis of the current **BA_Tools** suite, here are several recommendations for technical enhancement and high-impact automation ideas for your Revit workflow.

---

## 🛠️ Technical Improvements

### 1. Robust Unit Testing Framework
Currently, the project lacks automated tests.
- **Recommendation**: Implement a testing framework like **Revit.TestRunner** or use **pytest** with a mock Revit API (like `Revit-API-Stub`) to test non-API logic.
- **Goal**: Ensure that geometry calculations (like those in `SlabFromLine`) don't break when you add new features.

### 2. Centralized User Settings
Many tools seem to use hardcoded defaults or require re-entry of data.
- **Recommendation**: Use `pyrevit.script.get_config()` to save user preferences (like default offsets or favorite slab types) to a JSON file.
- **Benefit**: Improves UX by remembering the user's "Last Used" settings.

### 3. Integrated Logging & Error Reporting
- **Recommendation**: Implement a centralized logger that writes to a shared network drive or a cloud service (like Sentry for Python).
- **Benefit**: Helps you identify which tools are failing for users without needing them to send screenshots of error dialogs.

### 4. CI/CD Pipeline
- **Recommendation**: Set up GitHub Actions to:
  - Check for syntax errors (Linting).
  - Automatically bundle the extension for distribution.
  - Verify `bundle.yaml` files are valid.

---

## 🚀 High-Impact Automation Ideas

### 1. 🏗️ "BIM Standard" Auditor
A tool that scans the model and flags elements that don't follow company naming conventions or parameter requirements.
- **Button Name**: `Audit Model`
- **Logic**: Checks Workset assignments, Naming (Rooms, Sheets), and missing Parameter values.

### 2. 📑 Automated Sheet Generator (from Excel/CSV)
Instead of creating sheets one by one, users can import a list from a spreadsheet.
- **Button Name**: `Bulk Sheets`
- **Logic**: Reads Excel/CSV, matches Titleblocks, and generates placeholders or views.

### 3. 🔗 Smart Link Synchronizer
A utility to manage multiple linked models (Architectural, Structural, MEP).
- **Button Name**: `Link Manager`
- **Logic**: Automatically reloads links, checks if links are pinned, and verifies that shared coordinates haven't shifted.

### 4. 🏷️ Intelligent Tag Placement
One of the most tedious tasks is tagging elements without overlaps.
- **Button Name**: `Auto-Tag`
- **Logic**: Uses collision detection to place tags in "empty" spaces around elements (e.g., tagging all Doors in a view at once).

### 5. 🧱 Geometry-Based Collision Check
A lightweight "Clash Detection" tool that runs inside Revit without needing Navisworks.
- **Button Name**: `Local Clash`
- **Logic**: Checks for intersections between two selected categories (e.g., Pipes vs. Slabs) and highlights them in a temporary 3D view.

---

## 🎨 UI/UX Enhancements

- **Progress Bars**: For long-running tasks (like bulk exports), use `pyrevit.forms.ProgressBar` to provide visual feedback.
- **Searchable UI**: In tools with long lists (like `Params2Param`), add a search/filter bar to the WPF window to find parameters faster.

---
*These suggestions aim to elevate BA_Tools from a collection of scripts to a enterprise-grade Revit automation suite.*
