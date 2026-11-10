# -*- coding: utf-8 -*-
"""
Loop Placer  v2
Place loop families vertically on wall end faces or exterior face.
Family parameters auto-set after placement:
  Groove Height  = wall height  (always)
  C/C Spacing    = user input
  Loops Number   = auto (ceil(wall_h / spacing)) or manual
  From Start     = user input

Orientation fix
---------------
`NewFamilyInstance(Reference, XYZ, referenceDirection, FamilySymbol)`
  referenceDirection defines the family's LOCAL X direction on the face.
  On a vertical face the face plane contains the world Z axis.
  Passing Z-up (0,0,1) makes the family's X = vertical → its height
  axis becomes HORIZONTAL → family lies flat.

  Correct ref_dir for each face type
  ───────────────────────────────────
  • Exterior long face  (normal = wall.Orientation, horizontal)
      ref_dir = wall_direction (along wall length, horizontal)
      → family X = along wall → family height (Y) = vertical ✓

  • End face  (normal = ±wall_direction, horizontal)
      ref_dir = wall.Orientation (perpendicular to wall, horizontal)
      → family X = across wall → family height (Y) = vertical ✓
"""
__title__ = 'Loop\nPlacer'
__doc__   = 'Place loop families on wall faces with auto Groove Height and loop params'

import clr
import os
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import revit, script, forms
import System
import System.Windows.Media as Media
import System.Windows as SW
from System.Windows.Markup import XamlReader
from System.IO import StreamReader

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

MM_TO_FT = 1.0 / 304.8


# ==============================================================================
# WALL SELECTION FILTER
# ==============================================================================

class WallFilter(ISelectionFilter):
    def AllowElement(self, el):
        return isinstance(el, Wall)
    def AllowReference(self, ref, pos):
        return False


# ==============================================================================
# UTILITY
# ==============================================================================

def ft(mm_val):
    """Millimetres → feet."""
    return mm_val * MM_TO_FT


def mm_from_ft(ft_val):
    """Feet → millimetres (rounded)."""
    return ft_val / MM_TO_FT


def safe_float(text, default=0.0):
    try:
        return float(str(text).strip())
    except Exception:
        return default


def safe_int(text, default=0):
    try:
        return int(str(text).strip())
    except Exception:
        return default


# ==============================================================================
# FAMILY HELPERS
# ==============================================================================

def get_all_families():
    return {
        f.Name: f
        for f in FilteredElementCollector(doc).OfClass(Family).ToElements()
        if not f.IsInPlace
    }


def get_symbols(family):
    result = []
    for sid in family.GetFamilySymbolIds():
        sym = doc.GetElement(sid)
        if sym:
            try:
                name = sym.get_Parameter(
                    BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            except Exception:
                name = Element.Name.GetValue(sym)
            result.append((name or "Unnamed", sym))
    return sorted(result, key=lambda x: x[0])


def get_symbol_placement_mode(symbol):
    """
    Return tuple:
      (mode_key, placement_type_name)

    mode_key:
      - "face_ref"    : use face-reference overload (WorkPlaneBased)
      - "wall_hosted" : use wall-host overload (OneLevelBasedHosted)
      - "unsupported" : unsupported for this tool
    """
    try:
        fpt = symbol.Family.FamilyPlacementType
        fpt_name = str(fpt)
    except Exception:
        return "unsupported", "Unknown"

    if fpt == FamilyPlacementType.WorkPlaneBased:
        return "face_ref", fpt_name

    if fpt == FamilyPlacementType.OneLevelBasedHosted:
        return "wall_hosted", fpt_name

    return "unsupported", fpt_name


# ==============================================================================
# WALL GEOMETRY HELPERS
# ==============================================================================

def get_wall_height(wall):
    """Return wall height in feet using WALL_USER_HEIGHT_PARAM."""
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        if p:
            return p.AsDouble()
    except Exception:
        pass
    # Fallback via bounding box
    try:
        bb = wall.get_BoundingBox(None)
        if bb:
            return bb.Max.Z - bb.Min.Z
    except Exception:
        pass
    return 0.0


def get_base_elevation(wall):
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        if p:
            lvl = doc.GetElement(p.AsElementId())
            if lvl:
                return lvl.Elevation
    except Exception:
        pass
    return 0.0


def get_wall_level_id(wall):
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        if p:
            return p.AsElementId()
    except Exception:
        pass
    return ElementId.InvalidElementId


def get_wall_direction(wall):
    """Unit vector along wall length (start → end)."""
    curve = wall.Location.Curve
    return (curve.GetEndPoint(1) - curve.GetEndPoint(0)).Normalize()


def get_end_face_refs(wall):
    """
    Return (start_ref, end_ref) – the two vertical short end faces.
    Uses dot product of face normal with wall_direction:
      start face normal ≈ -wall_dir  (dot < -0.98)
      end   face normal ≈ +wall_dir  (dot > +0.98)
    """
    opts = Options()
    opts.ComputeReferences = True
    opts.DetailLevel       = ViewDetailLevel.Fine

    wall_dir  = get_wall_direction(wall)
    start_ref = end_ref = None

    for obj in wall.get_Geometry(opts):
        if not (isinstance(obj, Solid) and obj.Volume > 1e-9):
            continue
        for face in obj.Faces:
            if not isinstance(face, PlanarFace):
                continue
            dot = face.FaceNormal.DotProduct(wall_dir)
            if dot < -0.98 and start_ref is None:
                start_ref = face.Reference
            elif dot > 0.98 and end_ref is None:
                end_ref = face.Reference
        if start_ref and end_ref:
            break

    return start_ref, end_ref


def get_exterior_face_ref(wall):
    refs = HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)
    return refs[0] if refs and refs.Count > 0 else None


