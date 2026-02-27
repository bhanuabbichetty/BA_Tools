# -*- coding: utf-8 -*-
"""
Dowel Placer
Place dowel families on a selected wall face with configurable
left/right offsets, spacing interval, and vertical height.
"""
__title__ = 'Dowel\nPlacer'
__doc__   = 'Place dowels on a wall face with configurable spacing'

import clr, os, math
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application
output = script.get_output()

MM_TO_FT = 1.0 / 304.8   # 1 mm in feet


# ==============================================================================
# SELECTION FILTER — walls only
# ==============================================================================

class WallFaceFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Wall)

    def AllowReference(self, reference, point):
        return reference.ElementReferenceType == ElementReferenceType.REFERENCE_TYPE_SURFACE


# ==============================================================================
# HELPERS
# ==============================================================================

def mm_to_ft(mm):
    return mm * MM_TO_FT


def safe_float(text, default=0.0):
    try:
        return float(text.strip())
    except Exception:
        return default


def set_family_parameter(instance, param_name, value_mm):
    """
    Set a family instance parameter by name.
    value_mm is in millimeters, will be converted to feet for length parameters.
    """
    try:
        param = instance.LookupParameter(param_name)
        if param and not param.IsReadOnly:
            if param.StorageType == StorageType.Double:
                # Convert mm to feet for length parameters
                value_ft = value_mm / 304.8
                param.Set(value_ft)
                return True
            elif param.StorageType == StorageType.Integer:
                param.Set(int(value_mm))
                return True
        return False
    except:
        return False


def get_all_loadable_families():
    """Return dict  {family_name: Family element}  for all loadable families."""
    return {
        f.Name: f
        for f in FilteredElementCollector(doc).OfClass(Family).ToElements()
        if not f.IsInPlace
    }


def get_types_for_family(family):
    """Return list of (type_name, FamilySymbol) sorted by name."""
    result = []
    for type_id in family.GetFamilySymbolIds():
        sym = doc.GetElement(type_id)
        if sym:
            result.append((Element.Name.GetValue(sym), sym))
    return sorted(result, key=lambda x: x[0])


