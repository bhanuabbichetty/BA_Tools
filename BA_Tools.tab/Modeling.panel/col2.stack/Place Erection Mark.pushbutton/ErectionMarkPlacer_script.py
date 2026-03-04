# -*- coding: utf-8 -*-
"""
Erection Mark Placer
Place erection marks at the centre of exterior wall faces with height control.
"""
__title__ = 'Erection\nMark'
__doc__   = 'Place erection marks on wall exterior faces with height control'

import clr
import os
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.UI import *
from pyrevit import revit, script, forms
import System
import System.Windows.Media as Media
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()


# ==============================================================================
# WALL SELECTION FILTER
# ==============================================================================

class WallSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Wall)

    def AllowReference(self, reference, position):
        return False


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_erection_mark_families():
    """
    Return ALL loadable families in the project (not just 'Erection Mark' names)
    so the user can pick any appropriate family.
    Filters out in-place families.
    """
    families = {}
    for fam in FilteredElementCollector(doc).OfClass(Family).ToElements():
        if not fam.IsInPlace:
            families[fam.Name] = fam
    return families


def get_family_symbols(family):
    """Return list of (type_name, FamilySymbol) sorted alphabetically."""
    result = []
    for sym_id in family.GetFamilySymbolIds():
        sym = doc.GetElement(sym_id)
        if sym:
            try:
                name = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            except Exception:
                name = Element.Name.GetValue(sym)
            result.append((name or "Unnamed", sym))
    return sorted(result, key=lambda x: x[0])


def get_wall_base_level_elevation(wall):
    """Return elevation (ft) of the wall's base constraint level."""
    try:
        param = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        if param:
            level = doc.GetElement(param.AsElementId())
            if level:
                return level.Elevation
    except Exception:
        pass
    return 0.0


def wall_has_openings(wall):
    """Check if wall has any door or window openings."""
    try:
        inserts = wall.FindInserts(True, True, True, True)
        return inserts and inserts.Size > 0
    except Exception:
        return False


