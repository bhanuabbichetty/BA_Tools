# -*- coding: utf-8 -*-
__title__ = "Levels\nDimensions"
__author__ = "Bhanu Prakash A"
__doc__ = """Dimension levels and toggle level bubbles on the chosen sides
(left / right) for the current elevation/section or several views, with a
selectable dimension style and 2D / 3D level extent."""

import os
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction, ElementId,
    XYZ, Line, View, ViewType, Level, Element, Reference, ReferenceArray,
    DimensionType, DimensionStyleType, DatumEnds, DatumExtentType
)
from pyrevit import forms, script

import wpf
from System.Windows import Window
from System.Windows.Controls import CheckBox, DataGridRow
from System.Windows.Media import VisualTreeHelper
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
import System

PATH_SCRIPT = os.path.dirname(__file__)
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()
INVALID_ID = ElementId.InvalidElementId

MM_PER_FT = 304.8

# Levels are horizontal datums shown in vertical views.
LEVEL_VIEW_TYPES = set([ViewType.Elevation, ViewType.Section])


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

class ComboItem(object):
    def __init__(self, id_val, label):
        self.Id = id_val
        self.Label = label


def is_level_capable_view(view):
    if view is None:
        return False
    try:
        if view.IsTemplate:
            return False
    except Exception:
        return False
    try:
        return view.ViewType in LEVEL_VIEW_TYPES
    except Exception:
        return False


def collect_level_views():
    views = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if is_level_capable_view(v):
            views.append(v)
    return sorted(views, key=lambda x: x.Name)


def get_linear_dim_types():
    items = []
    for dt in FilteredElementCollector(doc).OfClass(DimensionType).ToElements():
        try:
            if dt.StyleType != DimensionStyleType.Linear:
                continue
        except Exception:
            continue
        name = None
        try:
            name = Element.Name.GetValue(dt)
        except Exception:
            name = None
        if not name:
            try:
                name = dt.Name
            except Exception:
                name = None
        if not name:
            name = "Type {}".format(dt.Id.IntegerValue)
        items.append(ComboItem(dt.Id, name))
    return sorted(items, key=lambda x: x.Label.lower())


def levels_in_view(view):
    return (FilteredElementCollector(doc, view.Id)
            .OfCategory(BuiltInCategory.OST_Levels)
            .WhereElementIsNotElementType()
            .ToElements())


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW COORDINATE MATH (elevation / section plane)
# ═══════════════════════════════════════════════════════════════════════════════

def view_basis(view):
    return (view.RightDirection, view.UpDirection,
            view.ViewDirection, view.Origin)


def to_ruv(p, origin, right, up, vdir):
    """World point -> (right, up, depth) coordinates of the view."""
    v = p.Subtract(origin)
    return (v.DotProduct(right), v.DotProduct(up), v.DotProduct(vdir))


def from_ruv(r, u, d, origin, right, up, vdir):
    """(right, up, depth) -> world point."""
    return (origin
            .Add(right.Multiply(r))
            .Add(up.Multiply(u))
            .Add(vdir.Multiply(d)))


def level_curve_in_view(level, view):
    for extent in (DatumExtentType.Model, DatumExtentType.ViewSpecific):
        try:
            crvs = level.GetCurvesInView(extent, view)
            if crvs and crvs.Count > 0:
                return crvs[0]
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# UI ROW MODEL
# ═══════════════════════════════════════════════════════════════════════════════

class ViewRow(INotifyPropertyChanged):
    def __init__(self, view):
        self.View = view
        self.Name = view.Name
        try:
            self.ViewTypeLabel = str(view.ViewType)
        except Exception:
            self.ViewTypeLabel = ""
        self._is_selected = False
        self._pch = None

    @property
    def IsSelected(self):
        return self._is_selected

    @IsSelected.setter
    def IsSelected(self, value):
        if self._is_selected != value:
            self._is_selected = value
            self._fire("IsSelected")

    def add_PropertyChanged(self, handler):
        self._pch = System.Delegate.Combine(self._pch, handler)

    def remove_PropertyChanged(self, handler):
        self._pch = System.Delegate.Remove(self._pch, handler)

    def _fire(self, name):
        if self._pch:
            self._pch(self, PropertyChangedEventArgs(name))