def calculate_dowel_positions(face, wall, left_off_mm, right_off_mm,
                               spacing_mm, v_offset_mm):
    """
    Return a list of XYZ world-coordinate points along the face.

    U axis  = horizontal direction along the face
    V axis  = vertical (up the face)

    left_off_mm  : offset from the left edge  (constant zone, no dowels)
    right_off_mm : offset from the right edge (constant zone, no dowels)
    spacing_mm   : distance between consecutive dowels
    v_offset_mm  : height from the bottom edge of the face
    """
    bbox  = face.GetBoundingBox()   # BoundingBoxUV
    min_u = bbox.Min.U
    max_u = bbox.Max.U
    min_v = bbox.Min.V
    max_v = bbox.Max.V

    left_off_ft  = mm_to_ft(left_off_mm)
    right_off_ft = mm_to_ft(right_off_mm)
    spacing_ft   = mm_to_ft(spacing_mm)
    v_off_ft     = mm_to_ft(v_offset_mm)

    if spacing_ft <= 0:
        return []

    # Detect which UV axis is vertical (changes world Z more).
    # This avoids assuming U=horizontal and V=vertical on all faces.
    u_range = max_u - min_u
    v_range = max_v - min_v
    mid_u = (min_u + max_u) * 0.5
    mid_v = (min_v + max_v) * 0.5
    du = max(u_range * 0.01, 1e-6)
    dv = max(v_range * 0.01, 1e-6)
    if du > (u_range * 0.5):
        du = u_range * 0.25
    if dv > (v_range * 0.5):
        dv = v_range * 0.25

    u_is_vertical = False
    try:
        p_u1 = face.Evaluate(UV(mid_u + du, mid_v))
        p_u0 = face.Evaluate(UV(mid_u - du, mid_v))
        p_v1 = face.Evaluate(UV(mid_u, mid_v + dv))
        p_v0 = face.Evaluate(UV(mid_u, mid_v - dv))
        dz_du = abs(p_u1.Z - p_u0.Z)
        dz_dv = abs(p_v1.Z - p_v0.Z)
        u_is_vertical = dz_du >= dz_dv
    except Exception:
        u_is_vertical = False

    # Map a generic horizontal/vertical parameter back to UV.
    if u_is_vertical:
        h_min, h_max = min_v, max_v
        t_min, t_max = min_u, max_u
        def to_uv(h, t):
            return UV(t, h)
    else:
        h_min, h_max = min_u, max_u
        t_min, t_max = min_v, max_v
        def to_uv(h, t):
            return UV(h, t)

    # Decide which horizontal edge is "left" by comparing edge points to wall start.
    left_is_min = True
    try:
        wall_curve = wall.Location.Curve
        wall_start = wall_curve.GetEndPoint(0)
        mid_t = (t_min + t_max) * 0.5
        pt_min = face.Evaluate(to_uv(h_min, mid_t))
        pt_max = face.Evaluate(to_uv(h_max, mid_t))
        left_is_min = pt_min.DistanceTo(wall_start) <= pt_max.DistanceTo(wall_start)
    except Exception:
        left_is_min = True

    if left_is_min:
        start_h = h_min + left_off_ft
        end_h = h_max - right_off_ft
        step_h = spacing_ft
    else:
        start_h = h_max - left_off_ft
        end_h = h_min + right_off_ft
        step_h = -spacing_ft

    if (left_is_min and start_h >= end_h) or ((not left_is_min) and start_h <= end_h):
        return []

    # Resolve vertical placement against wall base level elevation:
    # choose the vertical side (min/max parameter) that is closest to
    # (wall base level + requested offset). This avoids top-edge placement
    # when the face UV direction is flipped.
    mid_h = (start_h + end_h) * 0.5
    t_low = t_min + v_off_ft
    t_high = t_max - v_off_ft

    # Clamp candidates inside face UV range.
    if t_low < t_min:
        t_low = t_min
    if t_low > t_max:
        t_low = t_max
    if t_high < t_min:
        t_high = t_min
    if t_high > t_max:
        t_high = t_max

    t_at_height = t_low
    try:
        # Target world elevation from wall Base Constraint level.
        base_level = None
        base_level_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        if base_level_param:
            lvl_id = base_level_param.AsElementId()
            if lvl_id and lvl_id != ElementId.InvalidElementId:
                base_level = doc.GetElement(lvl_id)
        if base_level is None:
            base_level = doc.GetElement(wall.LevelId)

        target_z = (base_level.Elevation if base_level else 0.0) + v_off_ft

        z_low = face.Evaluate(to_uv(mid_h, t_low)).Z
        z_high = face.Evaluate(to_uv(mid_h, t_high)).Z
        t_at_height = t_low if abs(z_low - target_z) <= abs(z_high - target_z) else t_high
    except Exception:
        # Fallback: prefer lower world-Z side.
        try:
            z_low = face.Evaluate(to_uv(mid_h, t_low)).Z
            z_high = face.Evaluate(to_uv(mid_h, t_high)).Z
            t_at_height = t_low if z_low <= z_high else t_high
        except Exception:
            t_at_height = t_low

    positions = []
    h = start_h
    tolerance = spacing_ft * 0.001
    while (h <= end_h + tolerance) if left_is_min else (h >= end_h - tolerance):
        uv = to_uv(h, t_at_height)
        try:
            if face.IsInside(uv):
                pt = face.Evaluate(uv)
                positions.append(pt)
        except Exception:
            pass
        h += step_h

    return positions


