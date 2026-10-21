# -*- coding: utf-8 -*-
"""
Place Void in Wall  -  BA Tools
================================

Workflow (crash-safe):
  1. User selects walls with PickObjects() on the MAIN THREAD.
  2. WPF dialog collects parameters only - NO Revit API calls inside handlers.
  3. After ShowDialog() returns, placement runs on the MAIN THREAD inside a
     TransactionGroup; per-wall transactions allow continue-on-error.

Side fix:
  After placing a face-hosted instance, we check whether the void's bounding-box
  centre is on the AIR side of the host face (sticking out of the wall) or on
  the WALL-SOLID side (correctly extruding into the wall body).  If on the air
  side, we FlipFacing once.  This works identically for Interior and Exterior
  faces and for any face-hosted family, regardless of how it was authored.
"""

import os
import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows import Visibility
from System.Collections.Generic import List

from pyrevit import forms, script

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ElementId,
    ElementTransformUtils, FamilyInstance, FamilyPlacementType, FamilySymbol,
    FilteredElementCollector, GeometryInstance, HostObjectUtils,
    InstanceVoidCutUtils, Level, Options, Plane, PlanarFace, ShellLayerType,
    Solid, StorageType, Transaction, TransactionGroup, UnitTypeId, UnitUtils,
    UV, Wall, XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc    = __revit__.ActiveUIDocument.Document
uidoc  = __revit__.ActiveUIDocument
output = script.get_output()
logger = script.get_logger()


# ── Unit helpers ──────────────────────────────────────────────────────────────
def to_ft(mm):
    return UnitUtils.ConvertToInternalUnits(float(mm), UnitTypeId.Millimeters)


def from_ft(val):
    return UnitUtils.ConvertFromInternalUnits(float(val), UnitTypeId.Millimeters)


def safe_float(text, default=None):
    try:
        return float((text or "").strip())
    except Exception:
        return default


def elem_name(elem, fallback=""):
    try:
        n = elem.Name
        if n:
            return n
    except Exception:
        pass
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME,
                BuiltInParameter.DATUM_TEXT):
        try:
            p = elem.get_Parameter(bip)
            if p and p.HasValue:
                v = p.AsString()
                if v:
                    return v
        except Exception:
            continue
    return fallback


# ── Data collectors ───────────────────────────────────────────────────────────
def get_levels():
    return sorted(
        FilteredElementCollector(doc).OfClass(Level).ToElements(),
        key=lambda l: l.Elevation,
    )


def get_wall_length_mm(wall):
    p = wall.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
    if p and p.HasValue:
        return from_ft(p.AsDouble())
    try:
        return from_ft(wall.Location.Curve.Length)
    except Exception:
        return 0.0


def collect_families():
    """Return {family_name: {type_name: symbol_id_int}} for face-hosted Generic Models.

    Restricted to ``WorkPlaneBased`` (Generic Model face based.rft).  Wall-hosted
    or level-hosted templates use a different placement API and would not behave
    correctly with the face-reference call we use below.
    """
    syms = (FilteredElementCollector(doc)
            .OfClass(FamilySymbol)
            .OfCategory(BuiltInCategory.OST_GenericModel)
            .WhereElementIsElementType()
            .ToElements())
    fams = {}
    for sym in syms:
        try:
            fam = sym.Family
            if fam is None:
                continue
            if fam.FamilyPlacementType != FamilyPlacementType.WorkPlaneBased:
                continue
            fn = elem_name(fam, "Family_{}".format(fam.Id.IntegerValue))
            tn = elem_name(sym, "Type_{}".format(sym.Id.IntegerValue))
            fams.setdefault(fn, {})[tn] = sym.Id.IntegerValue
        except Exception:
            continue
    return {fn: dict(sorted(tv.items())) for fn, tv in sorted(fams.items())}