def get_wall_face_boundary_and_place(wall, height_mm, face_side):
    """
    Place erection mark at the horizontal centre of the wall face at the
    requested height.

    Opening-avoidance logic (vertical axis only — host is never lost):
    1.  For every insert (door/window/opening) in the wall, project the
        wall's horizontal midpoint onto the wall-direction axis and check
        whether it falls inside the insert's horizontal span.
    2.  If it does AND the requested height Z falls inside the insert's
        Z range → the mark would land in the void and lose its host.
        In that case, move the placement point 100 mm above the insert top.
        If multiple openings overlap the centre, take the highest top.
    3.  Otherwise place at the original requested height.

    Returns (XYZ placement_pt, Reference face_ref).
    """
    CLEAR_MM = 100.0

    try:
        # ── Face reference ────────────────────────────────────────────────
        shell_type = ShellLayerType.Exterior if face_side == "Exterior" \
                     else ShellLayerType.Interior
        side_refs  = HostObjectUtils.GetSideFaces(wall, shell_type)
        if not side_refs or len(side_refs) == 0:
            return None, None

        face_ref = side_refs[0]
        face_obj = wall.GetGeometryObjectFromReference(face_ref)
        if not isinstance(face_obj, Face):
            return None, None

        # ── Wall geometry ─────────────────────────────────────────────────
        loc = wall.Location
        if not isinstance(loc, LocationCurve):
            return None, None

        curve      = loc.Curve
        wall_start = curve.GetEndPoint(0)
        wall_end   = curve.GetEndPoint(1)
        wall_dir   = (wall_end - wall_start).Normalize()
        mid_pt     = curve.Evaluate(0.5, True)

        orient     = wall.Orientation
        if face_side == "Interior":
            orient = orient.Negate()
        half_width = wall.Width / 2.0

        face_x = mid_pt.X + orient.X * half_width
        face_y = mid_pt.Y + orient.Y * half_width

        base_elev  = get_wall_base_level_elevation(wall)
        height_ft  = height_mm / 304.8
        target_z   = base_elev + height_ft
        clear_ft   = CLEAR_MM / 304.8
        tol_ft     = 5.0 / 304.8   # 5 mm tolerance

        # ── Check every insert ────────────────────────────────────────────
        adjusted_z = target_z

        try:
            inserts = wall.FindInserts(True, True, True, True)
        except Exception:
            inserts = []

        # inserts is a Python list-like in IronPython — use len(), not .Size
        if inserts and len(inserts) > 0:
            for insert_id in inserts:
                try:
                    insert = doc.GetElement(insert_id)
                    if insert is None:
                        continue

                    bbox = insert.get_BoundingBox(None)
                    if bbox is None:
                        continue

                    # ── Project onto wall axis ────────────────────────────
                    # Scalar offset of wall midpoint from wall start
                    mid_offset = (mid_pt - wall_start).DotProduct(wall_dir)

                    # Scalar offset of insert bbox centre from wall start
                    ins_ctr_2d = XYZ(
                        (bbox.Min.X + bbox.Max.X) * 0.5,
                        (bbox.Min.Y + bbox.Max.Y) * 0.5,
                        0.0
                    )
                    start_2d   = XYZ(wall_start.X, wall_start.Y, 0.0)
                    ins_offset = (ins_ctr_2d - start_2d).DotProduct(wall_dir)

                    # Half-span of insert along wall direction
                    ins_half   = max(
                        abs(bbox.Max.X - bbox.Min.X),
                        abs(bbox.Max.Y - bbox.Min.Y)
                    ) * 0.5

                    # 1. Horizontal check: wall centre inside insert span?
                    if abs(mid_offset - ins_offset) > (ins_half + tol_ft):
                        continue

                    # 2. Vertical check: target Z inside insert Z range?
                    if not ((bbox.Min.Z - tol_ft) <= target_z <= (bbox.Max.Z + tol_ft)):
                        continue

                    # Both overlap → raise above insert top
                    candidate_z = bbox.Max.Z + clear_ft
                    if candidate_z > adjusted_z:
                        adjusted_z = candidate_z
                        output.print_md(
                            "  Wall {} — opening at centre (insert ID {}), "
                            "raised {:.0f} mm above opening top".format(
                                wall.Id.IntegerValue,
                                insert_id.IntegerValue,
                                CLEAR_MM
                            )
                        )

                except Exception:
                    continue

        placement_pt = XYZ(face_x, face_y, adjusted_z)
        return placement_pt, face_ref

    except Exception as e:
        output.print_md("⚠ Wall {} placement error: {}".format(
            wall.Id.IntegerValue, str(e)))
        return None, None


def calculate_side_placement(wall, height_mm, face_side):
    """
    Return (XYZ placement_point, Reference face_ref) for the requested side face.

    face_side: "Exterior" or "Interior"

    Uses HostObjectUtils.GetSideFaces with proper ShellLayerType.

    Placement point:
      X,Y  = horizontal midpoint of the wall, projected onto the exterior surface
      Z    = wall base level elevation + height_mm converted to feet
    """
    try:
        # ── Side face reference via HostObjectUtils ───────────────────────
        shell_type = ShellLayerType.Exterior if face_side == "Exterior" else ShellLayerType.Interior
        side_refs = HostObjectUtils.GetSideFaces(wall, shell_type)
        if not side_refs or side_refs.Count == 0:
            output.print_md("⚠ Wall {} — no {} face found".format(
                wall.Id.IntegerValue, face_side.lower()))
            return None, None

        face_ref = side_refs[0]
        face_obj = wall.GetGeometryObjectFromReference(face_ref)
        if not isinstance(face_obj, Face):
            output.print_md("⚠ Wall {} — invalid {} face geometry".format(
                wall.Id.IntegerValue, face_side.lower()))
            return None, None

        # ── Centre of wall in plan (midpoint of location curve) ───────────
        loc = wall.Location
        if not isinstance(loc, LocationCurve):
            output.print_md("⚠ Wall {} — no location curve".format(
                wall.Id.IntegerValue))
            return None, None

        curve = loc.Curve
        mid_pt = curve.Evaluate(0.5, True)   # normalised midpoint

        # ── Offset midpoint to requested side face ────────────────────────
        # wall.Orientation points toward exterior.
        orient = wall.Orientation
        if face_side == "Interior":
            orient = orient.Negate()
        half_width = wall.Width / 2.0        # Width is already in feet

        ext_x = mid_pt.X + orient.X * half_width
        ext_y = mid_pt.Y + orient.Y * half_width

        # ── Target elevation ──────────────────────────────────────────────
        base_elev  = get_wall_base_level_elevation(wall)
        height_ft  = height_mm / 304.8
        target_z   = base_elev + height_ft

        placement_pt = XYZ(ext_x, ext_y, target_z)
        return placement_pt, face_ref

    except Exception as e:
        output.print_md("⚠ Wall {} error ({}): {}".format(
            wall.Id.IntegerValue, face_side, str(e)))
        return None, None