# ═══════════════════════════════════════════════════════════════════════════════
# WINDOW 1 — SCOPE
# ═══════════════════════════════════════════════════════════════════════════════

class LevelScopeUI(Window):
    def UIe_view_row_click(self, sender, e):
        try:
            node = e.OriginalSource
            row = None
            while node is not None:
                if isinstance(node, CheckBox):
                    return
                if isinstance(node, DataGridRow):
                    row = node
                    break
                try:
                    node = VisualTreeHelper.GetParent(node)
                except Exception:
                    node = None
            if row is not None and row.Item is not None:
                row.Item.IsSelected = not row.Item.IsSelected
                self._update_count()
                e.Handled = True
        except Exception:
            pass
    def UIe_drag_window(self, sender, e):
        try:
            self.DragMove()
        except Exception:
            pass
    def __init__(self):
        wpf.LoadComponent(self, os.path.join(PATH_SCRIPT, "LevelScopeUI.xaml"))
        self._views = collect_level_views()
        self.result = None

        active = uidoc.ActiveView
        if is_level_capable_view(active):
            self.UI_txt_current.Text = "→ {}".format(active.Name)
        else:
            self.UI_txt_current.Text = "→ active view isn't an elevation / section"
            self.UI_rb_current.IsEnabled = False
            self.UI_rb_multi.IsChecked = True

        rows = ObservableCollection[object]()
        for v in self._views:
            rows.Add(ViewRow(v))
        self.UI_dg_views.ItemsSource = rows
        self._sync_enabled()
        self._update_count()
        self.ShowDialog()

    def _sync_enabled(self):
        self.UI_dg_views.IsEnabled = bool(self.UI_rb_multi.IsChecked)

    def _update_count(self):
        rows = self.UI_dg_views.ItemsSource
        if rows is None:
            return
        sel = sum(1 for r in rows if r.IsSelected)
        self.UI_txt_count.Text = "{}/{} selected".format(sel, rows.Count)

    def UIe_scope_changed(self, sender, e):
        self._sync_enabled()

    def UIe_select_all(self, sender, e):
        for r in self.UI_dg_views.ItemsSource:
            r.IsSelected = True
        self._update_count()

    def UIe_select_none(self, sender, e):
        for r in self.UI_dg_views.ItemsSource:
            r.IsSelected = False
        self._update_count()

    def UIe_btn_continue(self, sender, e):
        if self.UI_rb_current.IsChecked:
            active = uidoc.ActiveView
            if not is_level_capable_view(active):
                forms.alert("The active view isn't an elevation / section.",
                            exitscript=False)
                return
            self.result = [active]
        else:
            chosen = [r.View for r in self.UI_dg_views.ItemsSource if r.IsSelected]
            if not chosen:
                forms.alert("Select at least one view.", exitscript=False)
                return
            self.result = chosen
        self.Close()


# ═══════════════════════════════════════════════════════════════════════════════
# WINDOW 2 — SETUP
# ═══════════════════════════════════════════════════════════════════════════════