# ── Wall selection filter ─────────────────────────────────────────────────────
class WallFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Wall)
    def AllowReference(self, reference, point):
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  WPF Dialog  -  pure UI, zero Revit API
# ══════════════════════════════════════════════════════════════════════════════
class ConfigDialog(forms.WPFWindow):

    def __init__(self, xaml_path, walls, families, levels):
        forms.WPFWindow.__init__(self, xaml_path)
        self.walls          = list(walls)
        self.families       = families
        self.levels         = levels
        self._type_map      = {}
        self._all_fam_names = list(families.keys())
        self.result         = None

        self.btnPickWalls.Click += self._on_pick_walls
        self.txtFamSearch.TextChanged += self._on_family_search
        self.cmbFamily.SelectionChanged += self._on_family_changed
        self.cmbType.SelectionChanged   += lambda s, e: self._refresh_summary()
        self.cmbLevel.SelectionChanged  += lambda s, e: self._refresh_summary()
        self.txtElevation.TextChanged   += lambda s, e: self._refresh_summary()
        self.txtHeight.TextChanged      += lambda s, e: self._refresh_summary()
        self.rbInterior.Checked += lambda s, e: self._refresh_summary()
        self.rbExterior.Checked += lambda s, e: self._refresh_summary()
        self.chkAutoCut.Checked    += lambda s, e: self._refresh_summary()
        self.chkAutoCut.Unchecked  += lambda s, e: self._refresh_summary()
        self.chkMatchWS.Checked    += lambda s, e: self._refresh_summary()
        self.chkMatchWS.Unchecked  += lambda s, e: self._refresh_summary()
        self.btnPlace.Click  += self._on_place
        self.btnCancel.Click += self._on_cancel
        self.btnClose.Click  += self._on_cancel

        self._populate_walls()
        self._populate_families()
        self._populate_levels()
        self._refresh_summary()

    # ── Populate ─────────────────────────────────────────────────────────────
    def _populate_walls(self):
        self.lstWalls.Items.Clear()
        for w in self.walls:
            self.lstWalls.Items.Add(
                "{}   |   L = {:.0f} mm   |   Id {}".format(
                    elem_name(w, "Wall"), get_wall_length_mm(w), w.Id.IntegerValue
                )
            )
        n = len(self.walls)
        self.txtWallCount.Text = "{} wall{}".format(n, "" if n == 1 else "s")
        self.txtWallEmpty.Visibility = Visibility.Hidden if n > 0 else Visibility.Visible
        self._refresh_summary()

    def _populate_families(self):
        self.cmbFamily.Items.Clear()
        names = self._filter_family_names(self.txtFamSearch.Text)
        for n in names:
            self.cmbFamily.Items.Add(n)
        if self.cmbFamily.Items.Count > 0:
            self.cmbFamily.SelectedIndex = 0
        else:
            self.cmbType.Items.Clear()
            self._set_status("No matching face-based Generic Model family found.")

    def _populate_levels(self):
        self.cmbLevel.Items.Clear()
        for lv in self.levels:
            self.cmbLevel.Items.Add(elem_name(lv, "Level {}".format(lv.Id.IntegerValue)))
        if self.cmbLevel.Items.Count > 0:
            self.cmbLevel.SelectedIndex = 0

    def _populate_types(self, fam_name):
        self.cmbType.Items.Clear()
        self._type_map = self.families.get(fam_name, {})
        for tn in self._type_map:
            self.cmbType.Items.Add(tn)
        if self.cmbType.Items.Count > 0:
            self.cmbType.SelectedIndex = 0

    # ── Filtering / events ───────────────────────────────────────────────────
    def _filter_family_names(self, text):
        text = (text or "").strip().lower()
        if not text:
            return list(self._all_fam_names)
        return [n for n in self._all_fam_names if text in n.lower()]

    def _on_family_search(self, sender, args):
        self._populate_families()

    def _on_family_changed(self, sender, args):
        fam = self.cmbFamily.SelectedItem
        if fam:
            self._populate_types(fam)
        self._refresh_summary()

    def _on_pick_walls(self, sender, args):
        # Close, repick, reopen on outside caller via a flag.
        self.result = "REPICK"
        self.Close()

    # ── Status / summary ─────────────────────────────────────────────────────
    def _set_status(self, msg):
        self.txtStatus.Text = msg

    def _refresh_summary(self):
        try:
            n_walls = len(self.walls)
            fam = self.cmbFamily.SelectedItem or "—"
            typ = self.cmbType.SelectedItem or "—"
            face = "Exterior" if self.rbExterior.IsChecked else "Interior"
            lvl = self.cmbLevel.SelectedItem or "—"
            h_mm = safe_float(self.txtHeight.Text)
            e_mm = safe_float(self.txtElevation.Text)
            self.txtSumWalls.Text  = "{}".format(n_walls)
            self.txtSumFamily.Text = "{}  ·  {}".format(fam, typ)
            self.txtSumFace.Text   = face
            self.txtSumLevel.Text  = "{}".format(lvl)
            self.txtSumHeight.Text = "—" if h_mm is None else "{:.0f} mm".format(h_mm)
            self.txtSumOffset.Text = "—" if e_mm is None else "{:+.0f} mm".format(e_mm)
            cuts = []
            if self.chkAutoCut.IsChecked:
                cuts.append("Auto-cut")
            if self.chkMatchWS.IsChecked:
                cuts.append("Match workset")
            self.txtSumOptions.Text = "  ·  ".join(cuts) if cuts else "—"

            if n_walls == 0:
                self._set_status("Pick walls to begin.")
                self.btnPlace.IsEnabled = False
            elif self.cmbFamily.SelectedIndex < 0 or self.cmbType.SelectedIndex < 0:
                self._set_status("Select void family and type.")
                self.btnPlace.IsEnabled = False
            elif self.cmbLevel.SelectedIndex < 0:
                self._set_status("Select a schedule level.")
                self.btnPlace.IsEnabled = False
            elif h_mm is None or e_mm is None:
                self._set_status("Height and offset must be numeric (mm).")
                self.btnPlace.IsEnabled = False
            else:
                self._set_status("Ready  ·  void will be placed inside the wall body.")
                self.btnPlace.IsEnabled = True
        except Exception:
            pass

    # ── Place / cancel ───────────────────────────────────────────────────────
    def _on_place(self, sender, args):
        if not self.walls:
            self._set_status("No walls selected."); return
        if self.cmbFamily.SelectedIndex < 0:
            self._set_status("Select a family."); return
        if self.cmbType.SelectedIndex < 0:
            self._set_status("Select a type."); return
        if self.cmbLevel.SelectedIndex < 0:
            self._set_status("Select a level."); return

        height_mm = safe_float(self.txtHeight.Text)
        elev_mm   = safe_float(self.txtElevation.Text)
        if height_mm is None:
            self._set_status("Height must be a number (mm)."); return
        if elev_mm is None:
            self._set_status("Elevation offset must be a number (mm)."); return

        sym_id = self._type_map.get(self.cmbType.SelectedItem)
        if sym_id is None:
            self._set_status("Cannot resolve selected type."); return

        self.result = {
            "sym_id"      : sym_id,
            "level_idx"   : self.cmbLevel.SelectedIndex,
            "height_mm"   : height_mm,
            "elev_mm"     : elev_mm,
            "use_exterior": bool(self.rbExterior.IsChecked),
            "auto_cut"    : bool(self.chkAutoCut.IsChecked),
            "match_ws"    : bool(self.chkMatchWS.IsChecked),
        }
        self.Close()

    def _on_cancel(self, sender, args):
        self.result = None
        self.Close()


