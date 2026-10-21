# -*- coding: utf-8 -*-
__title__ = "Assembly Views\nCreator"
__author__ = "Bhanu Prakash A"
__doc__ = """Create assembly views, production sheet layout, view templates,
viewport types, and revisions for selected assemblies."""

import os
import sys
import math
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Transaction, ElementId, XYZ, Element, ElementType, View, View3D,
    ViewSection, ViewSchedule, ViewSheet, Viewport, Revision, ScheduleSheetInstance,
    AssemblyInstance, AssemblyViewUtils, AssemblyDetailViewOrientation,
    ViewDuplicateOption, ViewOrientation3D, RevisionNumberType,
    ElementTransformUtils, RevisionCloud, Color, ViewFamilyType, ViewFamily
)
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, Entity, AccessLevel
from pyrevit import forms, script
import wpf

from System.Windows import Window
from System.Windows.Controls import CheckBox, DataGridRow
from System.Windows.Media import VisualTreeHelper
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs, PropertyChangedEventHandler
import System

PATH_SCRIPT = os.path.dirname(__file__)
LAYOUT_CACHE_PATH = os.path.join(PATH_SCRIPT, "layout_cache.json")
doc = __revit__.ActiveUIDocument.Document
output = script.get_output()
INVALID_ID = ElementId.InvalidElementId

FORBIDDEN_NAMES = r'\:{}[]|;<>?`~'

# Fixed view scale (scale UI removed — templates / types define appearance)
DEFAULT_VIEW_SCALE = 25


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW DEFINITIONS — matches Revit Create Assembly Views + production naming
# ═══════════════════════════════════════════════════════════════════════════════

# Production views only (checked rows from your workflow)
VIEW_DEFS = [
    # key, default name prefix, orientation or special, layout slot, default on
    ("3d_front",   "3D VIEW - FRONT",   "3d_front",         "3d_front",        True),
    ("3d_rear",    "3D VIEW - REAR",    "3d_rear",          "3d_rear",         True),
    ("plan",       "TOP VIEW",          "ElevationTop",     "plan",            True),
    # SECTION 1-1 = vertical section (DetailSectionB per production / Revit Section B)
    ("section_a",  "SECTION 1-1",       "DetailSectionB",   "section_a",       True),
    ("section_b",  "SECTION 2-2",       "HorizontalDetail", "section_b",       True),
    ("elev_front", "FRONT ELEVATION",   "ElevationFront",   "elevation_front", True),
    ("elev_back",  "BACK ELEVATION",    "ElevationBack",    "elevation_back",  True),
    ("wall_schedule", "Wall Schedule", "sched_walls",      "schedule",        True),
]

# Production sheet layout (image 2): 3 columns, vertically aligned per column
# Col1: FRONT ELEV | middle horizontal SECTION (04) | TOP VIEW (05)
# Col2: BACK ELEV  | 3D FRONT
# Col3: SECTION 1-1 | 3D REAR
LAYOUT_POSITIONS = {
    "elevation_front": (0.328, 0.750),
    "section_b":       (0.328, 0.480),
    "plan":            (0.328, 0.255),
    "elevation_back":  (0.784, 0.734),
    "3d_front":        (0.784, 0.291),
    "section_a":       (1.070, 0.754),
    "3d_rear":         (1.070, 0.288),
    "schedule":        (0.915, 0.079),
}

# Fixed column U — keeps viewports vertically aligned in each column
LAYOUT_COLUMN_U = {
    "elevation_front": 0.328,
    "section_b":       0.328,
    "plan":            0.328,
    "elevation_back":  0.784,
    "3d_front":        0.784,
    "section_a":       1.070,
    "3d_rear":         1.070,
    "schedule":        0.915,
}

# Match title / view name → layout slot (longer / specific hints first)
TITLE_HINT_TO_LAYOUT = [
    ("3D VIEW - REAR", "3d_rear"),
    ("3D VIEW - FRONT", "3d_front"),
    ("FRONT ELEVATION", "elevation_front"),
    ("BACK ELEVATION", "elevation_back"),
    ("SECTION 2-2", "section_b"),
    ("SECTION 1-1", "section_a"),
    ("ELEVATION TOP", "section_b"),
    ("TOP VIEW", "plan"),
    ("WALL SCHEDULE", "schedule"),
    ("PART LIST", "schedule"),
]


def load_layout_cache():
    """Load last captured layout from layout_cache.json (from active sheet)."""
    try:
        if not os.path.exists(LAYOUT_CACHE_PATH):
            return False
        import json
        with open(LAYOUT_CACHE_PATH, "r") as f:
            data = json.load(f)
        for key, uv in data.items():
            if isinstance(uv, (list, tuple)) and len(uv) == 2:
                LAYOUT_POSITIONS[key] = (float(uv[0]), float(uv[1]))
        return True
    except Exception:
        return False