class LevelDimensionUI(Window):
    def UIe_drag_window(self, sender, e):
        try:
            self.DragMove()
        except Exception:
            pass
    def __init__(self, views):
        wpf.LoadComponent(self, os.path.join(PATH_SCRIPT, "LevelDimensionUI.xaml"))
        self._views = views
        self.result = None

        if len(views) == 1:
            self.UI_txt_subtitle.Text = "Step 2 of 2 — view: {}".format(views[0].Name)
        else:
            self.UI_txt_subtitle.Text = "Step 2 of 2 — {} views selected".format(len(views))

        self._dim_types = get_linear_dim_types()
        self.UI_combo_dim_type.ItemsSource = self._dim_types
        if self._dim_types:
            self.UI_combo_dim_type.SelectedIndex = 0
        else:
            forms.alert("No linear dimension types found in this project.",
                        exitscript=False)
        self.ShowDialog()

    def _read_mm(self, textbox, fallback):
        try:
            return float(textbox.Text.strip())
        except Exception:
            return fallback

    def _extent_choice(self):
        if self.UI_rb_2d.IsChecked:
            return "2d"
        if self.UI_rb_3d.IsChecked:
            return "3d"
        return "keep"

    def UIe_btn_run(self, sender, e):
        dim_item = self.UI_combo_dim_type.SelectedItem
        if dim_item is None:
            forms.alert("Choose a dimension style.", exitscript=False)
            return

        sides = {
            "left":  (bool(self.UI_chk_left_dim.IsChecked),  bool(self.UI_chk_left_bubble.IsChecked)),
            "right": (bool(self.UI_chk_right_dim.IsChecked), bool(self.UI_chk_right_bubble.IsChecked)),
        }
        self.result = {
            "views": self._views,
            "dim_type_id": dim_item.Id,
            "sides": sides,
            "overall": bool(self.UI_chk_overall.IsChecked),
            "offset_mm": self._read_mm(self.UI_txt_offset, 8.0),
            "gap_mm": self._read_mm(self.UI_txt_gap, 8.0),
            "extent": self._extent_choice(),
        }
        self.Close()


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def offset_feet(view, mm_on_paper):
    try:
        scale = view.Scale or 100
    except Exception:
        scale = 100
    return (mm_on_paper / MM_PER_FT) * float(scale)


# DatumEnds bubble side is inverted relative to GetEndPoint() order (see grid tool).
def left_end_for_level(r0, r1):
    return DatumEnds.End1 if r0 <= r1 else DatumEnds.End0


def right_end_for_level(r0, r1):
    return DatumEnds.End0 if r0 <= r1 else DatumEnds.End1


def gather_level_data(view, basis):
    """Return list of (level, r0, r1, u, depth) sorted by elevation (u)."""
    right, up, vdir, origin = basis
    data = []
    for lvl in levels_in_view(view):
        crv = level_curve_in_view(lvl, view)
        if crv is None:
            continue
        try:
            e0 = crv.GetEndPoint(0)
            e1 = crv.GetEndPoint(1)
        except Exception:
            continue
        r0, u0, d0 = to_ruv(e0, origin, right, up, vdir)
        r1, u1, d1 = to_ruv(e1, origin, right, up, vdir)
        u = (u0 + u1) / 2.0
        depth = (d0 + d1) / 2.0
        data.append((lvl, r0, r1, u, depth))
    data.sort(key=lambda d: d[3])
    return data


def make_dimension(view, levels, line, dim_type, only_ends=False):
    if only_ends and len(levels) >= 2:
        levels = [levels[0], levels[-1]]
    if len(levels) < 2:
        return None
    refs = ReferenceArray()
    for lvl in levels:
        try:
            refs.Append(Reference(lvl))
        except Exception:
            pass
    if refs.Size < 2:
        return None
    try:
        if dim_type is not None:
            return doc.Create.NewDimension(view, line, refs, dim_type)
        return doc.Create.NewDimension(view, line, refs)
    except Exception as ex:
        output.print_md("  - dimension failed: `{}`".format(ex))
        return None