# ══════════════════════════════════════════════════════════════════════════════
#  Placement helpers
# ══════════════════════════════════════════════════════════════════════════════
def find_param(inst, names):
    lmap = {p.Definition.Name.lower(): p for p in inst.Parameters if p.Definition}
    for n in names:
        p = lmap.get(n.lower())
        if p:
            return p
    return None


def set_mm_param(param, mm):
    if param and not param.IsReadOnly and param.StorageType == StorageType.Double:
        param.Set(to_ft(mm)); return True
    return False


def set_level(inst, level_id):
    for bip in (BuiltInParameter.FAMILY_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM):
        try:
            p = inst.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(level_id); return True
        except Exception:
            continue
    return False


def set_elevation(inst, mm):
    for bip in (BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
                BuiltInParameter.INSTANCE_ELEVATION_PARAM):
        try:
            p = inst.get_Parameter(bip)
            if p and not p.IsReadOnly and p.StorageType == StorageType.Double:
                p.Set(to_ft(mm)); return True
        except Exception:
            continue
    return False


def match_workset(wall, inst):
    if not doc.IsWorkshared:
        return
    try:
        p = inst.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if p and not p.IsReadOnly:
            p.Set(wall.WorksetId.IntegerValue)
    except Exception:
        pass


def cut_wall(wall, inst):
    try:
        if not InstanceVoidCutUtils.CanBeCutWithVoid(wall):
            return False
        ok = True
        if hasattr(InstanceVoidCutUtils, "CanAddInstanceVoidCut"):
            ok = InstanceVoidCutUtils.CanAddInstanceVoidCut(doc, wall, inst)
        if ok:
            InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, inst)
            return True
    except Exception as ex:
        logger.warning("Cut failed for wall {}: {}".format(wall.Id.IntegerValue, ex))
    return False