def get_side_face_ref(wall, side_key):
    layer = ShellLayerType.Exterior if side_key == "exterior" else ShellLayerType.Interior
    refs = HostObjectUtils.GetSideFaces(wall, layer)
    return refs[0] if refs and refs.Count > 0 else None


def get_planar_face_from_ref(face_ref):
    """Resolve a PlanarFace from a Reference. Returns None if unavailable."""
    try:
        host = doc.GetElement(face_ref.ElementId)
        if not host:
            return None
        face = host.GetGeometryObjectFromReference(face_ref)
        return face if isinstance(face, PlanarFace) else None
    except Exception:
        return None


def get_upward_ref_dir(face_ref, ref_dir):
    """
    Revit face-based placement builds local Y from:
      localY ~= faceNormal x referenceDirection
    Flip referenceDirection when needed so localY points upward ( +Z ).
    """
    if ref_dir is None:
        return None

    try:
        face = get_planar_face_from_ref(face_ref)
        if not face:
            return ref_dir

        x_dir = ref_dir.Normalize()
        y_dir = face.FaceNormal.Normalize().CrossProduct(x_dir)
        if y_dir.GetLength() > 1e-9 and y_dir.DotProduct(XYZ.BasisZ) < 0:
            return x_dir.Negate()
        return x_dir
    except Exception:
        return ref_dir


# ==============================================================================
# PLACEMENT POINT HELPERS
# ==============================================================================

def end_face_placement_point(wall, end_face_ref, inset_mm, base_z, side_key):
    """
    Point on an end face centred vertically at base_z,
    offset inward from the selected side (exterior/interior) by inset_mm.

    For an end face the inset moves the point across wall thickness:
      - exterior: from exterior face toward interior
      - interior: from interior face toward exterior
    """
    orient  = wall.Orientation          # points to exterior (horizontal)
    half_w  = wall.Width / 2.0         # half wall thickness in feet
    inset   = ft(inset_mm)

    # Get face centroid XY from the reference
    face = doc.GetElement(end_face_ref.ElementId)\
              .GetGeometryObjectFromReference(end_face_ref)
    bb   = face.GetBoundingBox()
    cu   = (bb.Min.U + bb.Max.U) / 2.0
    cv   = (bb.Min.V + bb.Max.V) / 2.0
    raw  = face.Evaluate(UV(cu, cv))

    # Position from selected side and move inward
    if side_key == "interior":
        side_sign = -1.0
        inward_sign = 1.0
    else:
        side_sign = 1.0
        inward_sign = -1.0
    x = raw.X + orient.X * (side_sign * half_w + inward_sign * inset)
    y = raw.Y + orient.Y * (side_sign * half_w + inward_sign * inset)
    return XYZ(x, y, base_z)


def side_face_placement_point(wall, offset_from_start_ft, base_z, side_key):
    """
    Point on selected long face (exterior/interior):
      XY  = wall start + offset along wall + half-width outward
      Z   = base_z  (family spans upward via Groove Height)
    """
    curve    = wall.Location.Curve
    start_pt = curve.GetEndPoint(0)
    wall_dir = get_wall_direction(wall)
    orient   = wall.Orientation
    half_w   = wall.Width / 2.0

    along = start_pt + wall_dir * offset_from_start_ft
    side_sign = 1.0 if side_key == "exterior" else -1.0
    x     = along.X + orient.X * half_w * side_sign
    y     = along.Y + orient.Y * half_w * side_sign
    return XYZ(x, y, base_z)


# ==============================================================================
# CORE PLACEMENT
# ==============================================================================

def activate_symbol(symbol):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def assign_level(inst, level_id):
    if level_id == ElementId.InvalidElementId:
        return
    for bip in [BuiltInParameter.FAMILY_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM]:
        try:
            p = inst.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(level_id)
        except Exception:
            pass


