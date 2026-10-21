# -*- coding: utf-8 -*-
__title__ = "Grid\nDimensions"
__author__ = "Bhanu Prakash A"
__doc__ = """Dimension grids and toggle grid bubbles on the chosen sides
(top / bottom / left / right) for the current view or several views,
with a selectable dimension style and 2D / 3D grid extent."""

import os
import sys
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction, ElementId,
    XYZ, Line, View, ViewType, Element, Reference, ReferenceArray,
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

# Plan view types — the top/bottom/left/right grid map is a plan concept,
# and the XY placement math below assumes a plan orientation.
GRID_VIEW_TYPES = set([
    ViewType.FloorPlan, ViewType.CeilingPlan,
    ViewType.EngineeringPlan, ViewType.AreaPlan,
])


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS — collection
# ═══════════════════════════════════════════════════════════════════════════════

class ComboItem(object):
    def __init__(self, id_val, label):
        self.Id = id_val
        self.Label = label


def is_grid_capable_view(view):
    if view is None:
        return False
    try:
        if view.IsTemplate:
            return False
    except Exception:
        return False
    try:
        return view.ViewType in GRID_VIEW_TYPES
    except Exception:
        return False


def collect_grid_views():
    """Graphical views that can carry grids, sorted by name."""
    views = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if is_grid_capable_view(v):
            views.append(v)
    return sorted(views, key=lambda x: x.Name)


def get_linear_dim_types():
    """Linear dimension types for the style dropdown."""
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


def grids_in_view(view):
    return (FilteredElementCollector(doc, view.Id)
            .OfCategory(BuiltInCategory.OST_Grids)
            .WhereElementIsNotElementType()
            .ToElements())


def grid_line(grid):
    """Return the grid's defining Line (None for arcs / non-line grids)."""
    try:
        crv = grid.Curve
    except Exception:
        return None
    if crv is None:
        return None
    try:
        p0 = crv.GetEndPoint(0)
        p1 = crv.GetEndPoint(1)
    except Exception:
        return None
    return (p0, p1)


def classify_grid(grid):
    """Return ('vertical'|'horizontal'|None, p0, p1)."""
    ends = grid_line(grid)
    if ends is None:
        return None, None, None
    p0, p1 = ends
    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)
    if dy >= dx:
        return "vertical", p0, p1      # runs in Y, bubbles top / bottom
    return "horizontal", p0, p1        # runs in X, bubbles left / right


# ═══════════════════════════════════════════════════════════════════════════════
# UI ROW MODELS
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