def save_layout_cache():
    try:
        import json
        data = {k: [uv[0], uv[1]] for k, uv in LAYOUT_POSITIONS.items()}
        with open(LAYOUT_CACHE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def apply_column_alignment_to_layout():
    """Snap each slot to its column U so views stack vertically on the sheet."""
    for key, col_u in LAYOUT_COLUMN_U.items():
        pos = LAYOUT_POSITIONS.get(key)
        if pos:
            LAYOUT_POSITIONS[key] = (col_u, pos[1])
    # Keep the requested horizontal SECTION / TOP VIEW order even when
    # capturing a sheet or loading a cache made with the previous layout.
    plan = LAYOUT_POSITIONS["plan"]
    section = LAYOUT_POSITIONS["section_b"]
    if plan[1] > section[1]:
        LAYOUT_POSITIONS["plan"] = (plan[0], section[1])
        LAYOUT_POSITIONS["section_b"] = (section[0], plan[1])


load_layout_cache()
apply_column_alignment_to_layout()

# Feet per character for viewport title underline (NCP title types)
TITLE_LINE_FT_PER_CHAR = 0.0105

VIEWPORT_DETAIL_NUMBER_ORDER = [
    "elevation_front", "elevation_back", "section_a", "section_b",
    "plan", "3d_front", "3d_rear", "schedule",
]

# Exact production defaults (image 2) — matched first, then keyword fallback
DEFAULT_TEMPLATE_NAMES = {
    "3d_front":   "Wall Assembly 3D View-25",
    "3d_rear":    "Wall Assembly 3D View-25",
    "plan":       "Wall Assembly Plan Elevation-25",
    "section_a":  "Wall Assembly Section-25",
    "section_b":  "Wall Assembly Plan Elevation-25",
    "elev_front": "Wall Assembly Front Elevation-25",
    "elev_back":  "Wall Assembly Back Elevation-25",
    "wall_schedule": "Production Wall ERP Schedule",
}

DEFAULT_VIEWPORT_NAMES = {
    "3d_front":   "NCP_Detail Title Without Scale",
    "3d_rear":    "NCP_Detail Title Without Scale",
    "plan":       "NCP_Section_Title With Scale",
    "section_a":  "NCP_Section_Title With Scale",
    "section_b":  "NCP_Section_Title With Scale",
    "elev_front": "NCP_Section_Title With Scale",
    "elev_back":  "NCP_Section_Title With Scale",
    "wall_schedule": "NCP_Detail Title",
}

# Title on sheet — only FRONT ELEVATION includes {assembly} (production sheet style)
DEFAULT_TITLE_ON_SHEET = {
    "3d_front":   "3D VIEW - FRONT",
    "3d_rear":    "3D VIEW - REAR",
    "plan":       "TOP VIEW",
    "section_a":  "SECTION",
    "section_b":  "SECTION",
    "elev_front": "FRONT ELEVATION - {assembly}",
    "elev_back":  "BACK ELEVATION",
    "wall_schedule": "{assembly}",
}

TEMPLATE_KEYWORDS = {
    "3d_front":   ["wall assembly 3d view"],
    "3d_rear":    ["wall assembly 3d view"],
    "plan":       ["wall assembly plan elevation"],
    "section_a":  ["wall assembly section"],
    "section_b":  ["wall assembly plan elevation", "elevation top"],
    "elev_front": ["wall assembly front elevation"],
    "elev_back":  ["wall assembly back elevation"],
    "wall_schedule": ["production wall erp"],
}

VIEWPORT_KEYWORDS = {
    "3d_front":   ["detail title without scale"],
    "3d_rear":    ["detail title without scale"],
    "plan":       ["section_title with scale"],
    "section_a":  ["section_title with scale"],
    "section_b":  ["section_title with scale"],
    "elev_front": ["section_title with scale"],
    "elev_back":  ["section_title with scale"],
    "wall_schedule": ["ncp_detail title"],
}

VIEW_TYPE_LABELS = {
    "3d_front": "3D Front", "3d_rear": "3D Rear",
    "plan": "Top view", "section_a": "Vertical section", "section_b": "Horizontal section",
    "elev_front": "Front elevation", "elev_back": "Back elevation",
    "wall_schedule": "Wall Schedule",
}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_name(text):
    if not text:
        return ""
    return ''.join(c for c in text if c not in FORBIDDEN_NAMES).strip()


def format_view_name(prefix, assembly_name):
    return "{} - ({})".format(sanitize_name(prefix), sanitize_name(assembly_name))


def resolve_title_on_sheet(view_row, assembly_name):
    """
    Sheet viewport title. Only rows with {assembly} in the pattern get the
    assembly name (default: FRONT ELEVATION only). All others stay as typed.
    """
    raw = (view_row.TitleOnSheet or "").strip()
    if not raw:
        raw = DEFAULT_TITLE_ON_SHEET.get(view_row.Key, view_row.NamePrefix)
    asm = sanitize_name(assembly_name)
    if "{assembly}" in raw:
        return sanitize_name(raw.replace("{assembly}", asm))
    return sanitize_name(raw)


def match_by_exact_name(items, exact_name):
    if not exact_name:
        return None
    key = exact_name.lower().strip()
    for item in items:
        if item.Label.lower().strip() == key:
            return item
    for item in items:
        if key in item.Label.lower():
            return item
    return None


def rename_sheet(sheet, sheet_name, sheet_number):
    sheet.Name = sanitize_name(sheet_name) or "Unnamed Sheet"
    num = sanitize_name(sheet_number)
    for _ in range(50):
        try:
            sheet.SheetNumber = num
            return
        except Exception:
            num += '*'


def get_sheet_titleblock(sheet):
    """First title block instance on the sheet."""
    try:
        tbs = (FilteredElementCollector(doc, sheet.Id)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsNotElementType()
               .ToElements())
        return tbs[0] if tbs else None
    except Exception:
        return None


def apply_sheet_parameters(sheet, sheet_params):
    """Write title block / sheet identity parameters (Drawn By, dates, etc.)."""
    if not sheet or not sheet_params:
        return
    tb = get_sheet_titleblock(sheet)
    for pname, pval in sheet_params.items():
        if not pval:
            continue
        param = None
        try:
            if tb:
                param = tb.LookupParameter(pname)
        except Exception:
            param = None
        if not param:
            try:
                param = sheet.LookupParameter(pname)
            except Exception:
                param = None
        if param and not param.IsReadOnly:
            try:
                param.Set(pval)
            except Exception:
                pass


def get_view_templates():
    templates = [ComboItem(INVALID_ID, "<From type>")]
    for vt in FilteredElementCollector(doc).OfClass(View).ToElements():
        try:
            if vt.IsTemplate:
                templates.append(ComboItem(vt.Id, vt.Name))
        except Exception:
            pass
    return sorted(templates, key=lambda x: x.Label)


def element_type_display_name(element_type):
    """Readable type name for viewport / element types."""
    for bip in (BuiltInParameter.ALL_MODEL_TYPE_NAME,
                BuiltInParameter.SYMBOL_NAME_PARAM):
        try:
            p = element_type.get_Parameter(bip)
            if p and p.AsString():
                return p.AsString().strip()
        except Exception:
            pass
    try:
        return Element.Name.GetValue(element_type).strip()
    except Exception:
        return "Type {}".format(element_type.Id.IntegerValue)


def get_viewport_types():
    """Collect all viewport types from project (multiple API paths)."""
    types = [ComboItem(INVALID_ID, "<Default>")]
    seen = set()
    vp_cat_int = int(BuiltInCategory.OST_Viewports)

    def add_type(etype):
        eid = etype.Id.IntegerValue
        if eid in seen:
            return
        seen.add(eid)
        label = element_type_display_name(etype)
        if label:
            types.append(ComboItem(etype.Id, label))

    # Path 1: ElementType + category match
    for et in FilteredElementCollector(doc).OfClass(ElementType).ToElements():
        try:
            cat = et.Category
            if cat and cat.Id.IntegerValue == vp_cat_int:
                add_type(et)
        except Exception:
            pass

    # Path 2: BuiltIn category filter
    for et in (FilteredElementCollector(doc)
               .OfCategory(BuiltInCategory.OST_Viewports)
               .WhereElementIsElementType()
               .ToElements()):
        try:
            add_type(et)
        except Exception:
            pass

    # Path 3: family name contains "viewport"
    for et in FilteredElementCollector(doc).OfClass(ElementType).ToElements():
        try:
            fn = et.FamilyName
            if fn and "viewport" in fn.lower():
                add_type(et)
        except Exception:
            pass

    # Path 4: types used by viewports already on sheets
    for vp in FilteredElementCollector(doc).OfClass(Viewport).ToElements():
        try:
            tid = vp.GetTypeId()
            if tid == INVALID_ID or tid.IntegerValue in seen:
                continue
            et = doc.GetElement(tid)
            if et:
                add_type(et)
        except Exception:
            pass

    # De-duplicate labels, keep first id
    unique = [types[0]]
    labels_seen = set(["<default>"])
    for item in sorted(types[1:], key=lambda x: x.Label.lower()):
        key = item.Label.lower()
        if key not in labels_seen:
            labels_seen.add(key)
            unique.append(item)
    return unique


def get_detail_view_types():
    """Detail view types control the section/callout mark, not viewport titles."""
    items = [ComboItem(INVALID_ID, "<Keep current detail type>")]
    for view_type in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if view_type.ViewFamily == ViewFamily.Detail:
            items.append(ComboItem(view_type.Id, element_type_display_name(view_type)))
    return items[:1] + sorted(items[1:], key=lambda item: item.Label.lower())


def apply_detail_view_type(view, type_id):
    if not isinstance(view, ViewSection) or type_id == INVALID_ID:
        return
    if view.GetTypeId() == type_id:
        return
    if type_id not in view.GetValidTypes():
        raise Exception("The selected production detail type is not compatible with {}.".format(view.Name))
    view.ChangeTypeId(type_id)


def match_default_viewport(view_key, viewports):
    exact = match_by_exact_name(viewports, DEFAULT_VIEWPORT_NAMES.get(view_key))
    if exact:
        return exact
    keywords = VIEWPORT_KEYWORDS.get(view_key, [])
    best = None
    best_score = 0
    for vp in viewports:
        if vp.Id == INVALID_ID:
            continue
        label_l = vp.Label.lower()
        score = sum(2 for kw in keywords if kw in label_l)
        if score > best_score:
            best_score = score
            best = vp
    return best if best else viewports[0]


def get_title_blocks():
    """Title block type names for dropdown."""
    result = []
    for tb in (FilteredElementCollector(doc)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsElementType()
               .ToElements()):
        type_name = Element.Name.GetValue(tb)
        family = tb.FamilyName
        label = type_name if type_name else family
        if family and type_name and family not in type_name:
            label = "{} : {}".format(family, type_name)
        result.append(ComboItem(tb.Id, label))
    return sorted(result, key=lambda x: x.Label)


def get_revisions_combo():
    items = []
    for rev in sorted(
            FilteredElementCollector(doc).OfClass(Revision).ToElements(),
            key=lambda r: r.SequenceNumber):
        label = "Rev {} — {}".format(rev.SequenceNumber, rev.Description or "")
        items.append(ComboItem(rev.Id, label))
    return items


def collect_assemblies():
    return list(FilteredElementCollector(doc).OfClass(AssemblyInstance).ToElements())


def get_assembly_sheet(assembly_id):
    """Return assembly-owned sheet (appears under assembly in Project Browser)."""
    for sheet in (FilteredElementCollector(doc)
                  .OfClass(ViewSheet)
                  .ToElements()):
        try:
            if sheet.AssociatedAssemblyInstanceId == assembly_id:
                return sheet
        except Exception:
            pass
    return None


def build_assembly_sheet_map():
    """Map assembly ElementId -> assembly ViewSheet."""
    sheet_map = {}
    for asm in collect_assemblies():
        sh = get_assembly_sheet(asm.Id)
        if sh:
            sheet_map[asm.Id] = sh
    return sheet_map


def match_default_template(view_key, name_prefix, templates):
    exact = match_by_exact_name(templates, DEFAULT_TEMPLATE_NAMES.get(view_key))
    if exact:
        return exact
    keywords = TEMPLATE_KEYWORDS.get(view_key, [])
    prefix_l = (name_prefix or "").lower()
    best = None
    best_score = 0
    for tmpl in templates:
        if tmpl.Id == INVALID_ID:
            continue
        label_l = tmpl.Label.lower()
        score = sum(2 for kw in keywords if kw in label_l)
        score += sum(1 for kw in keywords if kw in prefix_l)
        if score > best_score:
            best_score = score
            best = tmpl
    return best if best else templates[0]


def set_view_title_on_sheet_param(view, title_text):
    """View Identity → Title on Sheet."""
    for bip in (BuiltInParameter.VIEW_DESCRIPTION,):
        try:
            p = view.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(title_text)
                return True
        except Exception:
            pass
    return False


def _viewport_title_on_sheet_text(viewport):
    try:
        p = viewport.get_Parameter(BuiltInParameter.VIEWPORT_SHEET_NAME)
        if p and p.AsString():
            return p.AsString().strip().upper()
    except Exception:
        pass
    try:
        view = doc.GetElement(viewport.ViewId)
        if view:
            p = view.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
            if p and p.AsString():
                return p.AsString().strip().upper()
    except Exception:
        pass
    return ""


def _layout_key_from_text(text):
    t = (text or "").upper()
    for hint, key in TITLE_HINT_TO_LAYOUT:
        if hint in t:
            return key
    return None


def _sheet_uv_from_xy(sheet, x, y):
    bb = sheet.Outline
    min_u, max_u = bb.Min.U, bb.Max.U
    min_v, max_v = bb.Min.V, bb.Max.V
    draw_max_u = min_u + (max_u - min_u) * 0.72
    span_u = draw_max_u - min_u
    span_v = max_v - min_v
    if span_u < 0.01 or span_v < 0.01:
        return None
    return (round((x - min_u) / span_u, 3), round((y - min_v) / span_v, 3))


def capture_layout_from_active_sheet():
    """Read viewport/schedule positions from active sheet; update layout cache only."""
    try:
        from Autodesk.Revit.DB import ScheduleSheetInstance
        active = __revit__.ActiveUIDocument.ActiveView
        if active is None or not isinstance(active, ViewSheet):
            return False
        sheet = active
        updated = {}

        for vp in (FilteredElementCollector(doc, sheet.Id)
                   .OfClass(Viewport)
                   .ToElements()):
            try:
                title = _viewport_title_on_sheet_text(vp)
                key = _layout_key_from_text(title)
                if not key:
                    view = doc.GetElement(vp.ViewId)
                    if view:
                        key = _layout_key_from_text(view.Name)
                if not key:
                    continue
                c = vp.GetBoxCenter()
                uv = _sheet_uv_from_xy(sheet, c.X, c.Y)
                if uv:
                    updated[key] = uv
            except Exception:
                pass

        for inst in (FilteredElementCollector(doc, sheet.Id)
                     .OfClass(ScheduleSheetInstance)
                     .ToElements()):
            try:
                sched = doc.GetElement(inst.ScheduleId)
                sname = sched.Name if sched else ""
                if sname and "revision" in sname.lower():
                    continue
                pt = inst.Point
                uv = _sheet_uv_from_xy(sheet, pt.X, pt.Y)
                if uv:
                    updated["schedule"] = uv
            except Exception:
                pass

        if updated:
            for key, uv in updated.items():
                LAYOUT_POSITIONS[key] = uv
            apply_column_alignment_to_layout()
            save_layout_cache()
            return True
    except Exception:
        pass
    return False


def fit_viewport_title_line(viewport, title_text):
    """Underline length matches title text (production viewport style)."""
    title_text = sanitize_name(title_text)
    try:
        p = viewport.get_Parameter(BuiltInParameter.VIEWPORT_SHEET_NAME)
        if p and not p.IsReadOnly:
            p.Set(title_text)
    except Exception:
        pass

    char_count = len(title_text)
    if char_count < 1:
        return

    length_ft = char_count * TITLE_LINE_FT_PER_CHAR
    length_ft = max(0.06, min(length_ft, 0.75))

    try:
        viewport.LabelLineLength = length_ft
    except AttributeError:
        pass
    except Exception:
        pass


def create_assembly_sheet(assembly, title_block_id, sheet_name, sheet_number):
    """Create sheet owned by assembly (Project Browser → Assemblies → … → Sheets)."""
    sheet = AssemblyViewUtils.CreateSheet(doc, assembly.Id, title_block_id)
    rename_sheet(sheet, sheet_name, sheet_number)
    return sheet


def find_view_by_name(name):
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if v.Name == name:
            return v
    return None


def apply_view_scale(view, scale_value):
    try:
        if view and not isinstance(view, ViewSchedule):
            view.Scale = int(scale_value)
    except Exception:
        pass


def apply_template(view, template_id, assign):
    if template_id is None or template_id == INVALID_ID:
        return
    try:
        if assign:
            view.ViewTemplateId = template_id
        else:
            view.ApplyViewTemplateParameters(doc.GetElement(template_id))
    except Exception:
        pass


def set_view_name(view, name):
    clean = sanitize_name(name)
    for attempt in range(30):
        try:
            view.Name = clean if attempt == 0 else clean + " ({})".format(attempt)
            return view.Name
        except Exception:
            pass
    return clean


def get_orientation_enum(key):
    mapping = {
        "HorizontalDetail": AssemblyDetailViewOrientation.HorizontalDetail,
        "DetailSectionA":   AssemblyDetailViewOrientation.DetailSectionA,
        "DetailSectionB":   AssemblyDetailViewOrientation.DetailSectionB,
        "ElevationTop":     AssemblyDetailViewOrientation.ElevationTop,
        "ElevationBottom":  AssemblyDetailViewOrientation.ElevationBottom,
        "ElevationLeft":    AssemblyDetailViewOrientation.ElevationLeft,
        "ElevationRight":   AssemblyDetailViewOrientation.ElevationRight,
        "ElevationFront":   AssemblyDetailViewOrientation.ElevationFront,
        "ElevationBack":    AssemblyDetailViewOrientation.ElevationBack,
    }
    return mapping.get(key)


def create_3d_assembly_view(asm_id, template_id, assign):
    tid = template_id if template_id != INVALID_ID else None
    if tid:
        v = AssemblyViewUtils.Create3DOrthographic(doc, asm_id, tid, assign)
    else:
        v = AssemblyViewUtils.Create3DOrthographic(doc, asm_id)
    doc.Regenerate()
    return v


def orient_3d_view_front(view3d, assembly):
    """Initial isometric orientation before horizontal flip."""
    try:
        center = assembly.GetCenter()
        tr = assembly.GetTransform()
        dist = 25.0
        front = tr.BasisY.Normalize()
        right = tr.BasisX.Normalize()
        up = tr.BasisZ.Normalize()
        eye = (center + front * dist * 0.85 + right * dist * 0.65 + up * dist * 0.55)
        forward = (center - eye).Normalize()
        view3d.SetOrientation(ViewOrientation3D(eye, up, forward))
    except Exception:
        pass


def _xyz_len(vec):
    return math.sqrt(vec.X ** 2 + vec.Y ** 2 + vec.Z ** 2)


def _xyz_normalize(vec):
    length = _xyz_len(vec)
    if length < 0.001:
        return vec
    return XYZ(vec.X / length, vec.Y / length, vec.Z / length)


def _xyz_dot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _xyz_cross(a, b):
    return XYZ(
        a.Y * b.Z - a.Z * b.Y,
        a.Z * b.X - a.X * b.Z,
        a.X * b.Y - a.Y * b.X)


def flip_3d_view_horizontal(view3d):
    """Flip 3D view horizontally (production Dynamo logic), then lock."""
    if not isinstance(view3d, View3D):
        return False
    try:
        orient = view3d.GetOrientation()
        eye = orient.EyePosition
        up = orient.UpDirection
        fwd = orient.ForwardDirection
        bbox = view3d.CropBox

        fwd_horizontal = XYZ(fwd.X, fwd.Y, 0)
        fwd_h_len = _xyz_len(fwd_horizontal)

        if fwd_h_len > 0.001:
            fwd_h_norm = _xyz_normalize(fwd_horizontal)
            new_fwd_h = XYZ(-fwd_h_norm.X, -fwd_h_norm.Y, 0)
            new_fwd = XYZ(new_fwd_h.X * fwd_h_len, new_fwd_h.Y * fwd_h_len, fwd.Z)
            new_fwd = _xyz_normalize(new_fwd)
        else:
            new_fwd = XYZ(-fwd.X, -fwd.Y, -fwd.Z)

        new_up = up
        dot = _xyz_dot(new_fwd, new_up)
        if abs(dot) > 0.01:
            right = _xyz_normalize(_xyz_cross(new_fwd, new_up))
            new_up = _xyz_normalize(_xyz_cross(right, new_fwd))

        if bbox:
            bbox_center = bbox.Transform.Origin
            distance = _xyz_len(XYZ(
                eye.X - bbox_center.X,
                eye.Y - bbox_center.Y,
                eye.Z - bbox_center.Z))
            new_eye = XYZ(
                bbox_center.X - new_fwd.X * distance,
                bbox_center.Y - new_fwd.Y * distance,
                bbox_center.Z - new_fwd.Z * distance)
        else:
            new_eye = eye

        view3d.SetOrientation(ViewOrientation3D(new_eye, new_up, new_fwd))

        try:
            temp_param = view3d.get_Parameter(
                BuiltInParameter.VIEWER_TEMPORARY_VIEW_MODE)
            if temp_param and not temp_param.IsReadOnly:
                temp_param.Set(0)
        except Exception:
            pass

        lock_3d_view_orientation(view3d)
        return True
    except Exception:
        return False


def setup_3d_view_front(view3d, assembly):
    """FRONT title keeps its slot and uses the former REAR orientation."""
    view3d.Unlock()
    orient_3d_view_rear(view3d, assembly)
    doc.Regenerate()
    lock_3d_view_orientation(view3d)


def setup_3d_view_rear(view3d, assembly, erection_mark=None):
    """REAR title keeps its slot and uses the former FRONT orientation."""
    view3d.Unlock()
    orient_3d_view_front(view3d, assembly)
    doc.Regenerate()
    if not flip_3d_view_horizontal(view3d):
        raise Exception("Could not set the rear 3D orientation.")


def find_erection_mark_in_assembly(assembly):
    """Erection mark family in assembly members (same logic as Create Assembly tool)."""
    try:
        for member_id in assembly.GetMemberIds():
            elem = doc.GetElement(member_id)
            if not elem or not elem.Category:
                continue
            if elem.Category.Id.IntegerValue not in [
                    int(BuiltInCategory.OST_GenericModel),
                    int(BuiltInCategory.OST_SpecialityEquipment)]:
                continue
            family_name = ""
            type_name = ""
            elem_type = doc.GetElement(elem.GetTypeId())
            if elem_type:
                family_name = elem_type.FamilyName or ""
                type_name = elem_type.Name or ""
            combined = (family_name + " " + type_name).lower()
            if "erection" in combined or "mark" in combined:
                return elem
    except Exception:
        pass
    return None


def orient_3d_view_rear(view3d, assembly, erection_mark=None):
    """Isometric rear — erection-mark side visible (production 3D VIEW - REAR)."""
    if erection_mark is None:
        erection_mark = find_erection_mark_in_assembly(assembly)
    try:
        center = assembly.GetCenter()
        dist = 25.0
        asm_tr = assembly.GetTransform()
        up = asm_tr.BasisZ.Normalize()
        if erection_mark:
            mark_tr = erection_mark.GetTransform()
            back = mark_tr.BasisX.Normalize()
            side = asm_tr.BasisY.Normalize()
        else:
            back = asm_tr.BasisX.Normalize()
            side = asm_tr.BasisY.Normalize()
        eye = (center + back * dist * 0.90 - side * dist * 0.45 + up * dist * 0.55)
        forward = (center - eye).Normalize()
        view3d.SetOrientation(ViewOrientation3D(eye, up, forward))
    except Exception:
        pass


def lock_3d_view_orientation(view3d):
    try:
        if view3d and view3d.CanSaveOrientation():
            view3d.SaveOrientationAndLock()
            return True
    except Exception:
        pass
    try:
        if view3d and view3d.CanSaveOrientation():
            view3d.SaveOrientation()
    except Exception:
        pass
    return False


def create_detail_view(asm_id, orient_key, template_id, assign):
    direction = get_orientation_enum(orient_key)
    tid = template_id if template_id != INVALID_ID else None
    if tid:
        return AssemblyViewUtils.CreateDetailSection(doc, asm_id, direction, tid, assign)
    return AssemblyViewUtils.CreateDetailSection(doc, asm_id, direction)


def create_schedule_view(asm_id, sched_key, template_id, assign):
    tid = template_id if template_id != INVALID_ID else None
    if sched_key == "part_list":
        if tid:
            return AssemblyViewUtils.CreatePartList(doc, asm_id, tid, assign)
        return AssemblyViewUtils.CreatePartList(doc, asm_id)
    if sched_key == "material_tko":
        if tid:
            return AssemblyViewUtils.CreateMaterialTakeoff(doc, asm_id, tid, assign)
        return AssemblyViewUtils.CreateMaterialTakeoff(doc, asm_id)

    struct_cat = getattr(BuiltInCategory, "OST_StructConnections", None)
    if struct_cat is None:
        struct_cat = getattr(BuiltInCategory, "OST_StructuralConnectionHandler", None)
    cat_map = {
        "sched_walls":   BuiltInCategory.OST_Walls,
        "sched_generic": BuiltInCategory.OST_GenericModel,
        "sched_struct":  struct_cat,
    }
    cat = cat_map.get(sched_key)
    if cat is None:
        return None
    cat_id = ElementId(cat)
    if not ViewSchedule.IsValidCategoryForSchedule(cat_id):
        raise Exception("The selected category cannot be scheduled.")
    if sched_key == "sched_walls":
        # Create the Walls schedule first so an incompatible template cannot
        # prevent the schedule from appearing under the assembly.
        schedule = AssemblyViewUtils.CreateSingleCategorySchedule(doc, asm_id, cat_id)
        doc.Regenerate()
        if tid:
            try:
                if assign:
                    schedule.ViewTemplateId = tid
                else:
                    schedule.ApplyViewTemplateParameters(doc.GetElement(tid))
            except Exception as ex:
                output.print_md(
                    "**Wall schedule created without the selected template:** `{}`. "
                    "Select a Walls schedule template. Error: `{}`".format(
                        doc.GetElement(tid).Name, ex))
        return schedule
    if tid:
        return AssemblyViewUtils.CreateSingleCategorySchedule(doc, asm_id, cat_id, tid, assign)
    return AssemblyViewUtils.CreateSingleCategorySchedule(doc, asm_id, cat_id)


def sheet_layout_point(sheet, slot_key):
    pos = LAYOUT_POSITIONS.get(slot_key)
    if not pos:
        return XYZ(0, 0, 0)
    u, v = pos
    if slot_key in LAYOUT_COLUMN_U:
        u = LAYOUT_COLUMN_U[slot_key]
    try:
        bb = sheet.Outline
        min_u, max_u = bb.Min.U, bb.Max.U
        min_v, max_v = bb.Min.V, bb.Max.V
        draw_max_u = min_u + (max_u - min_u) * 0.72
        x = min_u + (draw_max_u - min_u) * u
        y = min_v + (max_v - min_v) * v
        return XYZ(x, y, 0)
    except Exception:
        return XYZ(u * 2.0, v * 1.5, 0)


def add_revision_to_sheet(sheet, revision_id):
    try:
        rev_ids = sheet.GetAdditionalRevisionIds()
        if revision_id not in rev_ids:
            rev_ids.Add(revision_id)
            sheet.SetAdditionalRevisionIds(rev_ids)
    except Exception:
        pass


def revision_color_schema():
    schema_id = System.Guid("45b48ef2-94c5-4cdc-9c6d-ef2a2d9a7150")
    schema = Schema.Lookup(schema_id)
    if schema is None:
        builder = SchemaBuilder(schema_id)
        builder.SetSchemaName("AssemblyViewsRevisionColor")
        builder.SetReadAccessLevel(AccessLevel.Public)
        builder.SetWriteAccessLevel(AccessLevel.Public)
        builder.SetDocumentation("Revision cloud RGB line colour used by Assembly Views Creator.")
        builder.AddSimpleField("CloudColor", System.String)
        schema = builder.Finish()
    return schema


def apply_saved_revision_colors(sheet):
    """Colour only clouds of revisions carrying this tool's saved colour."""
    schema = Schema.Lookup(System.Guid("45b48ef2-94c5-4cdc-9c6d-ef2a2d9a7150"))
    if schema is None:
        return
    colors = {}
    for revision_id in sheet.GetAllRevisionIds():
        revision = doc.GetElement(revision_id)
        entity = revision.GetEntity(schema)
        if entity.IsValid():
            rgb = entity.Get[System.String](schema.GetField("CloudColor"))
            colors[revision_id] = Color(*[int(c) for c in rgb.split(",")])
    if not colors:
        return
    owner_ids = set([sheet.Id])
    for viewport_id in sheet.GetAllViewports():
        owner_ids.add(doc.GetElement(viewport_id).ViewId)
    for cloud in FilteredElementCollector(doc).OfClass(RevisionCloud).ToElements():
        if cloud.RevisionId in colors and cloud.OwnerViewId in owner_ids:
            owner = doc.GetElement(cloud.OwnerViewId)
            overrides = owner.GetElementOverrides(cloud.Id)
            overrides.SetProjectionLineColor(colors[cloud.RevisionId])
            owner.SetElementOverrides(cloud.Id, overrides)


def create_revision(description, date_text, issued_by="", issued_to="", cloud_color=None):
    rev = Revision.Create(doc)
    rev.Description = description or "New Revision"
    rev.RevisionDate = date_text or ""
    rev.IssuedBy = issued_by or ""
    rev.IssuedTo = issued_to or ""
    if cloud_color is not None:
        schema = revision_color_schema()
        entity = Entity(schema)
        entity.Set[System.String](schema.GetField("CloudColor"),
                                  ",".join(str(c) for c in cloud_color))
        rev.SetEntity(entity)
    return rev


# ═══════════════════════════════════════════════════════════════════════════════
# UI DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ComboItem(object):
    def __init__(self, id_val, label):
        self.Id = id_val
        self.Label = label


class AssemblyRow(INotifyPropertyChanged):
    def __init__(self, assembly, has_sheet):
        self.Assembly = assembly
        self.Id = assembly.Id
        self.Name = assembly.AssemblyTypeName
        self.SheetStatus = "Yes" if has_sheet else "No"
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


class ViewOptionRow(INotifyPropertyChanged):
    def __init__(self, key, default_prefix, layout_key, default_on,
                 templates, viewports):
        self.Key = key
        self._name_prefix = default_prefix
        self._title_on_sheet = DEFAULT_TITLE_ON_SHEET.get(
            key, "{} - {{assembly}}".format(default_prefix))
        self.LayoutKey = layout_key
        self.ViewTypeLabel = VIEW_TYPE_LABELS.get(key, key)
        self._is_enabled = default_on
        self.AssignTemplate = True
        self.IsViewportView = key != "wall_schedule"
        self._pch = None

        self.TemplateChoices = ObservableCollection[object]()
        self.ViewportChoices = ObservableCollection[object]()
        for t in templates:
            self.TemplateChoices.Add(t)
        for vp in viewports:
            self.ViewportChoices.Add(vp)

        self._selected_template = match_default_template(
            key, default_prefix, templates)
        self._selected_viewport = match_default_viewport(key, viewports)

    @property
    def SelectedTemplate(self):
        return self._selected_template

    @SelectedTemplate.setter
    def SelectedTemplate(self, value):
        if self._selected_template != value:
            self._selected_template = value
            self._fire("SelectedTemplate")

    @property
    def SelectedViewport(self):
        return self._selected_viewport

    @SelectedViewport.setter
    def SelectedViewport(self, value):
        if self._selected_viewport != value:
            self._selected_viewport = value
            self._fire("SelectedViewport")

    @property
    def NamePrefix(self):
        return self._name_prefix

    @NamePrefix.setter
    def NamePrefix(self, value):
        if self._name_prefix != value:
            self._name_prefix = value
            self._fire("NamePrefix")

    @property
    def TitleOnSheet(self):
        return self._title_on_sheet

    @TitleOnSheet.setter
    def TitleOnSheet(self, value):
        if self._title_on_sheet != value:
            self._title_on_sheet = value
            self._fire("TitleOnSheet")

    @property
    def IsEnabled(self):
        return self._is_enabled

    @IsEnabled.setter
    def IsEnabled(self, value):
        if self._is_enabled != value:
            self._is_enabled = value
            self._fire("IsEnabled")

    def add_PropertyChanged(self, handler):
        self._pch = System.Delegate.Combine(self._pch, handler)

    def remove_PropertyChanged(self, handler):
        self._pch = System.Delegate.Remove(self._pch, handler)

    def _fire(self, name):
        if self._pch:
            self._pch(self, PropertyChangedEventArgs(name))


# ═══════════════════════════════════════════════════════════════════════════════
# WPF UI
# ═══════════════════════════════════════════════════════════════════════════════

class AssemblyViewsCreatorUI(Window):
    def __init__(self):
        path_xaml = os.path.join(PATH_SCRIPT, "AssemblyViewsCreatorUI.xaml")
        wpf.LoadComponent(self, path_xaml)

        self._templates = get_view_templates()
        self._detail_types = get_detail_view_types()
        self.UI_combo_detail_type.ItemsSource = self._detail_types
        self.UI_combo_detail_type.SelectedIndex = 0
        for item in self._detail_types:
            if "".join(item.Label.lower().split()) == "06.productiondetail":
                self.UI_combo_detail_type.SelectedItem = item
                break
        self.UI_combo_detail_type.ToolTip = (
            "06. Production Detail selected for section/callout marks."
            if self.UI_combo_detail_type.SelectedIndex > 0 else
            "06. Production Detail was not found in this project. Load that detail type or choose an available type.")
        self._viewports = get_viewport_types()
        if len(self._viewports) <= 1:
            output.print_md(
                "⚠️ **No viewport types found** in this project. "
                "Place at least one viewport on a sheet, or define viewport types "
                "in Revit (Manage → Settings), then reload the tool.")
        self._title_blocks = get_title_blocks()
        self._revisions = get_revisions_combo()
        self._asm_sheet_map = build_assembly_sheet_map()
        self._all_assemblies = collect_assemblies()
        self._assembly_selection_ids = set()

        self._setup_filters()
        self._setup_title_blocks()
        self._setup_sheet_parameters()
        self._setup_revisions()
        self._setup_view_grid()
        self._refresh_assembly_grid()

        self._layout_from_sheet = capture_layout_from_active_sheet()
        if self._layout_from_sheet:
            forms.toast(
                "Viewport layout loaded from active sheet: {}".format(
                    __revit__.ActiveUIDocument.ActiveView.Name),
                title="Assembly Views Creator")
        else:
            forms.toast(
                "Open your template sheet first for exact viewport positions.",
                title="Assembly Views Creator")

        self.result = None
        self.ShowDialog()

    def _setup_filters(self):
        self.UI_combo_asm_filter.Items.Clear()
        for label in ["All assemblies", "Assemblies with sheets", "Assemblies without sheets"]:
            self.UI_combo_asm_filter.Items.Add(label)
        self.UI_combo_asm_filter.SelectedIndex = 0

    def _setup_title_blocks(self):
        self.UI_combo_title_block.ItemsSource = self._title_blocks
        if self._title_blocks:
            self.UI_combo_title_block.SelectedIndex = 0

    def _setup_sheet_parameters(self):
        """Default title block fields (match production sheet)."""
        self.UI_txt_drawn_by.Text = "Author"
        self.UI_txt_checked_by.Text = "Checker"
        self.UI_txt_designed_by.Text = "JM"
        self.UI_txt_approved_by.Text = "Approver"
        try:
            self.UI_date_sheet_issue.SelectedDate = System.DateTime.Now
        except Exception:
            pass

    def _get_sheet_params(self):
        params = {}
        for pname, textbox in [
            ("Drawn By", self.UI_txt_drawn_by),
            ("Checked By", self.UI_txt_checked_by),
            ("Designed By", self.UI_txt_designed_by),
            ("Approved By", self.UI_txt_approved_by),
        ]:
            val = textbox.Text.strip()
            if val:
                params[pname] = val
        try:
            if self.UI_date_sheet_issue.SelectedDate:
                params["Sheet Issue Date"] = (
                    self.UI_date_sheet_issue.SelectedDate.ToString("MM/dd/yy"))
        except Exception:
            pass
        return params

    def _setup_revisions(self):
        self.UI_combo_revisions.ItemsSource = None
        self.UI_combo_revisions.Items.Clear()
        for item in self._revisions:
            self.UI_combo_revisions.Items.Add(item)
        if self._revisions:
            self.UI_combo_revisions.SelectedIndex = 0
        self.UI_txt_rev_date.Text = System.DateTime.Now.ToString("dd/MM/yyyy")
        for label, rgb in [
                ("Default (project colour)", None), ("Red", (220, 38, 38)),
                ("Blue", (37, 99, 235)), ("Green", (22, 163, 74)),
                ("Orange", (234, 88, 12)), ("Purple", (124, 58, 237)),
                ("Black", (0, 0, 0))]:
            self.UI_combo_rev_color.Items.Add(ComboItem(rgb, label))
        self.UI_combo_rev_color.SelectedIndex = 0
        self.UIe_rev_mode_changed(None, None)

    def _setup_view_grid(self):
        rows = ObservableCollection[object]()
        for key, prefix, orient, layout, default_on in VIEW_DEFS:
            rows.Add(ViewOptionRow(
                key, prefix, layout, default_on,
                self._templates, self._viewports))
        self.UI_dg_views.ItemsSource = rows

    def _current_asm_filter(self):
        idx = self.UI_combo_asm_filter.SelectedIndex
        if idx == 1:
            return "with"
        if idx == 2:
            return "without"
        return "all"

    def _refresh_assembly_grid(self):
        filt = self._current_asm_filter()
        rows = ObservableCollection[object]()
        for asm in sorted(self._all_assemblies, key=lambda a: a.AssemblyTypeName):
            has_sheet = asm.Id in self._asm_sheet_map
            if filt == "with" and not has_sheet:
                continue
            if filt == "without" and has_sheet:
                continue
            row = AssemblyRow(asm, has_sheet)
            row.IsSelected = asm.Id in self._assembly_selection_ids
            row.add_PropertyChanged(PropertyChangedEventHandler(self._assembly_selection_changed))
            rows.Add(row)
        self.UI_dg_assemblies.ItemsSource = rows
        self._update_asm_count()

    def _update_asm_count(self):
        rows = self.UI_dg_assemblies.ItemsSource
        if rows is None:
            return
        total = rows.Count
        sel = len(self._assembly_selection_ids)
        self.UI_txt_asm_count.Text = "{} selected  |  {} shown".format(sel, total)

    def _assembly_selection_changed(self, sender, e):
        if e.PropertyName != "IsSelected":
            return
        if sender.IsSelected:
            self._assembly_selection_ids.add(sender.Assembly.Id)
        else:
            self._assembly_selection_ids.discard(sender.Assembly.Id)
        self._update_asm_count()

    def UIe_asm_row_click(self, sender, e):
        """A row click toggles once; the checkbox handles its own click."""
        node = e.OriginalSource
        while node is not None:
            if isinstance(node, CheckBox):
                return
            if isinstance(node, DataGridRow):
                row = node.Item
                row.IsSelected = not row.IsSelected
                sender.SelectedItem = row
                sender.Focus()
                e.Handled = True
                return
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                node = getattr(node, "Parent", None)

    def _collect_settings(self):
        selected = [asm for asm in self._all_assemblies
                    if asm.Id in self._assembly_selection_ids]
        if not selected:
            forms.alert("Select at least one assembly.", exitscript=False)
            return None

        view_rows = []
        for row in self.UI_dg_views.ItemsSource:
            if row.IsEnabled:
                view_rows.append(row)

        if not view_rows:
            forms.alert("Enable at least one view to create.", exitscript=False)
            return None

        tb = self.UI_combo_title_block.SelectedItem
        if self.UI_chk_create_sheet.IsChecked and (tb is None):
            forms.alert("Select a title block for sheet creation.", exitscript=False)
            return None

        rev_id = None
        new_rev_data = None
        if self.UI_chk_create_sheet.IsChecked:
            if self.UI_rb_rev_new.IsChecked:
                if not self.UI_txt_rev_desc.Text.strip():
                    forms.alert("Enter a description for the new revision.", exitscript=False)
                    return None
                new_rev_data = (
                    self.UI_txt_rev_desc.Text.strip(),
                    self.UI_txt_rev_date.Text.strip(),
                    self.UI_txt_rev_author.Text.strip(),
                    self.UI_txt_rev_issued_to.Text.strip(),
                    self.UI_combo_rev_color.SelectedItem.Id,
                )
            else:
                item = self.UI_combo_revisions.SelectedItem
                if item:
                    rev_id = item.Id

        sheet_params = self._get_sheet_params()
        if new_rev_data and self.UI_txt_rev_drawn_by.Text.strip():
            sheet_params["Drawn By"] = self.UI_txt_rev_drawn_by.Text.strip()
        return {
            "assemblies": selected,
            "view_rows": view_rows,
            "scale": DEFAULT_VIEW_SCALE,
            "create_sheet": bool(self.UI_chk_create_sheet.IsChecked),
            "sheet_name": self.UI_txt_sheet_name.Text.strip(),
            "title_block_id": tb.Id if tb else INVALID_ID,
            "revision_id": rev_id,
            "new_revision": new_rev_data,
            "sheet_params": sheet_params,
            "detail_type_id": self.UI_combo_detail_type.SelectedItem.Id,
        }

    # ── events ────────────────────────────────────────────────────────────────

    def UIe_header_drag(self, sender, e):
        try:
            self.DragMove()
        except Exception:
            pass

    def UIe_header_btn_close(self, sender, e):
        self.Close()
        sys.exit()

    def UIe_asm_filter_changed(self, sender, e):
        self._refresh_assembly_grid()

    def UIe_asm_select_all(self, sender, e):
        for r in self.UI_dg_assemblies.ItemsSource:
            r.IsSelected = True
        self._update_asm_count()

    def UIe_asm_select_none(self, sender, e):
        self._assembly_selection_ids.clear()
        for r in self.UI_dg_assemblies.ItemsSource:
            r.IsSelected = False
        self._update_asm_count()

    def UIe_rev_mode_changed(self, sender, e):
        # Checked events can fire while XAML is still being loaded.
        if not hasattr(self, "UI_combo_rev_color") or self.UI_combo_rev_color is None:
            return
        use_new = self.UI_rb_rev_new.IsChecked
        self.UI_combo_revisions.IsEnabled = not use_new
        self.UI_txt_rev_desc.IsEnabled = use_new
        self.UI_txt_rev_date.IsEnabled = use_new
        self.UI_txt_rev_author.IsEnabled = use_new
        self.UI_txt_rev_issued_to.IsEnabled = use_new
        self.UI_txt_rev_drawn_by.IsEnabled = use_new
        self.UI_combo_rev_color.IsEnabled = use_new

    def UIe_btn_run(self, sender, e):
        self.UI_dg_assemblies.CommitEdit()
        self.UI_dg_views.CommitEdit()
        settings = self._collect_settings()
        if settings:
            self.result = settings
            self.Close()


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW CREATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_view_def(key):
    for item in VIEW_DEFS:
        if item[0] == key:
            return item
    return None


def migrate_horizontal_view_names(assembly):
    """Correct the old TOP VIEW / ELEVATION TOP pair once, retaining their IDs."""
    asm_name = assembly.AssemblyTypeName
    old_top = find_view_by_name(format_view_name("TOP VIEW", asm_name))
    old_elevation = find_view_by_name(format_view_name("ELEVATION TOP", asm_name))
    corrected_section = find_view_by_name(format_view_name("SECTION 2-2", asm_name))
    if old_elevation is None or corrected_section is not None:
        return
    for view in (old_top, old_elevation):
        if view is not None and (not isinstance(view, ViewSection)
                                 or view.AssociatedAssemblyInstanceId != assembly.Id):
            raise Exception("Cannot correct horizontal views: matching view belongs to another assembly.")
    # Free the TOP VIEW name before moving the top-face view into that role.
    if old_top is not None:
        old_top.Name = format_view_name("SECTION 2-2", asm_name)
        set_view_title_on_sheet_param(old_top, "SECTION")
    old_elevation.Name = format_view_name("TOP VIEW", asm_name)
    set_view_title_on_sheet_param(old_elevation, "TOP VIEW")
    doc.Regenerate()


def create_or_get_view(assembly, view_row, scale_value):
    """Create assembly view (or reuse by name). Returns (view, layout_key)."""
    asm_name = assembly.AssemblyTypeName
    asm_id = assembly.Id
    view_name = format_view_name(view_row.NamePrefix, asm_name)

    sel_tpl = view_row.SelectedTemplate
    template_id = sel_tpl.Id if sel_tpl else INVALID_ID
    assign = view_row.AssignTemplate

    if view_row.Key == "wall_schedule":
        # Reuse only an assembly-owned Walls schedule, never the old Part List.
        existing = None
        for schedule in FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements():
            if (not schedule.IsTemplate
                    and schedule.AssociatedAssemblyInstanceId == asm_id
                    and schedule.Definition.CategoryId == ElementId(BuiltInCategory.OST_Walls)):
                existing = schedule
                break
    else:
        existing = find_view_by_name(view_name)
    if existing:
        apply_view_scale(existing, scale_value)
        if template_id != INVALID_ID:
            apply_template(existing, template_id, assign)
        vdef = resolve_view_def(view_row.Key)
        layout = vdef[3] if vdef else view_row.LayoutKey
        return existing, layout

    vdef = resolve_view_def(view_row.Key)
    if not vdef:
        return None, None

    orient_key = vdef[2]
    layout_key = vdef[3]
    view = None

    try:
        if orient_key == "3d_front":
            view = create_3d_assembly_view(asm_id, template_id, assign)
            setup_3d_view_front(view, assembly)
        elif orient_key == "3d_rear":
            view = create_3d_assembly_view(asm_id, template_id, assign)
            setup_3d_view_rear(view, assembly)
        elif orient_key in ("part_list", "material_tko", "sched_walls",
                            "sched_generic", "sched_struct"):
            view = create_schedule_view(asm_id, orient_key, template_id, assign)
            if view and view_row.Key == "wall_schedule":
                doc.Regenerate()
                set_view_name(view, asm_name)
                return view, layout_key
        else:
            view = create_detail_view(asm_id, orient_key, template_id, assign)
    except Exception as ex:
        output.print_md("⚠️ {} — `{}`".format(view_name, ex))
        return None, layout_key

    if view:
        set_view_name(view, view_name)
        apply_view_scale(view, scale_value)
    return view, layout_key


def set_viewport_detail_number(viewport, detail_number):
    try:
        p = viewport.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
        if p and not p.IsReadOnly:
            p.Set(detail_number)
            return True
    except Exception:
        pass
    return False


def get_viewport_on_sheet(sheet_id, view_id):
    for vp in FilteredElementCollector(doc, sheet_id).OfClass(Viewport).ToElements():
        try:
            if vp.ViewId == view_id:
                return vp
        except Exception:
            pass
    return None


def place_viewport(sheet, view, center, viewport_type_id, title_on_sheet):
    if not Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
        return None
    set_view_title_on_sheet_param(view, title_on_sheet)
    vp = Viewport.Create(doc, sheet.Id, view.Id, center)
    if vp and viewport_type_id != INVALID_ID:
        try:
            if vp.GetTypeId() != viewport_type_id:
                vp.ChangeTypeId(viewport_type_id)
        except Exception:
            pass
    if vp:
        fit_viewport_title_line(vp, title_on_sheet)
    return vp


def move_viewport_to_center(viewport, center):
    """Move viewport box center on sheet (SetBoxCenter, then MoveElement fallback)."""
    try:
        current = viewport.GetBoxCenter()
        target = XYZ(center.X, center.Y, current.Z)
        viewport.SetBoxCenter(target)
        return True
    except Exception:
        pass
    try:
        delta = center - viewport.GetBoxCenter()
        if delta.GetLength() > 0.0001:
            ElementTransformUtils.MoveElement(doc, viewport.Id, delta)
            return True
    except Exception:
        pass
    return False


def place_or_move_viewport(sheet, view, layout_key, viewport_type_id, title_on_sheet):
    """Place a new viewport or move an existing one to the layout slot."""
    center = sheet_layout_point(sheet, layout_key)
    if isinstance(view, ViewSchedule):
        doc.Regenerate()
        for inst in (FilteredElementCollector(doc, sheet.Id)
                     .OfClass(ScheduleSheetInstance).ToElements()):
            if inst.ScheduleId == view.Id:
                inst.Point = center
                return None
        ScheduleSheetInstance.Create(doc, sheet.Id, view.Id, center)
        return None
    existing = get_viewport_on_sheet(sheet.Id, view.Id)
    set_view_title_on_sheet_param(view, title_on_sheet)
    if existing:
        move_viewport_to_center(existing, center)
        if viewport_type_id != INVALID_ID:
            try:
                if existing.GetTypeId() != viewport_type_id:
                    existing.ChangeTypeId(viewport_type_id)
            except Exception:
                pass
        fit_viewport_title_line(existing, title_on_sheet)
        return existing
    vp = place_viewport(sheet, view, center, viewport_type_id, title_on_sheet)
    if vp:
        move_viewport_to_center(vp, center)
    return vp


def number_viewports_by_sheet_order(placed_viewports):
    """Detail numbers 01–08: section_a=03, section_b=04 (production order)."""
    if not placed_viewports:
        return
    by_slot = {}
    for item in placed_viewports:
        if len(item) >= 3:
            by_slot[item[2]] = item[0]
    # Free existing numbers first, including the old swapped 04/05 pair.
    for slot, vp in by_slot.items():
        if not set_viewport_detail_number(vp, "AVC-{}".format(vp.Id)):
            raise Exception("Could not reset detail number for {}.".format(slot))
    for n, slot in enumerate(VIEWPORT_DETAIL_NUMBER_ORDER, 1):
        vp = by_slot.get(slot)
        if vp:
            if not set_viewport_detail_number(vp, "{:02d}".format(n)):
                raise Exception("Could not assign detail number {:02d} to {}.".format(n, slot))


def process_assembly(assembly, settings, report):
    asm_name = assembly.AssemblyTypeName
    if not assembly.AllowsAssemblyViewCreation():
        raise Exception("Assembly does not allow view creation.")
    created_views = []
    if any(row.Key in ("plan", "section_b") for row in settings["view_rows"]):
        migrate_horizontal_view_names(assembly)

    for view_row in settings["view_rows"]:
        view, layout_key = create_or_get_view(assembly, view_row, settings["scale"])
        if view:
            apply_detail_view_type(view, settings.get("detail_type_id", INVALID_ID))
            if isinstance(view, ViewSection) and view_row.SelectedTemplate:
                apply_template(view, view_row.SelectedTemplate.Id, view_row.AssignTemplate)
            created_views.append((view, layout_key, view_row))

    sheet = None
    if settings["create_sheet"]:
        sheet_num = sanitize_name(asm_name)
        sheet = get_assembly_sheet(assembly.Id)
        if sheet is None:
            sheet = create_assembly_sheet(
                assembly,
                settings["title_block_id"],
                settings["sheet_name"],
                sheet_num)
        else:
            rename_sheet(sheet, settings["sheet_name"], sheet_num)

        if settings.get("sheet_params"):
            apply_sheet_parameters(sheet, settings["sheet_params"])

        rev_id = settings["revision_id"]
        if settings["new_revision"] and not rev_id:
            rev = create_revision(*settings["new_revision"])
            rev_id = rev.Id
            # Share the new revision across all selected sheets in this run.
            settings["revision_id"] = rev_id
        if rev_id:
            add_revision_to_sheet(sheet, rev_id)

        placed_viewports = []
        for view, layout_key, view_row in created_views:
            if not layout_key:
                continue
            pt = sheet_layout_point(sheet, layout_key)
            vp_type = view_row.SelectedViewport.Id
            sheet_title = resolve_title_on_sheet(view_row, asm_name)
            vp = place_or_move_viewport(
                sheet, view, layout_key, vp_type, sheet_title)
            if vp:
                placed_viewports.append((vp, pt, layout_key))

        number_viewports_by_sheet_order(placed_viewports)
        doc.Regenerate()
        apply_saved_revision_colors(sheet)

    report.append({
        "assembly": asm_name,
        "views": len(created_views),
        "sheet": sheet.SheetNumber if sheet else None,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

exit_flag = False
try:
    ui = AssemblyViewsCreatorUI()
    settings = ui.result
except SystemExit:
    exit_flag = True
except Exception:
    output.print_md("**Error opening UI**")
    import traceback
    print(traceback.format_exc())
    sys.exit()

if exit_flag or not settings:
    sys.exit()

report = []
errors = []

t = Transaction(doc, "Assembly Views & Sheets Creator")
t.Start()

try:
    with forms.ProgressBar(title="Creating assembly views...") as pb:
        assemblies = settings["assemblies"]
        for i, asm in enumerate(assemblies):
            pb.update_progress(i, len(assemblies))
            try:
                process_assembly(asm, settings, report)
            except Exception as ex:
                errors.append((asm.AssemblyTypeName, str(ex)))
    t.Commit()
except Exception:
    t.RollBack()
    output.print_md("**Transaction failed — rolled back**")
    import traceback
    print(traceback.format_exc())
    sys.exit()

output.print_md("### Assembly Views & Sheets — Complete")
output.print_md("**{}** assembly(s) processed".format(len(report)))

for item in report:
    sheet_info = item["sheet"] if item["sheet"] else "—"
    output.print_md("- **{}** — {} view(s), sheet `{}`".format(
        item["assembly"], item["views"], sheet_info))

if errors:
    output.print_md("### Errors")
    for name, msg in errors:
        output.print_md("- **{}**: `{}`".format(name, msg))

forms.alert(
    "Finished.\n{} assembly(s) processed.\nSee pyRevit output for details.".format(
        len(report)),
    exitscript=False)