def set_param_by_name(inst, param_name, value_ft):
    """
    Set a DOUBLE instance parameter by its name (string lookup).
    value_ft is in feet for length params, unitless for integers.
    Returns True if successful.
    """
    for p in inst.Parameters:
        if p.Definition.Name == param_name:
            try:
                if p.StorageType == StorageType.Double:
                    p.Set(float(value_ft))
                    return True
                elif p.StorageType == StorageType.Integer:
                    p.Set(int(round(value_ft)))
                    return True
            except Exception:
                pass
    return False


def place_instance(symbol, wall, placement_mode, placement_pt, face_ref=None, ref_dir=None):
    """
    Placement wrapper for supported family modes.
    """
    if placement_mode == "face_ref":
        adjusted_ref_dir = get_upward_ref_dir(face_ref, ref_dir)
        return doc.Create.NewFamilyInstance(
            face_ref, placement_pt, adjusted_ref_dir, symbol
        )

    if placement_mode == "wall_hosted":
        return doc.Create.NewFamilyInstance(
            placement_pt, symbol, wall, StructuralType.NonStructural
        )

    raise Exception("Unsupported placement mode: {}".format(placement_mode))


def post_set_params(inst, wall_height_ft, spacing_ft, loops_n, from_start_ft):
    """
    Set all known loop family parameters on the placed instance.
    Uses string-name lookup so it works regardless of parameter ID.
    """
    # Groove Height = full wall height
    for name in ["Groove Height", "GrooveHeight", "Height"]:
        if set_param_by_name(inst, name, wall_height_ft):
            break

    # C/C Spacing
    for name in ["C/C Spacing", "CC Spacing", "Spacing"]:
        if set_param_by_name(inst, name, spacing_ft):
            break

    # Loops Number (integer)
    for name in ["Loops Number", "LoopsNumber", "NumberOfLoops", "Loop Count"]:
        if set_param_by_name(inst, name, loops_n):
            break

    # From Start
    for name in ["From Start", "FromStart", "Start Offset"]:
        if set_param_by_name(inst, name, from_start_ft):
            break


def set_elevation_from_level(inst, elev_ft):
    # Try common built-ins first, then family parameter names.
    for bip in [BuiltInParameter.INSTANCE_ELEVATION_PARAM,
                BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM]:
        try:
            p = inst.get_Parameter(bip)
            if p and not p.IsReadOnly and p.StorageType == StorageType.Double:
                p.Set(float(elev_ft))
        except Exception:
            pass

    for name in ["Elevation from Level", "Elevation", "Offset from Level"]:
        if set_param_by_name(inst, name, elev_ft):
            break


# ==============================================================================
# THREE CONDITIONS
# ==============================================================================

def do_condition1(wall, symbol, placement_mode, start_inset_mm, end_inset_mm,
                  wall_h_ft, spacing_ft, loops_n, from_start_ft,
                  elev_from_level_ft, offset_side_key):
    """
    Condition 1 — Both end faces.
    ref_dir = wall.Orientation  (across the wall, horizontal)
    → family height (Y axis) stands vertical.
    """
    start_ref, end_ref = get_end_face_refs(wall)
    if not start_ref or not end_ref:
        return [], ["Could not find end face references"]

    base_z   = get_base_elevation(wall) + elev_from_level_ft
    level_id = get_wall_level_id(wall)
    orient   = wall.Orientation    # horizontal, perpendicular to wall direction

    placed = []
    failed = []

    configs = [
        (start_ref, start_inset_mm, "start"),
        (end_ref,   end_inset_mm,   "end"),
    ]

    for ref, inset_mm, label in configs:
        try:
            pt   = end_face_placement_point(wall, ref, inset_mm, base_z, offset_side_key)
            inst = place_instance(
                symbol, wall, placement_mode, pt,
                face_ref=ref, ref_dir=orient
            )
            assign_level(inst, level_id)
            post_set_params(inst, wall_h_ft, spacing_ft, loops_n, from_start_ft)
            set_elevation_from_level(inst, elev_from_level_ft)
            placed.append(inst)
        except Exception as e:
            failed.append("{} end [{}]: {}".format(label, placement_mode, str(e)))

    return placed, failed