class GridScopeUI(Window):
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
        path_xaml = os.path.join(PATH_SCRIPT, "GridScopeUI.xaml")
        wpf.LoadComponent(self, path_xaml)

        self._views = collect_grid_views()
        self.result = None

        active = uidoc.ActiveView
        if is_grid_capable_view(active):
            self.UI_txt_current.Text = "→ {}".format(active.Name)
            self._active_ok = True
        else:
            self.UI_txt_current.Text = "→ active view can't host grid dimensions"
            self._active_ok = False
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
        multi = bool(self.UI_rb_multi.IsChecked)
        self.UI_dg_views.IsEnabled = multi

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
            if not is_grid_capable_view(active):
                forms.alert("The active view can't host grid dimensions.",
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

class GridDimensionUI(Window):
    def UIe_drag_window(self, sender, e):
        try:
            self.DragMove()
        except Exception:
            pass
    def __init__(self, views):
        path_xaml = os.path.join(PATH_SCRIPT, "GridDimensionUI.xaml")
        wpf.LoadComponent(self, path_xaml)

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
            "top":    (bool(self.UI_chk_top_dim.IsChecked),    bool(self.UI_chk_top_bubble.IsChecked)),
            "bottom": (bool(self.UI_chk_bottom_dim.IsChecked), bool(self.UI_chk_bottom_bubble.IsChecked)),
            "left":   (bool(self.UI_chk_left_dim.IsChecked),   bool(self.UI_chk_left_bubble.IsChecked)),
            "right":  (bool(self.UI_chk_right_dim.IsChecked),  bool(self.UI_chk_right_bubble.IsChecked)),
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
    """Convert a paper-space mm value into model feet using the view scale."""
    try:
        scale = view.Scale or 100
    except Exception:
        scale = 100
    return (mm_on_paper / MM_PER_FT) * float(scale)


def grid_bounds(grids_data):
    """Bounding extents across all grid endpoints. grids_data = [(grid, p0, p1)]."""
    xs, ys = [], []
    for _, p0, p1 in grids_data:
        xs.extend([p0.X, p1.X])
        ys.extend([p0.Y, p1.Y])
    return min(xs), max(xs), min(ys), max(ys)


# Revit's DatumEnds bubble side is inverted relative to the curve's
# GetEndPoint() order, so the geometric "high" end maps to End0.
def top_end_for_vertical(p0, p1):
    return DatumEnds.End0 if p1.Y >= p0.Y else DatumEnds.End1


def bottom_end_for_vertical(p0, p1):
    return DatumEnds.End1 if p1.Y >= p0.Y else DatumEnds.End0


def left_end_for_horizontal(p0, p1):
    return DatumEnds.End1 if p0.X <= p1.X else DatumEnds.End0


def right_end_for_horizontal(p0, p1):
    return DatumEnds.End0 if p0.X <= p1.X else DatumEnds.End1


def make_dimension(view, grids_data, line, dim_type, only_ends=False):
    """Create a continuous (or overall) dimension across the given grids."""
    if only_ends and len(grids_data) >= 2:
        grids_data = [grids_data[0], grids_data[-1]]
    if len(grids_data) < 2:
        return None
    refs = ReferenceArray()
    for grid, _, _ in grids_data:
        try:
            refs.Append(Reference(grid))
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


def place_side(view, side, vertical, horizontal, dim_type, offset_ft, gap_ft,
               add_overall, report):
    """Place dimension string(s) for one side of the view.

    Order (all sides):
      1. Overall — first grid to last grid, nearest the grid bubble
      2. Chain   — grid-to-grid string, below the overall (further inboard)
    """
    if side in ("top", "bottom"):
        data = vertical
        if len(data) < 2:
            return
        minx, maxx, miny, maxy = grid_bounds(data)
        data = sorted(data, key=lambda d: (d[1].X + d[2].X) / 2.0)
        if abs(maxx - minx) < 1e-6:
            return
        # nearest the grid bubble (inboard of grid ends)
        pos_near_bubble = (maxy - offset_ft) if side == "top" else (miny + offset_ft)
        if add_overall:
            overall = Line.CreateBound(
                XYZ(minx, pos_near_bubble, 0), XYZ(maxx, pos_near_bubble, 0))
            if make_dimension(view, data, overall, dim_type, only_ends=True):
                report["dims"] += 1
            pos_chain = (pos_near_bubble - gap_ft) if side == "top" else (pos_near_bubble + gap_ft)
        else:
            pos_chain = pos_near_bubble
        chain = Line.CreateBound(XYZ(minx, pos_chain, 0), XYZ(maxx, pos_chain, 0))
        if make_dimension(view, data, chain, dim_type):
            report["dims"] += 1
    else:
        data = horizontal
        if len(data) < 2:
            return
        minx, maxx, miny, maxy = grid_bounds(data)
        data = sorted(data, key=lambda d: (d[1].Y + d[2].Y) / 2.0)
        if abs(maxy - miny) < 1e-6:
            return
        pos_near_bubble = (minx + offset_ft) if side == "left" else (maxx - offset_ft)
        if add_overall:
            overall = Line.CreateBound(
                XYZ(pos_near_bubble, miny, 0), XYZ(pos_near_bubble, maxy, 0))
            if make_dimension(view, data, overall, dim_type, only_ends=True):
                report["dims"] += 1
            pos_chain = (pos_near_bubble + gap_ft) if side == "left" else (pos_near_bubble - gap_ft)
        else:
            pos_chain = pos_near_bubble
        chain = Line.CreateBound(XYZ(pos_chain, miny, 0), XYZ(pos_chain, maxy, 0))
        if make_dimension(view, data, chain, dim_type):
            report["dims"] += 1


def set_bubbles_and_extent(view, side, want_bubble, vertical, horizontal,
                           extent, report):
    extent_type = None
    if extent == "2d":
        extent_type = DatumExtentType.ViewSpecific
    elif extent == "3d":
        extent_type = DatumExtentType.Model

    if side in ("top", "bottom"):
        data = vertical
    else:
        data = horizontal

    for grid, p0, p1 in data:
        if side == "top":
            end = top_end_for_vertical(p0, p1)
        elif side == "bottom":
            end = bottom_end_for_vertical(p0, p1)
        elif side == "left":
            end = left_end_for_horizontal(p0, p1)
        else:
            end = right_end_for_horizontal(p0, p1)

        try:
            if want_bubble:
                grid.ShowBubbleInView(end, view)
                report["bubbles"] += 1
            else:
                grid.HideBubbleInView(end, view)
        except Exception:
            pass

        if extent_type is not None:
            try:
                grid.SetDatumExtentType(end, view, extent_type)
            except Exception:
                pass


def process_view(view, settings, report):
    grids = grids_in_view(view)
    vertical, horizontal = [], []
    for g in grids:
        kind, p0, p1 = classify_grid(g)
        if kind == "vertical":
            vertical.append((g, p0, p1))
        elif kind == "horizontal":
            horizontal.append((g, p0, p1))

    if not vertical and not horizontal:
        output.print_md("- **{}** — no line grids found".format(view.Name))
        return

    dim_type = doc.GetElement(settings["dim_type_id"])
    offset_ft = offset_feet(view, settings["offset_mm"])
    gap_ft = offset_feet(view, settings["gap_mm"])

    for side, (want_dim, want_bubble) in settings["sides"].items():
        # bubbles + extent first so dimensions attach to the final grid state
        set_bubbles_and_extent(view, side, want_bubble, vertical, horizontal,
                               settings["extent"], report)
        if want_dim:
            place_side(view, side, vertical, horizontal, dim_type,
                       offset_ft, gap_ft, settings["overall"], report)

    output.print_md("- **{}** — vertical: {}, horizontal: {}".format(
        view.Name, len(vertical), len(horizontal)))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    scope = GridScopeUI()
    if not scope.result:
        return
    views = scope.result

    setup = GridDimensionUI(views)
    if not setup.result:
        return
    settings = setup.result

    report = {"dims": 0, "bubbles": 0}
    errors = []

    t = Transaction(doc, "Grid Dimensions")
    t.Start()
    try:
        with forms.ProgressBar(title="Dimensioning grids...") as pb:
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

    output.print_md("### Grid Dimensions — Complete")
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