# ── Face selection (Interior / Exterior) ──────────────────────────────────────
def get_wall_face(wall, use_exterior):
    """Return (face_ref, face) for the requested side using HostObjectUtils."""
    shell = ShellLayerType.Exterior if use_exterior else ShellLayerType.Interior
    refs  = HostObjectUtils.GetSideFaces(wall, shell)
    if refs and refs.Count > 0:
        face_ref = refs[0]
        face = wall.GetGeometryObjectFromReference(face_ref)
        if face is not None:
            return face_ref, face
    # Fallback: try the other shell
    shell = ShellLayerType.Interior if use_exterior else ShellLayerType.Exterior
    refs  = HostObjectUtils.GetSideFaces(wall, shell)
    if refs and refs.Count > 0:
        face_ref = refs[0]
        face = wall.GetGeometryObjectFromReference(face_ref)
        return face_ref, face
    return None, None


def face_origin_and_dir(face, wall, target_z, use_exterior=False):
    """Origin + ref_dir for face-hosted placement.

    Origin
    ------
    Wall START (pt0) projected onto the face, with Z = target_z.
    We always project using the face UV MID-POINT normal so the projection
    is guaranteed to land *inside* the face domain.  The XY of the result
    is then the world position of pt0 on that face.

    ref_dir
    -------
    Use ``wall.Orientation`` (wall-level property, always valid, always
    pointing toward the exterior) to build a ref_dir that is:
      • horizontal (perpendicular to Z)
      • in the face plane of any vertical wall face
      • aligned with the wall start→end direction
      • identical for Interior AND Exterior faces of the same wall

    This is UV-parameterisation-independent and does NOT rely on
    face.ComputeNormal() (which can return garbage for points extrapolated
    outside the face domain).
    """
    curve = wall.Location.Curve
    pt0   = curve.GetEndPoint(0)
    pt1   = curve.GetEndPoint(1)

    try:
        wall_vec = (pt1 - pt0).Normalize()   # start → end
    except Exception:
        wall_vec = XYZ.BasisX

    # ── ref_dir from wall.Orientation (always reliable) ──────────────────────
    # wall.Orientation × Z gives a horizontal vector in the face plane.
    # It is the same for every vertical face on this wall.
    try:
        ori     = wall.Orientation.Normalize()   # points toward exterior
        ref_dir = ori.CrossProduct(XYZ.BasisZ)
        if ref_dir.GetLength() < 1e-9:
            ref_dir = wall_vec
        else:
            ref_dir = ref_dir.Normalize()
    except Exception:
        ref_dir = wall_vec

    # Align with wall start→end direction.
    if ref_dir.DotProduct(wall_vec) < 0:
        ref_dir = ref_dir.Negate()

    # ── Origin: evaluate face at its OWN UV midpoint, then offset in XY ──────
    # Projecting pt0 directly can fail if pt0 lies outside the face's UV domain.
    # Instead: evaluate face at UV midpoint to get a guaranteed valid point,
    # then shift it in the wall_vec direction by the distance from the face's
    # world midpoint to pt0, so the origin sits at the wall-start position on
    # the face plane.
    try:
        fbb      = face.GetBoundingBox()
        uv_mid   = UV((fbb.Min.U + fbb.Max.U) * 0.5,
                      (fbb.Min.V + fbb.Max.V) * 0.5)
        face_mid = face.Evaluate(uv_mid)   # guaranteed to be on the face
        # Compute how far pt0 is along the wall direction from the face midpoint.
        offset_along_wall = (pt0 - face_mid).DotProduct(wall_vec)
        origin_3d = face_mid + wall_vec * offset_along_wall
        origin_xy = XYZ(origin_3d.X, origin_3d.Y, target_z)
    except Exception:
        # Last-resort: use face midpoint itself.
        fbb = face.GetBoundingBox()
        uv  = UV(fbb.Min.U, (fbb.Min.V + fbb.Max.V) * 0.5)
        p   = face.Evaluate(uv)
        origin_xy = XYZ(p.X, p.Y, target_z)

    return origin_xy, ref_dir