def place_dowels_on_face(face, face_ref, wall, symbol,
                          positions, rotation_deg=0.0, model_props=None,
                          elevation_from_level_mm=0.0):
    """
    Place the FamilySymbol at each XYZ position on the face.

    Strategy:
    1. Try face-based placement  (NewFamilyInstance with Reference)
    2. Fall back to level-based  (NewFamilyInstance with Level)
    Then rotate by rotation_deg around the face normal axis if needed.
    """
    placed   = []
    failed   = []

    # Face normal (= wall orientation for the near face)
    try:
        face_normal = face.FaceNormal
    except Exception:
        face_normal = XYZ.BasisX

    # Reference direction = horizontal direction along the face
    ref_dir = face_normal.CrossProduct(XYZ.BasisZ)
    if ref_dir.IsZeroLength():
        ref_dir = XYZ.BasisX
    else:
        ref_dir = ref_dir.Normalize()

    # Level for placement + schedule level (use wall Base Constraint)
    base_level = None
    try:
        base_level_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        if base_level_param:
            lvl_id = base_level_param.AsElementId()
            if lvl_id and lvl_id != ElementId.InvalidElementId:
                base_level = doc.GetElement(lvl_id)
    except Exception:
        base_level = None

    if base_level is None:
        try:
            base_level = doc.GetElement(wall.LevelId)
        except Exception:
            base_level = FilteredElementCollector(doc).OfClass(Level).FirstElement()

    # Activate symbol if needed
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    # Keep UI rotation option, but apply an internal 180° correction so
    # default input (0°) places the dowel in the expected direction.
    rotation_rad = math.radians(rotation_deg + 180.0)

    for pt in positions:
        try:
            instance = None

            # --- Attempt 1: face-based ---
            try:
                instance = doc.Create.NewFamilyInstance(
                    face_ref, pt, ref_dir, symbol
                )
            except Exception:
                pass

            # --- Attempt 2: level-based ---
            if instance is None:
                try:
                    instance = doc.Create.NewFamilyInstance(
                        pt, symbol, base_level,
                        StructuralType.NonStructural
                    )
                except Exception:
                    pass

            # --- Attempt 3: simple XYZ ---
            if instance is None:
                instance = doc.Create.NewFamilyInstance(
                    pt, symbol, StructuralType.NonStructural
                )

            # Optional rotation offset around face normal
            if instance and abs(rotation_rad) > 0.0001:
                axis = Line.CreateBound(pt, pt + face_normal)
                ElementTransformUtils.RotateElement(
                    doc, instance.Id, axis, rotation_rad
                )

            # Force instance level/schedule level to wall Base Constraint level.
            if instance and base_level:
                for bip in [
                    BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM,
                    BuiltInParameter.FAMILY_LEVEL_PARAM,
                    BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM
                ]:
                    try:
                        p = instance.get_Parameter(bip)
                        if p and (not p.IsReadOnly):
                            p.Set(base_level.Id)
                    except Exception:
                        pass

            # Set Elevation from Level to the user-supplied value.
            if instance:
                elev_ft = elevation_from_level_mm / 304.8
                for bip in [
                    BuiltInParameter.INSTANCE_ELEVATION_PARAM,
                    BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM
                ]:
                    try:
                        p = instance.get_Parameter(bip)
                        if p and (not p.IsReadOnly):
                            p.Set(elev_ft)
                    except Exception:
                        pass

            # Set Model Properties parameters if provided
            if instance and model_props:
                try:
                    set_family_parameter(instance, "Dowel Offset", model_props.get("dowel_offset", 100.0))
                    set_family_parameter(instance, "Gap @ Top", model_props.get("gap_top", 100.0))
                    
                    # Try both possible names for C/P Joint Distance
                    cp_joint = model_props.get("cp_joint_distance", 150.0)
                    if not set_family_parameter(instance, "C/P Joint Distance", cp_joint):
                        set_family_parameter(instance, "CIP/Joint Distance", cp_joint)
                    
                    set_family_parameter(instance, "Embedded Bar Depth", model_props.get("embedded_depth", 800.0))
                    set_family_parameter(instance, "Embedded Bar Depth (X-Dir)", model_props.get("embedded_x", 500.0))
                    set_family_parameter(instance, "Embedded Bar Depth (Y-Dir)", model_props.get("embedded_y", 300.0))
                except Exception as e:
                    # Silently continue if parameter setting fails
                    pass

            if instance:
                placed.append(instance)

        except Exception as e:
            failed.append((pt, str(e)))

    return placed, failed