def do_condition2(wall, symbol, placement_mode, left_offset_mm, right_offset_mm,
                  wall_h_ft, spacing_ft, loops_n, from_start_ft,
                  elev_from_level_ft, offset_side_key):
    """
    Condition 2 — Both on selected long side face.
    ref_dir = wall_direction  (along wall length, horizontal)
    → family height (Y axis) stands vertical.
    """
    curve    = wall.Location.Curve
    length   = curve.Length          # feet
    base_z   = get_base_elevation(wall) + elev_from_level_ft
    level_id = get_wall_level_id(wall)
    wall_dir = get_wall_direction(wall)
    face_ref = None
    if placement_mode == "face_ref":
        face_ref = get_side_face_ref(wall, offset_side_key)
        if not face_ref:
            return [], ["Could not get {} face reference".format(offset_side_key)]

    placed = []
    failed = []

    configs = [
        (ft(left_offset_mm),          "left"),
        (length - ft(right_offset_mm), "right"),
    ]

    for offset_ft, label in configs:
        try:
            pt   = side_face_placement_point(wall, offset_ft, base_z, offset_side_key)
            inst = place_instance(
                symbol, wall, placement_mode, pt,
                face_ref=face_ref, ref_dir=wall_dir
            )
            assign_level(inst, level_id)
            post_set_params(inst, wall_h_ft, spacing_ft, loops_n, from_start_ft)
            set_elevation_from_level(inst, elev_from_level_ft)
            placed.append(inst)
        except Exception as e:
            failed.append("{} [{}]: {}".format(label, placement_mode, str(e)))

    return placed, failed


def do_condition3(wall, symbol, placement_mode, edge_at_start, edge_inset_mm, face_offset_mm,
                  wall_h_ft, spacing_ft, loops_n, from_start_ft,
                  elev_from_level_ft, offset_side_key):
    """
    Condition 3 — Mixed.
    Edge instance on chosen end face (ref_dir = wall.Orientation).
    Face instance on exterior long face (ref_dir = wall_direction).
    Face loop is near the OPPOSITE end.
    """
    start_ref, end_ref = get_end_face_refs(wall)
    if not start_ref or not end_ref:
        return [], ["Could not find end face references"]

    face_ref = None
    if placement_mode == "face_ref":
        face_ref = get_side_face_ref(wall, offset_side_key)
        if not face_ref:
            return [], ["Could not get {} face reference".format(offset_side_key)]

    curve    = wall.Location.Curve
    length   = curve.Length
    base_z   = get_base_elevation(wall) + elev_from_level_ft
    level_id = get_wall_level_id(wall)
    orient   = wall.Orientation
    wall_dir = get_wall_direction(wall)

    placed = []
    failed = []

    # ── Edge loop ──────────────────────────────────────────────────────
    edge_ref = start_ref if edge_at_start else end_ref
    try:
        pt   = end_face_placement_point(
            wall, edge_ref, edge_inset_mm, base_z, offset_side_key
        )
        inst = place_instance(
            symbol, wall, placement_mode, pt,
            face_ref=edge_ref, ref_dir=orient
        )
        assign_level(inst, level_id)
        post_set_params(inst, wall_h_ft, spacing_ft, loops_n, from_start_ft)
        set_elevation_from_level(inst, elev_from_level_ft)
        placed.append(inst)
    except Exception as e:
        failed.append("edge [{}]: {}".format(placement_mode, str(e)))

    # ── Face loop — at opposite end ────────────────────────────────────
    if edge_at_start:
        face_off = length - ft(face_offset_mm)   # near finish end
    else:
        face_off = ft(face_offset_mm)            # near start end

    try:
        pt   = side_face_placement_point(wall, face_off, base_z, offset_side_key)
        inst = place_instance(
            symbol, wall, placement_mode, pt,
            face_ref=face_ref, ref_dir=wall_dir
        )
        assign_level(inst, level_id)
        post_set_params(inst, wall_h_ft, spacing_ft, loops_n, from_start_ft)
        set_elevation_from_level(inst, elev_from_level_ft)
        placed.append(inst)
    except Exception as e:
        failed.append("face [{}]: {}".format(placement_mode, str(e)))

    return placed, failed


# ==============================================================================
# WPF WINDOW
# ==============================================================================