# ==============================================================================
# WPF WINDOW
# ==============================================================================

class ErectionMarkPlacerWindow(object):

    def __init__(self, xaml_path, selected_walls):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()

        self.selected_walls = selected_walls
        self.all_families   = {}    # {name: Family}
        self.families       = {}    # filtered {name: Family}
        self.result         = False

        # ── Controls ──────────────────────────────────────────────────────
        self.headerDragArea  = self._window.FindName("headerDragArea")
        self.btnClose        = self._window.FindName("btnClose")

        self.txtWallCount    = self._window.FindName("txtWallCount")
        self.txtWallList     = self._window.FindName("txtWallList")

        self.txtFamilySearch = self._window.FindName("txtFamilySearch")
        self.cmbFamily       = self._window.FindName("cmbFamily")
        self.cmbType         = self._window.FindName("cmbType")
        self.cmbFaceSide     = self._window.FindName("cmbFaceSide")

        self.txtHeight       = self._window.FindName("txtHeight")
        self.btnPreset1000   = self._window.FindName("btnPreset1000")
        self.btnPreset1500   = self._window.FindName("btnPreset1500")
        self.btnPreset2000   = self._window.FindName("btnPreset2000")
        self.btnPreset2500   = self._window.FindName("btnPreset2500")

        self.txtSummaryWalls  = self._window.FindName("txtSummaryWalls")
        self.txtSummaryFamily = self._window.FindName("txtSummaryFamily")
        self.txtSummaryHeight = self._window.FindName("txtSummaryHeight")
        self.txtSummaryFace   = self._window.FindName("txtSummaryFace")
        self.txtSummaryTotal  = self._window.FindName("txtSummaryTotal")

        self.txtStatus       = self._window.FindName("txtStatus")
        self.btnPlace        = self._window.FindName("btnPlace")

        # ── Wire events FIRST so LoadFamilies triggers OnFamilyChanged ─────
        self.SetupEventHandlers()

        # ── Populate data ─────────────────────────────────────────────────
        self.all_families = get_erection_mark_families()
        self.LoadFamilies()      # sets SelectedIndex → fires OnFamilyChanged
        self.UpdateWallList()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    # ── Drag ──────────────────────────────────────────────────────────────

    def OnHeaderDrag(self, sender, args):
        try:
            self._window.DragMove()
        except Exception:
            pass

    def _get_face_side(self):
        """Return selected face side as plain string."""
        try:
            sel = self.cmbFaceSide.SelectedItem
            if sel is None:
                return "Exterior"
            content = getattr(sel, "Content", None)
            if content:
                return str(content)
            return str(sel)
        except Exception:
            return "Exterior"

    # ── Event wiring ──────────────────────────────────────────────────────

    def SetupEventHandlers(self):
        self.btnClose.Click              += self.OnClose
        self.txtFamilySearch.TextChanged += self.OnFamilySearchChanged
        self.cmbFamily.SelectionChanged  += self.OnFamilyChanged
        self.cmbType.SelectionChanged    += self.OnTypeChanged
        self.cmbFaceSide.SelectionChanged+= self.OnFaceSideChanged
        self.txtHeight.TextChanged       += self.OnHeightChanged
        self.btnPreset1000.Click         += lambda s, e: self.SetHeight(1000)
        self.btnPreset1500.Click         += lambda s, e: self.SetHeight(1500)
        self.btnPreset2000.Click         += lambda s, e: self.SetHeight(2000)
        self.btnPreset2500.Click         += lambda s, e: self.SetHeight(2500)
        self.btnPlace.Click              += self.OnPlaceMarks

    # ── Family loading ────────────────────────────────────────────────────

    def LoadFamilies(self):
        """Populate family combo (filtered by search text)."""
        self.RefreshFamilyList("")

    def RefreshFamilyList(self, search_text):
        self.cmbFamily.Items.Clear()
        search = (search_text or "").strip().lower()

        self.families = {
            name: fam for name, fam in sorted(self.all_families.items())
            if (not search) or (search in name.lower())
        }

        if not self.families:
            if self.all_families:
                self.cmbFamily.Items.Add("No family match")
                self.txtStatus.Text = "No family match found"
            else:
                self.cmbFamily.Items.Add("No families loaded in project")
                self.txtStatus.Text = "Load an Erection Mark family first"
            self.cmbFamily.SelectedIndex = 0
            self.cmbFamily.IsEnabled     = False
            self.cmbType.Items.Clear()
            return

        self.cmbFamily.IsEnabled = True
        for name in sorted(self.families.keys()):
            self.cmbFamily.Items.Add(name)

        # Setting SelectedIndex fires OnFamilyChanged → populates Type combo
        if self.cmbFamily.Items.Count > 0:
            self.cmbFamily.SelectedIndex = 0

    def OnFamilySearchChanged(self, sender, args):
        self.RefreshFamilyList(self.txtFamilySearch.Text if self.txtFamilySearch else "")

    def OnFamilyChanged(self, sender, args):
        """Populate types whenever a family is selected."""
        self.cmbType.Items.Clear()

        if self.cmbFamily.SelectedIndex < 0:
            return

        family_name = self.cmbFamily.SelectedItem
        if family_name not in self.families:
            return

        family  = self.families[family_name]
        symbols = get_family_symbols(family)

        for type_name, sym in symbols:
            self.cmbType.Items.Add(type_name)

        if self.cmbType.Items.Count > 0:
            self.cmbType.SelectedIndex = 0

        self.UpdateSummary()
        self.UpdatePlaceButton()

    def OnFaceSideChanged(self, sender, args):
        self.UpdateSummary()

    def OnTypeChanged(self, sender, args):
        self.UpdateSummary()
        self.UpdatePlaceButton()

    # ── Wall list ─────────────────────────────────────────────────────────

    def UpdateWallList(self):
        if not self.selected_walls:
            self.txtWallCount.Text       = "0 Walls"
            self.txtWallCount.Foreground = Media.Brushes.Orange
            self.txtWallList.Text        = "No walls selected"
            self.btnPlace.IsEnabled      = False
            self.UpdateSummary()
            return

        self.txtWallCount.Text       = "{} Walls".format(len(self.selected_walls))
        self.txtWallCount.Foreground = Media.Brushes.LightGreen

        lines = []
        for i, wall in enumerate(self.selected_walls, 1):
            lines.append("{}. {} (ID: {})".format(
                i, wall.Name, wall.Id.IntegerValue))
        self.txtWallList.Text = "\n".join(lines)

        self.UpdateSummary()
        self.UpdatePlaceButton()

    # ── Summary ───────────────────────────────────────────────────────────

    def UpdateSummary(self):
        self.txtSummaryWalls.Text = "Walls: {}".format(len(self.selected_walls))

        if (self.cmbFamily.SelectedIndex >= 0 and
                self.cmbType.SelectedIndex >= 0):
            self.txtSummaryFamily.Text = "Family: {} — {}".format(
                self.cmbFamily.SelectedItem,
                self.cmbType.SelectedItem)
        else:
            self.txtSummaryFamily.Text = "Family: Not selected"

        try:
            h = float(self.txtHeight.Text) if self.txtHeight.Text else 2000
            self.txtSummaryHeight.Text = "Height: {:.0f} mm".format(h)
        except Exception:
            self.txtSummaryHeight.Text = "Height: 2000 mm"

        self.txtSummaryFace.Text = "Face Side: {}".format(self._get_face_side())

        self.txtSummaryTotal.Text = "Total Marks: {}".format(
            len(self.selected_walls))

    def UpdatePlaceButton(self):
        ready = (
            len(self.selected_walls) > 0 and
            self.cmbFamily.SelectedIndex >= 0 and
            self.cmbType.SelectedIndex   >= 0
        )
        self.btnPlace.IsEnabled = ready
        if ready:
            self.txtStatus.Text = "Ready — click PLACE MARKS"
        else:
            self.txtStatus.Text = "Select walls and a family type to continue"

    # ── Height presets ────────────────────────────────────────────────────

    def SetHeight(self, h):
        self.txtHeight.Text = str(h)

    def OnHeightChanged(self, sender, args):
        self.UpdateSummary()

    # ── Close ─────────────────────────────────────────────────────────────

    def OnClose(self, sender, args):
        self._window.DialogResult = False
        self._window.Close()

    # ── Place marks ───────────────────────────────────────────────────────

    def OnPlaceMarks(self, sender, args):
        if not self.selected_walls:
            forms.alert("No walls selected.", title="Error")
            return

        if self.cmbFamily.SelectedIndex < 0 or self.cmbType.SelectedIndex < 0:
            forms.alert("Please select a family and type.", title="Error")
            return

        try:
            height_mm   = float(self.txtHeight.Text)
        except Exception:
            forms.alert("Invalid height value.", title="Error")
            return

        family_name = self.cmbFamily.SelectedItem
        type_name   = self.cmbType.SelectedItem
        face_side   = self._get_face_side()
        family      = self.families[family_name]

        # Resolve the FamilySymbol
        selected_symbol = None
        for tname, sym in get_family_symbols(family):
            if tname == type_name:
                selected_symbol = sym
                break

        if not selected_symbol:
            forms.alert("Could not resolve the selected family type.", title="Error")
            return

        # Confirm
        if not forms.alert(
            "Place {} erection mark(s) at {:.0f} mm height?\n\n"
            "Family: {} — {}\n"
            "Face Side: {}".format(
                len(self.selected_walls), height_mm, family_name, type_name, face_side),
            yes=True, no=True, title="Confirm"
        ):
            return

        self.btnPlace.IsEnabled = False
        self.txtStatus.Text     = "Placing erection marks..."

        placed_count = 0
        failed_ids   = []

        with revit.Transaction("Place Erection Marks"):

            # Activate symbol once
            if not selected_symbol.IsActive:
                selected_symbol.Activate()
                doc.Regenerate()

            for wall in self.selected_walls:
                try:
                    # Use boundary-based placement with intersection detection
                    pt, face_ref = get_wall_face_boundary_and_place(wall, height_mm, face_side)
                    
                    if pt is None:
                        output.print_md("⚠ Wall {} — boundary placement failed".format(
                            wall.Id.IntegerValue))
                        failed_ids.append(wall.Id.IntegerValue)
                        continue

                    # Get wall base level
                    base_level = None
                    try:
                        bp = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
                        if bp:
                            wlvl_id = bp.AsElementId()
                            if wlvl_id != ElementId.InvalidElementId:
                                base_level = doc.GetElement(wlvl_id)
                    except:
                        pass
                    
                    if base_level is None:
                        try:
                            base_level = doc.GetElement(wall.LevelId)
                        except:
                            pass
                    
                    if base_level is None:
                        output.print_md("⚠ Wall {} — no level found".format(wall.Id.IntegerValue))
                        failed_ids.append(wall.Id.IntegerValue)
                        continue

                    # Get wall direction for refDir
                    loc_curve = wall.Location
                    if not isinstance(loc_curve, LocationCurve):
                        output.print_md("⚠ Wall {} — no location curve".format(wall.Id.IntegerValue))
                        failed_ids.append(wall.Id.IntegerValue)
                        continue

                    wall_curve = loc_curve.Curve
                    wall_dir = (wall_curve.GetEndPoint(1) - wall_curve.GetEndPoint(0)).Normalize()

                    instance = None
                    
                    # Try face-based placement first
                    if face_ref:
                        try:
                            instance = doc.Create.NewFamilyInstance(
                                face_ref, pt, wall_dir, selected_symbol
                            )
                        except Exception as e:
                            instance = None
                    
                    # Try wall-hosted placement
                    if instance is None:
                        try:
                            instance = doc.Create.NewFamilyInstance(
                                pt, selected_symbol, wall, base_level, StructuralType.NonStructural
                            )
                        except Exception as e:
                            instance = None
                    
                    # Try level-based placement
                    if instance is None:
                        try:
                            instance = doc.Create.NewFamilyInstance(
                                pt, selected_symbol, base_level, StructuralType.NonStructural
                            )
                        except Exception as e:
                            instance = None

                    if instance is None:
                        output.print_md("⚠ All placement methods failed for wall {}".format(
                            wall.Id.IntegerValue))
                        failed_ids.append(wall.Id.IntegerValue)
                        continue

                    # ── Assign wall base level to erection mark instance ──
                    try:
                        bp = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
                        if bp:
                            wlvl_id = bp.AsElementId()
                            if wlvl_id != ElementId.InvalidElementId:
                                for bip in [BuiltInParameter.FAMILY_LEVEL_PARAM,
                                            BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM]:
                                    try:
                                        p = instance.get_Parameter(bip)
                                        if p and not p.IsReadOnly:
                                            p.Set(wlvl_id)
                                    except Exception:
                                        pass
                    except Exception as le:
                        output.print_md("  Level assign failed (Wall {}): {}".format(
                            wall.Id.IntegerValue, str(le)))

                    placed_count += 1

                except Exception as e:
                    output.print_md("✗ Wall {}: {}".format(
                        wall.Id.IntegerValue, str(e)))
                    failed_ids.append(wall.Id.IntegerValue)

        # ── Report ────────────────────────────────────────────────────────
        result_msg = "Successfully placed {} erection mark(s).".format(placed_count)
        if failed_ids:
            result_msg += "\n\nFailed on {} wall(s):\nIDs: {}".format(
                len(failed_ids),
                ", ".join(str(i) for i in failed_ids))

        forms.alert(result_msg, title="Placement Complete")

        output.print_md("## ✅ Erection Mark Placement Complete")
        output.print_md("**Family** : {} — {}".format(family_name, type_name))
        output.print_md("**Face**   : {}".format(face_side))
        output.print_md("**Height** : {:.0f} mm from base level".format(height_mm))
        output.print_md("**Placed** : {}".format(placed_count))
        output.print_md("**Failed** : {}".format(len(failed_ids)))

        self.result         = True
        self.btnPlace.IsEnabled = True
        self.txtStatus.Text = "✓ {} mark(s) placed".format(placed_count)

        # Close after successful placement
        self._window.Close()

    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN — Select walls FIRST, then open UI
# ==============================================================================

try:
    output.print_md("### Select Walls")
    output.print_md("Click walls in the model, then press **Finish** (green tick)…")

    selected_refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        WallSelectionFilter(),
        "Select walls to place erection marks — press Finish when done"
    )

    if not selected_refs or selected_refs.Count == 0:
        output.print_md("No walls selected. Operation cancelled.")
        script.exit()

    selected_walls = []
    for ref in selected_refs:
        wall = doc.GetElement(ref.ElementId)
        if isinstance(wall, Wall):
            selected_walls.append(wall)

    output.print_md("**Selected {} wall(s)**".format(len(selected_walls)))

except Exception as ex:
    msg = str(ex).lower()
    if "cancelled" in msg or "aborted" in msg:
        output.print_md("Selection cancelled.")
    else:
        output.print_md("**Selection error**: {}".format(str(ex)))
    script.exit()

# Open the UI
script_dir = os.path.dirname(__file__)
xaml_path  = os.path.join(script_dir, "ErectionMarkPlacer.xaml")

if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

window = ErectionMarkPlacerWindow(xaml_path, selected_walls)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Erection Marks Placed Successfully")
else:
    output.print_md("### Operation Cancelled")