# ==============================================================================
# WPF WINDOW
# ==============================================================================

class DowelPlacerWindow(object):

    def __init__(self, xaml_path):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()

        self.all_families      = {}   # {name: Family}
        self.filtered_families = {}
        self.selected_family   = None
        self.selected_symbol   = None
        self.result            = False

        # ── Controls ───────────────────────────────────────────────────────
        self.headerDragArea    = self._window.FindName("headerDragArea")
        self.btnClose          = self._window.FindName("btnClose")
        self.txtFamilySearch   = self._window.FindName("txtFamilySearch")
        self.lstFamilies       = self._window.FindName("lstFamilies")
        self.lstTypes          = self._window.FindName("lstTypes")

        self.txtLeftOffset     = self._window.FindName("txtLeftOffset")
        self.txtRightOffset    = self._window.FindName("txtRightOffset")
        self.txtSpacing        = self._window.FindName("txtSpacing")
        self.txtVerticalOffset = self._window.FindName("txtVerticalOffset")
        self.txtRotation       = self._window.FindName("txtRotation")

        # Model Properties Parameters
        self.txtDowelOffset       = self._window.FindName("txtDowelOffset")
        self.txtGapTop            = self._window.FindName("txtGapTop")
        self.txtCPJointDistance   = self._window.FindName("txtCPJointDistance")
        self.txtEmbeddedBarDepth  = self._window.FindName("txtEmbeddedBarDepth")
        self.txtEmbeddedDepthX    = self._window.FindName("txtEmbeddedDepthX")
        self.txtEmbeddedDepthY    = self._window.FindName("txtEmbeddedDepthY")

        self.txtSelectedFamily = self._window.FindName("txtSelectedFamily")
        self.txtSelectedType   = self._window.FindName("txtSelectedType")
        self.txtEstimatedCount = self._window.FindName("txtEstimatedCount")

        self.txtStatus         = self._window.FindName("txtStatus")
        self.btnCancel         = self._window.FindName("btnCancel")
        self.btnPickFace       = self._window.FindName("btnPickFace")

        # ── Setup ──────────────────────────────────────────────────────────
        self.LoadFamilies()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    # ── Drag ───────────────────────────────────────────────────────────────

    def OnHeaderDrag(self, sender, args):
        self._window.DragMove()

    # ── Data loading ───────────────────────────────────────────────────────

    def LoadFamilies(self):
        self.all_families = get_all_loadable_families()
        self.RefreshFamilyList("")

    def RefreshFamilyList(self, search_text):
        self.lstFamilies.Items.Clear()
        search = search_text.lower()
        self.filtered_families = {
            k: v for k, v in sorted(self.all_families.items())
            if not search or search in k.lower()
        }
        for name in self.filtered_families:
            self.lstFamilies.Items.Add(name)

        count = len(self.filtered_families)
        self.txtStatus.Text = "{} families loaded".format(count)

    def PopulateTypes(self, family):
        self.lstTypes.Items.Clear()
        for type_name, sym in get_types_for_family(family):
            self.lstTypes.Items.Add(type_name)
        if self.lstTypes.Items.Count == 1:
            self.lstTypes.SelectedIndex = 0

    # ── Event handlers ─────────────────────────────────────────────────────

    def SetupEventHandlers(self):
        self.btnClose.Click              += self.OnClose
        self.btnCancel.Click             += self.OnClose
        self.txtFamilySearch.TextChanged += self.OnSearchChanged
        self.lstFamilies.SelectionChanged+= self.OnFamilySelected
        self.lstTypes.SelectionChanged   += self.OnTypeSelected
        self.btnPickFace.Click           += self.OnPickFace

    def OnClose(self, sender, args):
        self._window.DialogResult = False
        self._window.Close()

    def OnSearchChanged(self, sender, args):
        self.RefreshFamilyList(self.txtFamilySearch.Text or "")

    def OnFamilySelected(self, sender, args):
        sel = self.lstFamilies.SelectedItem
        if sel is None:
            return
        family = self.filtered_families.get(sel)
        if family is None:
            return
        self.selected_family = family
        self.selected_symbol = None
        self.txtSelectedFamily.Text = sel
        self.txtSelectedType.Text   = ""
        self.PopulateTypes(family)
        self.UpdatePickButton()

    def OnTypeSelected(self, sender, args):
        sel = self.lstTypes.SelectedItem
        if sel is None or self.selected_family is None:
            return
        # Find the matching symbol
        for type_name, sym in get_types_for_family(self.selected_family):
            if type_name == sel:
                self.selected_symbol = sym
                self.txtSelectedType.Text = type_name
                break
        self.UpdatePickButton()

    def UpdatePickButton(self):
        ready = self.selected_symbol is not None
        self.btnPickFace.IsEnabled = ready
        if ready:
            self.txtStatus.Text = "Ready — click PICK FACE & PLACE to continue"
        else:
            self.txtStatus.Text = "Select a family and type to continue"

    # ── Main action ────────────────────────────────────────────────────────

    def OnPickFace(self, sender, args):
        """Validate inputs, hide window, pick face, place dowels."""
        # Validate
        left_mm  = safe_float(self.txtLeftOffset.Text,     150.0)
        right_mm = safe_float(self.txtRightOffset.Text,    150.0)
        spacing_mm = safe_float(self.txtSpacing.Text,      300.0)
        v_off_mm = safe_float(self.txtVerticalOffset.Text, 100.0)
        rot_deg  = safe_float(self.txtRotation.Text,         0.0)

        if spacing_mm <= 0:
            forms.alert("Spacing must be greater than 0.", title="Validation Error")
            return
        if left_mm < 0 or right_mm < 0:
            forms.alert("Offsets cannot be negative.", title="Validation Error")
            return

        # Store values and close UI — let user pick face
        self._window.Hide()

        try:
            self._PickAndPlace(left_mm, right_mm, spacing_mm, v_off_mm, rot_deg)
        except Exception as e:
            import traceback
            output.print_md("## ❌ Error")
            output.print_md("```\n{}\n```".format(traceback.format_exc()))
            forms.alert("Error: {}".format(str(e)), title="Error")
        finally:
            self._window.ShowDialog()

    def _PickAndPlace(self, left_mm, right_mm, spacing_mm, v_off_mm, rot_deg):
        """Internal: pick face(s) and place. Called with window hidden."""
        # ── Pick one or more faces ─────────────────────────────────────────
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Face,
                WallFaceFilter(),
                "Select one or more wall faces to place dowels"
            )
        except Exception:
            # User cancelled
            self.txtEstimatedCount.Text = "Pick cancelled"
            return
        
        if not refs or len(refs) == 0:
            self.txtEstimatedCount.Text = "Pick cancelled"
            return

        face_items = []
        total_positions = 0
        faces_with_no_positions = 0
        invalid_faces = 0

        # ── Resolve geometry and calculate positions per face ─────────────
        for ref in refs:
            wall = doc.GetElement(ref.ElementId)
            geo_obj = wall.GetGeometryObjectFromReference(ref)

            if not isinstance(geo_obj, Face):
                invalid_faces += 1
                continue

            face = geo_obj
            positions = calculate_dowel_positions(
                face, wall, left_mm, right_mm, spacing_mm, v_off_mm
            )

            if not positions:
                faces_with_no_positions += 1
                continue

            face_items.append((face, ref, wall, positions))
            total_positions += len(positions)

        if total_positions == 0:
            forms.alert(
                "No dowel positions could be calculated on selected faces.\n\n"
                "Check that Left Offset + Right Offset is less than wall length "
                "and Spacing is valid.",
                title="No Positions"
            )
            self.txtEstimatedCount.Text = "0 positions — check parameters"
            return

        self.txtEstimatedCount.Text = "{} dowels will be placed".format(total_positions)

        # ── Confirm ────────────────────────────────────────────────────────
        msg = (
            "Place {} dowels on {} face(s)?\n\n"
            "Family : {}\n"
            "Type   : {}\n\n"
            "Left Offset   : {} mm\n"
            "Right Offset  : {} mm\n"
            "Spacing       : {} mm\n"
            "Height        : {} mm"
        ).format(
            total_positions, len(face_items),
            self.selected_family.Name,
            Element.Name.GetValue(self.selected_symbol),
            int(left_mm), int(right_mm),
            int(spacing_mm), int(v_off_mm)
        )
        if faces_with_no_positions > 0 or invalid_faces > 0:
            msg += (
                "\n\nSkipped: {} face(s) with no valid positions, {} invalid face(s)"
                .format(faces_with_no_positions, invalid_faces)
            )

        result = TaskDialog.Show(
            "Confirm Placement", msg,
            TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
        )
        if result != TaskDialogResult.Yes:
            self.txtEstimatedCount.Text = "Placement cancelled"
            return

        # ── Place dowels in transaction ────────────────────────────────────
        placed_list = []
        failed_list = []

        # Gather Model Properties parameters
        model_props = {
            "dowel_offset": safe_float(self.txtDowelOffset.Text if self.txtDowelOffset else "", 100.0),
            "gap_top": safe_float(self.txtGapTop.Text if self.txtGapTop else "", 100.0),
            "cp_joint_distance": safe_float(self.txtCPJointDistance.Text if self.txtCPJointDistance else "", 150.0),
            "embedded_depth": safe_float(self.txtEmbeddedBarDepth.Text if self.txtEmbeddedBarDepth else "", 800.0),
            "embedded_x": safe_float(self.txtEmbeddedDepthX.Text if self.txtEmbeddedDepthX else "", 500.0),
            "embedded_y": safe_float(self.txtEmbeddedDepthY.Text if self.txtEmbeddedDepthY else "", 300.0),
        }

        with Transaction(doc, "Place Dowels on Wall Face") as t:
            t.Start()
            try:
                for face, ref, wall, positions in face_items:
                    p_list, f_list = place_dowels_on_face(
                        face, ref, wall,
                        self.selected_symbol,
                        positions,
                        rot_deg,
                        model_props,
                        v_off_mm
                    )
                    placed_list.extend(p_list)
                    failed_list.extend(f_list)
                t.Commit()
            except Exception as e:
                t.RollBack()
                raise

        # ── Report ─────────────────────────────────────────────────────────
        output.print_md("## ✅ Dowel Placement Complete")
        output.print_md("**Family** : {}".format(self.selected_family.Name))
        output.print_md("**Type**   : {}".format(
            Element.Name.GetValue(self.selected_symbol)))
        output.print_md("**Faces**  : {}".format(len(face_items)))
        output.print_md("---")
        output.print_md("**Placed** : {}".format(len(placed_list)))
        output.print_md("**Failed** : {}".format(len(failed_list)))

        if failed_list:
            output.print_md("### Failed positions:")
            for pt, err in failed_list:
                output.print_md("- ({:.3f}, {:.3f}, {:.3f}): {}".format(
                    pt.X, pt.Y, pt.Z, err))

        self.result = True

        # Update preview panel
        self.txtEstimatedCount.Text = "{} placed, {} failed".format(
            len(placed_list), len(failed_list)
        )

        # Keep window open for another placement
        self.txtStatus.Text = "✓ {} dowels placed successfully".format(
            len(placed_list)
        )

    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

script_dir = os.path.dirname(__file__)
xaml_path  = os.path.join(script_dir, "DowelPlacer.xaml")

if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

try:
    win = DowelPlacerWindow(xaml_path)
    win.ShowDialog()
except Exception as e:
    import traceback
    forms.alert("Error launching tool:\n\n{}".format(str(e)), title="Error")
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