# ── Face-relative side test ──────────────────────────────────────────────────
def _face_origin_and_normal(face):
    """Return (face_pt, face_normal) at the face's UV midpoint."""
    fbb = face.GetBoundingBox()
    uv  = UV((fbb.Min.U + fbb.Max.U) * 0.5,
             (fbb.Min.V + fbb.Max.V) * 0.5)
    face_pt = face.Evaluate(uv)
    normal  = face.ComputeNormal(uv).Normalize()
    return face_pt, normal


def _iter_solids(inst):
    """Yield all solids inside an instance's geometry, including void solids.

    Walks ``GeometryInstance`` children and returns ``Solid`` objects.  The
    options used include non-visible objects so void primitives are reachable.
    """
    try:
        opts = Options()
        opts.IncludeNonVisibleObjects = True
        opts.ComputeReferences = False
        ge = inst.get_Geometry(opts)
        if ge is None:
            return
        stack = [ge]
        while stack:
            cur = stack.pop()
            for g in cur:
                if isinstance(g, Solid):
                    yield g
                elif isinstance(g, GeometryInstance):
                    sub = g.GetInstanceGeometry()
                    if sub is not None:
                        stack.append(sub)
    except Exception:
        return


def _instance_geometric_center(inst):
    """Centre of the instance geometry (incl. voids) -> XYZ.  Falls back to BBox."""
    centers = []
    weights = []
    for s in _iter_solids(inst):
        try:
            if s is None or s.Volume <= 0:
                continue
            c = s.ComputeCentroid()
            centers.append(c)
            weights.append(float(s.Volume))
        except Exception:
            continue

    if centers:
        wsum = sum(weights) or 1.0
        ax = sum(c.X * w for c, w in zip(centers, weights)) / wsum
        ay = sum(c.Y * w for c, w in zip(centers, weights)) / wsum
        az = sum(c.Z * w for c, w in zip(centers, weights)) / wsum
        return XYZ(ax, ay, az)

    bb = None
    try:
        bb = inst.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return None
    return (bb.Min + bb.Max) * 0.5