class LoopPlacerWindow(object):

    def __init__(self, xaml_path):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()

        self.selected_wall     = None
        self.selected_walls    = []
        self.wall_height_ft    = 0.0
        self.all_families      = {}
        self.filtered_families = {}
        self.selected_symbol   = None
        self.result            = False

        # ── Controls ──────────────────────────────────────────────────────
        self.headerDragArea   = self._window.FindName("headerDragArea")
        self.btnClose         = self._window.FindName("btnClose")
        self.btnSelectWall    = self._window.FindName("btnSelectWall")
        self.txtWallName      = self._window.FindName("txtWallName")
        self.txtWallDetails   = self._window.FindName("txtWallDetails")
        self.txtWallHeightInfo= self._window.FindName("txtWallHeightInfo")

        self.txtFamilySearch  = self._window.FindName("txtFamilySearch")
        self.cmbFamily        = self._window.FindName("cmbFamily")
        self.cmbType          = self._window.FindName("cmbType")

        self.txtGrooveHeight  = self._window.FindName("txtGrooveHeight")
        self.txtSpacing       = self._window.FindName("txtSpacing")
        self.txtLoopsNumber   = self._window.FindName("txtLoopsNumber")
        self.chkAutoLoops     = self._window.FindName("chkAutoLoops")
        self.txtFromStart     = self._window.FindName("txtFromStart")
        self.txtElevFromLevel = self._window.FindName("txtElevFromLevel")
        self.rbOffsetExterior = self._window.FindName("rbOffsetExterior")
        self.rbOffsetInterior = self._window.FindName("rbOffsetInterior")

        self.rbCond1          = self._window.FindName("rbCond1")
        self.rbCond2          = self._window.FindName("rbCond2")
        self.rbCond3          = self._window.FindName("rbCond3")
        self.pnlCond1         = self._window.FindName("pnlCond1")
        self.pnlCond2         = self._window.FindName("pnlCond2")
        self.pnlCond3         = self._window.FindName("pnlCond3")

        self.txtC1StartInset  = self._window.FindName("txtC1StartInset")
        self.txtC1EndInset    = self._window.FindName("txtC1EndInset")
        self.txtC2LeftOffset  = self._window.FindName("txtC2LeftOffset")
        self.txtC2RightOffset = self._window.FindName("txtC2RightOffset")
        self.rbC3EdgeStart    = self._window.FindName("rbC3EdgeStart")
        self.rbC3EdgeEnd      = self._window.FindName("rbC3EdgeEnd")
        self.txtC3EdgeInset   = self._window.FindName("txtC3EdgeInset")
        self.txtC3FaceOffset  = self._window.FindName("txtC3FaceOffset")

        self.txtSummaryWall      = self._window.FindName("txtSummaryWall")
        self.txtSummaryFamily    = self._window.FindName("txtSummaryFamily")
        self.txtSummaryCondition = self._window.FindName("txtSummaryCondition")
        self.txtSummaryHeight    = self._window.FindName("txtSummaryHeight")
        self.txtSummarySpacing   = self._window.FindName("txtSummarySpacing")
        self.txtSummaryLoops     = self._window.FindName("txtSummaryLoops")
        self.txtStatus           = self._window.FindName("txtStatus")
        self.btnCancel           = self._window.FindName("btnCancel")
        self.btnPlace            = self._window.FindName("btnPlace")

        # ── Setup ─────────────────────────────────────────────────────────
        self.SetupEventHandlers()
        self.all_families = get_all_families()
        self.RefreshFamilyList("")
        self.UpdateSummary()
        self.headerDragArea.MouseLeftButtonDown += self.OnDrag

    # ── Drag ──────────────────────────────────────────────────────────────

    def OnDrag(self, sender, args):
        try:
            self._window.DragMove()
        except Exception:
            pass

    # ── Event wiring ──────────────────────────────────────────────────────

    def SetupEventHandlers(self):
        self.btnClose.Click             += self.OnClose
        self.btnCancel.Click            += self.OnClose
        self.btnSelectWall.Click        += self.OnSelectWall
        self.txtFamilySearch.TextChanged+= self.OnSearchChanged
        self.cmbFamily.SelectionChanged += self.OnFamilyChanged
        self.cmbType.SelectionChanged   += self.OnTypeChanged
        self.rbCond1.Checked            += self.OnConditionChanged
        self.rbCond2.Checked            += self.OnConditionChanged
        self.rbCond3.Checked            += self.OnConditionChanged
        self.txtSpacing.TextChanged     += self.OnSpacingChanged
        self.txtElevFromLevel.TextChanged += self.OnElevationChanged
        self.chkAutoLoops.Checked       += self.OnAutoLoopsChanged
        self.chkAutoLoops.Unchecked     += self.OnAutoLoopsChanged
        self.rbOffsetExterior.Checked   += lambda s, e: self.UpdateSummary()
        self.rbOffsetInterior.Checked   += lambda s, e: self.UpdateSummary()
        self.txtLoopsNumber.TextChanged += lambda s, e: self.UpdateSummary()
        self.btnPlace.Click             += self.OnPlace

    def OnClose(self, sender, args):
        self._window.DialogResult = False
        self._window.Close()

    # ── Wall selection ────────────────────────────────────────────────────

    def OnSelectWall(self, sender, args):
        self._window.Hide()
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element,
                WallFilter(),
                "Select one or more walls to place loops on"
            )
            walls = []
            for ref in refs:
                wall = doc.GetElement(ref.ElementId)
                if isinstance(wall, Wall):
                    walls.append(wall)

            if walls:
                self.selected_walls = walls
                self.selected_wall  = walls[0]
                self.wall_height_ft = get_wall_height(self.selected_wall)
                self.ShowWallInfo(self.selected_wall)
        except Exception:
            pass
        finally:
            self._window.ShowDialog()

    def ShowWallInfo(self, wall):
        curve    = wall.Location.Curve
        length_m = curve.Length * 0.3048        # ft → m
        h_mm     = self.wall_height_ft / MM_TO_FT
        count    = len(self.selected_walls) if self.selected_walls else 1

        try:
            lvl_id   = wall.get_Parameter(
                BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
            lvl_name = doc.GetElement(lvl_id).Name
        except Exception:
            lvl_name = "Unknown"

        if count > 1:
            self.txtWallName.Text = "{} wall(s) selected  (first: ID {})".format(
                count, wall.Id.IntegerValue)
        else:
            self.txtWallName.Text = "{}  (ID: {})".format(
                wall.Name, wall.Id.IntegerValue)
        self.txtWallName.Foreground = Media.Brushes.LightGreen
        self.txtWallDetails.Text    = "Length: {:.3f} m   Level: {}".format(
            length_m, lvl_name)
        self.txtWallHeightInfo.Text = "Groove Height: {:.0f} mm (auto)".format(h_mm)

        # Update Groove Height display
        self.txtGrooveHeight.Text = "{:.0f}".format(h_mm)

        self.RecalcAutoLoops()
        self.UpdateSummary()
        self.UpdatePlaceButton()

    # ── Family list ───────────────────────────────────────────────────────

    def RefreshFamilyList(self, search):
        self.cmbFamily.Items.Clear()
        s = search.lower()
        self.filtered_families = {
            k: v for k, v in sorted(self.all_families.items())
            if not s or s in k.lower()
        }
        for name in self.filtered_families:
            self.cmbFamily.Items.Add(name)
        if self.cmbFamily.Items.Count > 0:
            self.cmbFamily.SelectedIndex = 0

    def OnSearchChanged(self, sender, args):
        self.RefreshFamilyList(self.txtFamilySearch.Text or "")

    def OnFamilyChanged(self, sender, args):
        self.cmbType.Items.Clear()
        if self.cmbFamily.SelectedIndex < 0:
            return
        name = self.cmbFamily.SelectedItem
        fam  = self.filtered_families.get(name)
        if not fam:
            return
        for tname, _ in get_symbols(fam):
            self.cmbType.Items.Add(tname)
        if self.cmbType.Items.Count > 0:
            self.cmbType.SelectedIndex = 0
        self.UpdateSummary()
        self.UpdatePlaceButton()

    def OnTypeChanged(self, sender, args):
        self.selected_symbol = None
        if self.cmbFamily.SelectedIndex < 0 or self.cmbType.SelectedIndex < 0:
            return
        fam  = self.filtered_families.get(self.cmbFamily.SelectedItem)
        tsel = self.cmbType.SelectedItem
        if fam:
            for tname, sym in get_symbols(fam):
                if tname == tsel:
                    self.selected_symbol = sym
                    break
        self.UpdateSummary()
        self.UpdatePlaceButton()

    # ── Condition panel switch ─────────────────────────────────────────────

    def OnConditionChanged(self, sender, args):
        self.pnlCond1.Visibility = SW.Visibility.Collapsed
        self.pnlCond2.Visibility = SW.Visibility.Collapsed
        self.pnlCond3.Visibility = SW.Visibility.Collapsed
        if self.rbCond1.IsChecked:
            self.pnlCond1.Visibility = SW.Visibility.Visible
        elif self.rbCond2.IsChecked:
            self.pnlCond2.Visibility = SW.Visibility.Visible
        else:
            self.pnlCond3.Visibility = SW.Visibility.Visible
        self.UpdateSummary()

    def active_condition(self):
        if self.rbCond1.IsChecked:
            return 1
        if self.rbCond2.IsChecked:
            return 2
        return 3

    # ── Loop params ───────────────────────────────────────────────────────

    def OnSpacingChanged(self, sender, args):
        self.RecalcAutoLoops()
        self.UpdateSummary()

    def OnElevationChanged(self, sender, args):
        self.RecalcAutoLoops()
        self.UpdateSummary()

    def OnAutoLoopsChanged(self, sender, args):
        """Enable/disable the manual loops number textbox."""
        is_auto = bool(self.chkAutoLoops.IsChecked)
        self.txtLoopsNumber.IsEnabled = not is_auto
        if is_auto:
            self.RecalcAutoLoops()
        self.UpdateSummary()

    def RecalcAutoLoops(self):
        """If Auto, compute Loops Number = ceil(wall_height / spacing)."""
        if not bool(self.chkAutoLoops.IsChecked):
            return
        eff_h_ft = self.get_effective_height_ft(self.wall_height_ft)
        if eff_h_ft <= 0:
            self.txtLoopsNumber.Text = "0"
            return
        spacing_mm = safe_float(self.txtSpacing.Text, 600.0)
        if spacing_mm <= 0:
            return
        spacing_ft = ft(spacing_mm)
        loops = int(math.ceil(eff_h_ft / spacing_ft))
        self.txtLoopsNumber.Text = str(max(1, loops))

    def get_loops_number(self):
        return safe_int(self.txtLoopsNumber.Text, 1)

    def get_elevation_from_level_ft(self):
        elev_mm = safe_float(self.txtElevFromLevel.Text, 0.0)
        return ft(elev_mm)

    def get_effective_height_ft(self, wall_h_ft):
        return max(0.0, wall_h_ft - self.get_elevation_from_level_ft())

    def get_offset_side_key(self):
        return "interior" if bool(self.rbOffsetInterior.IsChecked) else "exterior"

    # ── Summary / button ─────────────────────────────────────────────────

    def UpdateSummary(self):
        h_mm      = mm_from_ft(self.wall_height_ft)
        eff_h_mm  = mm_from_ft(self.get_effective_height_ft(self.wall_height_ft))
        spacing_mm= safe_float(self.txtSpacing.Text, 600.0)
        loops_n   = self.get_loops_number()
        cond      = self.active_condition()
        elev_mm   = safe_float(self.txtElevFromLevel.Text, 0.0)
        side_label = "Interior" if self.get_offset_side_key() == "interior" else "Exterior"

        self.txtSummaryWall.Text = "Wall: {}".format(
            "{} selected".format(len(self.selected_walls))
            if self.selected_walls else "—")
        self.txtSummaryFamily.Text = (
            "Family: {} — {}".format(
                self.cmbFamily.SelectedItem, self.cmbType.SelectedItem)
            if (self.cmbFamily.SelectedIndex >= 0 and
                self.cmbType.SelectedIndex >= 0)
            else "Family: —"
        )
        cond_labels = {
            1: "1 — Both End Faces",
            2: "2 — Both on Side Face",
            3: "3 — Mixed (Edge + Face)"
        }
        self.txtSummaryCondition.Text = "Condition: {}".format(
            cond_labels[cond])
        self.txtSummaryHeight.Text = (
            "Groove Height: {:.0f} mm  |  Elev: {:.0f} mm  |  Side: {}".format(
                eff_h_mm, elev_mm, side_label)
            if h_mm > 0 else "Groove Height: — (select wall)")
        self.txtSummarySpacing.Text = "C/C Spacing: {:.0f} mm".format(
            spacing_mm)
        self.txtSummaryLoops.Text = "Loops Number: {}  (2 instances)".format(
            loops_n)

    def UpdatePlaceButton(self):
        ready = (len(self.selected_walls) > 0 and
                 self.selected_symbol is not None)
        self.btnPlace.IsEnabled = ready
        if ready:
            self.txtStatus.Text = "Ready — click PLACE LOOPS"
        elif len(self.selected_walls) == 0:
            self.txtStatus.Text = "Select one or more walls to begin"
        else:
            self.txtStatus.Text = "Select a family and type"

    # ── Placement ────────────────────────────────────────────────────────

    def OnPlace(self, sender, args):
        if len(self.selected_walls) == 0 or not self.selected_symbol:
            forms.alert("Wall and family must be selected.", title="Error")
            return

        cond       = self.active_condition()
        spacing_mm = safe_float(self.txtSpacing.Text,  600.0)
        loops_n    = self.get_loops_number()
        from_s_mm  = safe_float(self.txtFromStart.Text, 300.0)
        elev_mm    = safe_float(self.txtElevFromLevel.Text, 0.0)
        elev_ft    = ft(elev_mm)
        offset_side_key = self.get_offset_side_key()
        wall_h_ft  = self.get_effective_height_ft(self.wall_height_ft)
        spacing_ft = ft(spacing_mm)
        from_s_ft  = ft(from_s_mm)
        h_mm       = mm_from_ft(wall_h_ft)

        placement_mode, placement_type_name = get_symbol_placement_mode(
            self.selected_symbol)
        if placement_mode == "unsupported":
            forms.alert(
                "Selected family type is not supported by this tool.\n\n"
                "FamilyPlacementType: {}\n\n"
                "Supported:\n"
                " - WorkPlaneBased\n"
                " - OneLevelBasedHosted (wall-hosted)".format(
                    placement_type_name),
                title="Unsupported Family Type"
            )
            self.btnPlace.IsEnabled = True
            return

        # Build confirm text
        cond_labels = {
            1: "Condition 1 — Both End Faces",
            2: "Condition 2 — Both on Side Face",
            3: "Condition 3 — Mixed (Edge + Face)"
        }
        msg = (
            "Place loops on wall:\n"
            "  {} wall(s)\n\n"
            "Family         : {} — {}\n"
            "Placement Mode : {}  ({})\n"
            "Groove Height  : {:.0f} mm  (wall height, auto)\n"
            "Elev from Level: {:.0f} mm\n"
            "Offset Side    : {}\n"
            "C/C Spacing    : {:.0f} mm\n"
            "Loops Number   : {}\n"
            "From Start     : {:.0f} mm\n\n"
            "{}"
        ).format(
            len(self.selected_walls),
            self.cmbFamily.SelectedItem,
            self.cmbType.SelectedItem,
            placement_mode, placement_type_name,
            h_mm, elev_mm, offset_side_key.title(),
            spacing_mm, loops_n, from_s_mm,
            cond_labels[cond]
        )

        if not forms.alert(msg, yes=True, no=True, title="Confirm Placement"):
            return

        self.btnPlace.IsEnabled = False
        self.txtStatus.Text     = "Placing loops…"

        placed = []
        failed = []

        with revit.Transaction("Place Loops"):
            activate_symbol(self.selected_symbol)

            for wall in self.selected_walls:
                # Use FULL wall height for Groove Height parameter (don't deduct elevation)
                full_wall_h_ft = get_wall_height(wall)
                
                # Use effective height (wall height - elevation) for loops calculation only
                effective_h_ft = self.get_effective_height_ft(full_wall_h_ft)
                
                loops_n_wall = loops_n
                if bool(self.chkAutoLoops.IsChecked) and spacing_ft > 0:
                    loops_n_wall = max(1, int(math.ceil(effective_h_ft / spacing_ft)))

                wall_placed = []
                wall_failed = []

                if cond == 1:
                    si = safe_float(self.txtC1StartInset.Text, 50.0)
                    ei = safe_float(self.txtC1EndInset.Text,   50.0)
                    wall_placed, wall_failed = do_condition1(
                        wall, self.selected_symbol, placement_mode,
                        si, ei,
                        full_wall_h_ft, spacing_ft, loops_n_wall, from_s_ft,
                        elev_ft, offset_side_key)

                elif cond == 2:
                    lo = safe_float(self.txtC2LeftOffset.Text,  300.0)
                    ro = safe_float(self.txtC2RightOffset.Text, 300.0)
                    wall_placed, wall_failed = do_condition2(
                        wall, self.selected_symbol, placement_mode,
                        lo, ro,
                        full_wall_h_ft, spacing_ft, loops_n_wall, from_s_ft,
                        elev_ft, offset_side_key)

                else:
                    edge_start = bool(self.rbC3EdgeStart.IsChecked)
                    ei = safe_float(self.txtC3EdgeInset.Text,  50.0)
                    fo = safe_float(self.txtC3FaceOffset.Text, 300.0)
                    wall_placed, wall_failed = do_condition3(
                        wall, self.selected_symbol, placement_mode,
                        edge_start, ei, fo,
                        full_wall_h_ft, spacing_ft, loops_n_wall, from_s_ft,
                        elev_ft, offset_side_key)

                placed.extend(wall_placed)
                for f in wall_failed:
                    failed.append("Wall ID {}: {}".format(
                        wall.Id.IntegerValue, f))

        # ── Report ────────────────────────────────────────────────────────
        result_msg = "Placed {} loop instance(s).".format(len(placed))
        if failed:
            result_msg += "\n\nFailed ({}):\n{}".format(
                len(failed), "\n".join(failed))
        forms.alert(result_msg, title="Placement Complete")

        output.print_md("## ✅ Loop Placement Complete")
        output.print_md("**Wall**          : {}  (ID {})".format(
            "{} selected".format(len(self.selected_walls)),
            self.selected_walls[0].Id.IntegerValue if self.selected_walls else -1))
        output.print_md("**Family**        : {} — {}".format(
            self.cmbFamily.SelectedItem, self.cmbType.SelectedItem))
        output.print_md("**Condition**     : {}".format(cond))
        output.print_md("**Placement Mode**: {} ({})".format(
            placement_mode, placement_type_name))
        output.print_md("**Groove Height** : {:.0f} mm  (wall height - elevation)".format(h_mm))
        output.print_md("**Elevation**     : {:.0f} mm".format(elev_mm))
        output.print_md("**Offset Side**   : {}".format(offset_side_key.title()))
        output.print_md("**C/C Spacing**   : {:.0f} mm".format(spacing_mm))
        output.print_md("**Loops Number**  : {}".format(loops_n))
        output.print_md("**From Start**    : {:.0f} mm".format(from_s_mm))
        output.print_md("**Placed**        : {}".format(len(placed)))
        output.print_md("**Failed**        : {}".format(len(failed)))
        for f in failed:
            output.print_md("  - {}".format(f))

        self.result             = True
        self.btnPlace.IsEnabled = True
        self.txtStatus.Text     = "✓ {} instance(s) placed".format(len(placed))

    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

script_dir = os.path.dirname(__file__)
xaml_path  = os.path.join(script_dir, "LoopPlacer.xaml")

if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\n{}".format(xaml_path),
        title="File Not Found", exitscript=True
    )

try:
    win = LoopPlacerWindow(xaml_path)
    win.ShowDialog()
except Exception as ex:
    import traceback
    forms.alert("Error launching tool:\n\n{}".format(str(ex)), title="Error")
    output.print_md("```\n{}\n```".format(traceback.format_exc()))