def place_side(view, side, data, basis, dim_type, offset_ft, gap_ft,
               add_overall, report):
    """Vertical dimension string on the left or right of the levels."""
    if len(data) < 2:
        return
    right, up, vdir, origin = basis
    rs = []
    for _, r0, r1, _u, _d in data:
        rs.extend([r0, r1])
    min_r, max_r = min(rs), max(rs)
    us = [d[3] for d in data]
    min_u, max_u = min(us), max(us)
    if abs(max_u - min_u) < 1e-6:
        return
    depth = sum(d[4] for d in data) / float(len(data))
    levels_sorted = [d[0] for d in data]

    # inboard of the level ends so the bubble stays outside
    r_line = (min_r + offset_ft) if side == "left" else (max_r - offset_ft)
    p_bot = from_ruv(r_line, min_u, depth, origin, right, up, vdir)
    p_top = from_ruv(r_line, max_u, depth, origin, right, up, vdir)
    chain = Line.CreateBound(p_bot, p_top)
    if make_dimension(view, levels_sorted, chain, dim_type):
        report["dims"] += 1

    if add_overall:
        r2 = (r_line + gap_ft) if side == "left" else (r_line - gap_ft)
        o_bot = from_ruv(r2, min_u, depth, origin, right, up, vdir)
        o_top = from_ruv(r2, max_u, depth, origin, right, up, vdir)
        overall = Line.CreateBound(o_bot, o_top)
        if make_dimension(view, levels_sorted, overall, dim_type, only_ends=True):
            report["dims"] += 1


def set_bubbles_and_extent(view, side, want_bubble, data, extent, report):
    extent_type = None
    if extent == "2d":
        extent_type = DatumExtentType.ViewSpecific
    elif extent == "3d":
        extent_type = DatumExtentType.Model

    for lvl, r0, r1, _u, _d in data:
        end = left_end_for_level(r0, r1) if side == "left" \
            else right_end_for_level(r0, r1)
        try:
            if want_bubble:
                lvl.ShowBubbleInView(end, view)
                report["bubbles"] += 1
            else:
                lvl.HideBubbleInView(end, view)
        except Exception:
            pass
        if extent_type is not None:
            try:
                lvl.SetDatumExtentType(end, view, extent_type)
            except Exception:
                pass


def process_view(view, settings, report):
    basis = view_basis(view)
    data = gather_level_data(view, basis)
    if not data:
        output.print_md("- **{}** — no levels found".format(view.Name))
        return

    dim_type = doc.GetElement(settings["dim_type_id"])
    offset_ft = offset_feet(view, settings["offset_mm"])
    gap_ft = offset_feet(view, settings["gap_mm"])

    for side, (want_dim, want_bubble) in settings["sides"].items():
        set_bubbles_and_extent(view, side, want_bubble, data,
                               settings["extent"], report)
        if want_dim:
            place_side(view, side, data, basis, dim_type,
                       offset_ft, gap_ft, settings["overall"], report)

    output.print_md("- **{}** — levels: {}".format(view.Name, len(data)))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    scope = LevelScopeUI()
    if not scope.result:
        return
    views = scope.result

    setup = LevelDimensionUI(views)
    if not setup.result:
        return
    settings = setup.result

    report = {"dims": 0, "bubbles": 0}
    errors = []

    t = Transaction(doc, "Levels Dimensions")
    t.Start()
    try:
        with forms.ProgressBar(title="Dimensioning levels...") as pb:
            for i, view in enumerate(views):
                pb.update_progress(i, len(views))
                try:
                    process_view(view, settings, report)
                except Exception as ex:
                    errors.append((view.Name, str(ex)))
        t.Commit()
    except Exception:
        t.RollBack()
        output.print_md("**Transaction failed — rolled back**")
        import traceback
        print(traceback.format_exc())
        return

    output.print_md("### Levels Dimensions — Complete")
    output.print_md("**{}** view(s) processed · **{}** dimension string(s) · "
                    "**{}** bubble(s) shown".format(
                        len(views), report["dims"], report["bubbles"]))
    if errors:
        output.print_md("### Errors")
        for name, msg in errors:
            output.print_md("- **{}**: `{}`".format(name, msg))

    forms.alert(
        "Finished.\n{} view(s) processed.\n{} dimension string(s) placed.".format(
            len(views), report["dims"]),
        exitscript=False)


try:
    main()
except SystemExit:
    pass
except Exception:
    output.print_md("**Error**")
    import traceback
    print(traceback.format_exc())