def void_signed_distance_to_face(inst, face):
    """Signed distance from face plane to instance geometric centre, along face normal.

    Face normal of a wall side face always points OUT of the wall body, so:
        signed > 0  -> centre on AIR side   (sticking out, WRONG)
        signed < 0  -> centre on WALL side  (cuts into wall, CORRECT)
    Returns None if no centre can be determined.
    """
    center = _instance_geometric_center(inst)
    if center is None:
        return None
    try:
        face_pt, normal = _face_origin_and_normal(face)
        return (center - face_pt).DotProduct(normal)
    except Exception:
        return None


def void_is_on_air_side(inst, face, tol=1e-4):
    sd = void_signed_distance_to_face(inst, face)
    if sd is None:
        return False
    return sd > tol


def _mirror_inst_across_face_plane(inst, face):
    """Mirror the family instance in-place across the host face plane.

    This is the geometric equivalent of FlipFacing and works even when the
    family does not allow FlipFacing.  Uses ElementTransformUtils.MirrorElements
    with mirrorCopy=False so the original element is mirrored in-place.
    Returns True on success.
    """
    try:
        face_pt, normal = _face_origin_and_normal(face)
        plane = Plane.CreateByNormalAndOrigin(normal, face_pt)
        ids = List[ElementId]()
        ids.Add(inst.Id)
        ElementTransformUtils.MirrorElements(doc, ids, plane, False)
        doc.Regenerate()
        return True
    except Exception as ex:
        logger.warning("_mirror_inst_across_face_plane: {}".format(ex))
        return False


def correct_void_side(inst, face):
    """Make sure the void extrudes INTO the wall body (not into the room/outside).

    Returns one of: 'OK', 'FLIP-FACING', 'FLIP-HAND', 'MIRROR', 'STILL-WRONG'.

    Strategy (cumulative; each step verifies and reverts when ineffective):
        1. Regenerate; if already on wall-solid side, return 'OK'.
        2. FlipFacing (if family allows).
        3. FlipHand (if family allows).
        4. Mirror the instance in-place across the host face plane.  This is
           the universal geometric flip and works when the family does not
           expose any flip control.
    """
    if not isinstance(inst, FamilyInstance):
        return "OK"
    try:
        doc.Regenerate()
        if not void_is_on_air_side(inst, face):
            return "OK"

        # 1) FlipFacing
        try:
            if getattr(inst, "CanFlipFacing", False):
                inst.FlipFacing()
                doc.Regenerate()
                if not void_is_on_air_side(inst, face):
                    return "FLIP-FACING"
                inst.FlipFacing()
                doc.Regenerate()
        except Exception:
            pass

        # 2) FlipHand
        try:
            if getattr(inst, "CanFlipHand", False):
                inst.FlipHand()
                doc.Regenerate()
                if not void_is_on_air_side(inst, face):
                    return "FLIP-HAND"
                inst.FlipHand()
                doc.Regenerate()
        except Exception:
            pass

        # 3) Geometric mirror across host face plane
        if _mirror_inst_across_face_plane(inst, face):
            if not void_is_on_air_side(inst, face):
                return "MIRROR"
            _mirror_inst_across_face_plane(inst, face)

        return "STILL-WRONG"

    except Exception as ex:
        logger.warning("correct_void_side: {}".format(ex))
        return "ERROR"


# ══════════════════════════════════════════════════════════════════════════════
#  Main placement
# ══════════════════════════════════════════════════════════════════════════════
def run_placement(walls, cfg, levels):
    symbol = doc.GetElement(ElementId(int(cfg["sym_id"])))
    if symbol is None:
        forms.alert("Family type not found in model.", title="Error")
        return
    level  = levels[cfg["level_idx"]]
    placed = []
    failed = []

    tg = TransactionGroup(doc, "BA - Place Void in Wall")
    tg.Start()
    try:
        with Transaction(doc, "Activate symbol") as tx:
            tx.Start()
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
            tx.Commit()

        for wall in walls:
            wname     = elem_name(wall, "Wall")
            wid       = wall.Id.IntegerValue
            length_mm = get_wall_length_mm(wall)

            tx = Transaction(doc, "Place void - {}".format(wname))
            tx.Start()
            try:
                face_ref, face = get_wall_face(wall, cfg["use_exterior"])
                if face is None:
                    raise Exception("Could not retrieve wall face.")

                target_z = level.Elevation + to_ft(cfg["elev_mm"])
                origin, ref_dir = face_origin_and_dir(
                    face, wall, target_z, use_exterior=cfg["use_exterior"]
                )

                inst = doc.Create.NewFamilyInstance(face_ref, origin, ref_dir, symbol)
                if inst is None:
                    raise Exception("NewFamilyInstance returned None.")

                set_level(inst, level.Id)
                set_elevation(inst, cfg["elev_mm"])
                set_mm_param(find_param(inst, ["Height", "H", "Void Height"]), cfg["height_mm"])
                set_mm_param(find_param(inst, ["Length", "L", "Void Length"]), length_mm)

                # correct_void_side: detects air-side placement and corrects with
                # FlipFacing → FlipHand → geometry mirror (in that priority).
                side_action = correct_void_side(inst, face)

                if cfg["match_ws"]:
                    match_workset(wall, inst)
                cut_ok = cut_wall(wall, inst) if cfg["auto_cut"] else False

                tx.Commit()
                placed.append((wname, wid, inst.Id.IntegerValue,
                               round(length_mm, 1), round(cfg["height_mm"], 1),
                               "Yes" if cut_ok else "No",
                               side_action))
            except Exception as ex:
                tx.RollBack()
                failed.append((wname, wid, str(ex)))

        tg.Assimilate()

    except Exception as outer:
        tg.RollBack()
        forms.alert("Critical error - all changes rolled back.\n\n{}".format(outer),
                    title="Placement Failed")
        return

    if placed:
        output.print_md("## Void Placement Report")
        output.print_table(
            table_data=placed,
            columns=["Wall", "Wall Id", "Instance Id",
                     "Length (mm)", "Height (mm)", "Cut?", "Side Action"],
            title="Placed Voids",
        )
    if failed:
        output.print_table(
            table_data=failed,
            columns=["Wall", "Wall Id", "Error"],
            title="Failed",
        )

    msg = "Placed {} void(s).".format(len(placed))
    if failed:
        msg += "  {} failed - see pyRevit output.".format(len(failed))
    forms.alert(msg, title="Done")


# ══════════════════════════════════════════════════════════════════════════════
#  Wall picking helper (allows re-pick from inside the dialog)
# ══════════════════════════════════════════════════════════════════════════════
def pick_walls(prompt="Select walls to place void on  [Hold Ctrl]  [ESC = cancel]"):
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, WallFilter(), prompt)
    except OperationCanceledException:
        return None
    walls = [doc.GetElement(r.ElementId) for r in refs
             if isinstance(doc.GetElement(r.ElementId), Wall)]
    return walls


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if doc.IsReadOnly:
    forms.alert("Document is read-only.", title="Cannot Run", exitscript=True)

xaml = os.path.join(os.path.dirname(__file__), "ui.xaml")
if not os.path.exists(xaml):
    forms.alert("ui.xaml not found.", title="Missing File", exitscript=True)

# Step 1: pick walls
walls = pick_walls()
if walls is None:
    script.exit()
if not walls:
    forms.alert("No valid walls selected.", title="Cancelled", exitscript=True)

# Step 2: dialog (with optional re-pick loop)
families = collect_families()
levels   = get_levels()

while True:
    dlg = ConfigDialog(xaml, walls, families, levels)
    dlg.ShowDialog()

    if dlg.result == "REPICK":
        new_walls = pick_walls()
        if new_walls is None or not new_walls:
            # Cancel out entirely if user aborted re-pick
            script.exit()
        walls = new_walls
        continue
    break

# Step 3: place
if dlg.result is not None and dlg.result != "REPICK":
    run_placement(walls, dlg.result, levels)
