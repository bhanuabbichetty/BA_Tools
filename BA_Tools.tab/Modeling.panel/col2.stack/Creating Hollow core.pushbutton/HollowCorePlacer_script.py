# -*- coding: utf-8 -*-
"""
Hollow Core Placer - Multi-Select Version with Edge Fill
Places hollow cores within multiple slab boundaries using Z Offset Value parameter
FIXED: Only uses z Offset Value parameter, sets extensions to 0
"""
__title__ = 'Place Hollow\nCore Slabs'
__doc__ = 'Place hollow core slabs within multiple floor boundaries'

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
from Autodesk.Revit.DB.Structure import StructuralType, StructuralFramingUtils
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import revit, script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()


# ==============================================================================
# SELECTION FILTER
# ==============================================================================

class FloorSelectionFilter(ISelectionFilter):
    """Filter to allow only Floor selection"""
    def AllowElement(self, element):
        return isinstance(element, Floor)
    
    def AllowReference(self, reference, point):
        return False


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_floor_boundary_curves(floor):
    """Get the outer boundary curves of a floor"""
    curves = []
    try:
        deps = floor.GetDependentElements(ElementClassFilter(Sketch))
        if deps:
            sk = doc.GetElement(list(deps)[0])
            prof = sk.Profile
            for ca in prof:
                for c in ca:
                    curves.append(c)
    except Exception:
        pass

    if not curves:
        try:
            opt = Options()
            geo = floor.get_Geometry(opt)
            for g in geo:
                if isinstance(g, Solid):
                    for face in g.Faces:
                        for loop in face.EdgeLoops:
                            for e in loop:
                                curves.append(e.AsCurve())
                    break
        except Exception:
            pass

    return curves


def principal_axis_from_points(points):
    """Calculate principal axis using PCA"""
    if not points:
        return XYZ(1,0,0)
    n = float(len(points))
    mean_x = sum(p.X for p in points) / n
    mean_y = sum(p.Y for p in points) / n
    cov_xx = sum((p.X - mean_x)*(p.X - mean_x) for p in points) / n
    cov_yy = sum((p.Y - mean_y)*(p.Y - mean_y) for p in points) / n
    cov_xy = sum((p.X - mean_x)*(p.Y - mean_y) for p in points) / n
    trace = cov_xx + cov_yy
    diff = cov_xx - cov_yy
    disc = math.sqrt((diff*diff)/4.0 + cov_xy*cov_xy)
    lambda1 = trace/2.0 + disc
    vx = cov_xy
    vy = lambda1 - cov_xx
    if abs(vx) < 1e-9 and abs(vy) < 1e-9:
        vx, vy = 1.0, 0.0
    norm = math.hypot(vx, vy)
    return XYZ(vx / norm, vy / norm, 0.0)


def get_floor_span_direction(floor):
    """Get principal axis direction using PCA"""
    curves = get_floor_boundary_curves(floor)
    if not curves:
        return XYZ(1,0,0)
    pts = []
    for c in curves:
        try:
            pts.append(c.GetEndPoint(0))
            pts.append(c.GetEndPoint(1))
        except Exception:
            continue
    if not pts:
        return XYZ(1,0,0)
    axis = principal_axis_from_points(pts)
    return XYZ(axis.X, axis.Y, 0.0).Normalize()


def get_floor_level_and_offset(floor):
    """Get floor level and offset"""
    level = doc.GetElement(floor.LevelId)
    param = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    off = param.AsDouble() if param else 0.0
    return level, off


def get_structural_framing_families():
    """Get all Structural Framing family types"""
    collector = FilteredElementCollector(doc)\
        .OfClass(FamilySymbol)\
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
    
    syms = []
    for s in collector:
        try:
            _ = s.Family.Name
            syms.append(s)
        except Exception:
            continue
    return syms


def place_hollow_core_on_floor(floor, family_type, core_width_mm, z_offset_mm, flip_orientation=False):
    """
    Place hollow core slabs across floor
    FIXED VERSION:
    - Hollow cores placed at floor level (same as slab)
    - Z offset applied ONLY using z Offset Value parameter (NOT Start/End Level Offset)
    - Start Extension and End Extension set to 0.0 (cores end at slab edges)
    - Cores span the full length of slab
    - Cores placed side by side within slab boundary
    - Joins disallowed at both ends
    - Edge fill: if remainder > 100mm, add one more core to fill gap
    """
    mm_to_ft = 1.0 / 304.8
    core_width_ft = core_width_mm * mm_to_ft
    z_offset_ft = z_offset_mm * mm_to_ft

    boundary_curves = get_floor_boundary_curves(floor)
    if not boundary_curves:
        forms.alert("Could not get floor boundary", title="Error")
        return 0

    level, floor_offset = get_floor_level_and_offset(floor)
    
    # Get span direction (direction hollow cores will run)
    span_dir = get_floor_span_direction(floor)
    
    # If user asked to flip, rotate span_dir by 90 deg
    if flip_orientation:
        span_dir = XYZ(-span_dir.Y, span_dir.X, 0).Normalize()
        output.print_md("**Span direction rotated 90°**")

    # Placement direction (perpendicular to span - where we place side by side)
    place_dir = XYZ(-span_dir.Y, span_dir.X, 0)
    try:
        place_dir = place_dir.Normalize()
    except Exception:
        place_dir = XYZ(1,0,0)

    # Find min/max extents in both directions
    min_place = float('inf')
    max_place = float('-inf')
    min_span = float('inf')
    max_span = float('-inf')
    pts = []
    
    for c in boundary_curves:
        try:
            for i in range(2):
                p = c.GetEndPoint(i)
                pts.append(p)
                proj_place = p.DotProduct(place_dir)
                proj_span = p.DotProduct(span_dir)
                min_place = min(min_place, proj_place)
                max_place = max(max_place, proj_place)
                min_span = min(min_span, proj_span)
                max_span = max(max_span, proj_span)
        except Exception:
            continue

    if not pts:
        forms.alert("Could not sample floor boundary points", title="Error")
        return 0

    bbox = floor.get_BoundingBox(None)
    center = (bbox.Min + bbox.Max) * 0.5
    center_proj_place = center.DotProduct(place_dir)

    total_width = max_place - min_place
    if total_width <= 0:
        forms.alert("Invalid floor extents (zero width)", title="Error")
        return 0

    # Calculate how many full pieces fit
    # Add small tolerance (0.5mm) to handle floating-point precision errors
    tolerance = 0.5 * mm_to_ft  # 0.5mm tolerance
    num_full = int((total_width + tolerance) / core_width_ft)
    
    # Safety check: ensure last core doesn't exceed boundary
    if num_full * core_width_ft > total_width + core_width_ft * 0.01:  # 1% tolerance
        num_full = max(1, num_full - 1)
    
    remainder = total_width - (num_full * core_width_ft)
    
    # Check if we should add edge cores to fill gaps
    # If remainder is > 100mm (significant gap), add one more core at the edge
    min_gap_for_edge_core = 100 * mm_to_ft  # 100mm minimum gap
    add_edge_core = remainder > min_gap_for_edge_core
    
    if add_edge_core:
        num_to_place = num_full + 1  # Add one more to fill the edge
        output.print_md("**Edge Fill**: Adding 1 extra core to fill gap (will extend beyond boundary)")
    else:
        num_to_place = num_full

    output.print_md("**Floor Width**: {:.2f} mm".format(total_width * 304.8))
    output.print_md("**Full Cores (1200mm)**: {}".format(num_full))
    output.print_md("**Remainder**: {:.2f} mm".format(remainder * 304.8))
    if add_edge_core:
        output.print_md("**Edge Core**: 1 additional core will be placed (extends beyond boundary)")
        output.print_md("**Total Cores to Place**: {}".format(num_to_place))
    else:
        output.print_md("**Total Cores to Place**: {}".format(num_to_place))

    span_length = max_span - min_span
    if span_length <= 0:
        span_length = 20.0 * 3.28083989501312  # fallback 20m

    output.print_md("**Span Length**: {:.2f} mm".format(span_length * 304.8))

    placed = 0
    if not family_type.IsActive:
        family_type.Activate()
        try:
            doc.Regenerate()
        except Exception:
            pass

    # Starting position: first hollow core centered at min_place + half width
    base_center_proj = min_place + core_width_ft * 0.5

    # Place hollow cores - align from minimum edge (start from one side)
    for i in range(num_to_place):
        desired_proj = base_center_proj + i * core_width_ft
        offset_along = desired_proj - center_proj_place
        center2d = center + place_dir.Multiply(offset_along)
        
        # ===================================================================
        # CRITICAL: Place beam at LEVEL ELEVATION ONLY (not floor_offset)
        # We'll apply floor_offset + z_offset via "z Offset Value" parameter
        # ===================================================================
        center_pt = XYZ(center2d.X, center2d.Y, level.Elevation)
        
        # Create hollow core spanning full length - END AT SLAB EDGES
        # Use exact min/max span to end at boundaries
        p1 = center_pt + span_dir.Multiply(min_span - center.DotProduct(span_dir))
        p2 = center_pt + span_dir.Multiply(max_span - center.DotProduct(span_dir))
        line = Line.CreateBound(p1, p2)
        
        try:
            # Create the hollow core instance at the LEVEL elevation (no offset in geometry)
            inst = doc.Create.NewFamilyInstance(line, family_type, level, StructuralType.Beam)
            placed += 1
            
            # ===================================================================
            # FIX 1: SET START AND END EXTENSIONS TO 0.0 (END AT SLAB EDGES)
            # ===================================================================
            try:
                # Set Start Extension to 0
                start_ext_param = inst.get_Parameter(BuiltInParameter.START_EXTENSION)
                if start_ext_param and not start_ext_param.IsReadOnly:
                    start_ext_param.Set(0.0)
                
                # Set End Extension to 0
                end_ext_param = inst.get_Parameter(BuiltInParameter.END_EXTENSION)
                if end_ext_param and not end_ext_param.IsReadOnly:
                    end_ext_param.Set(0.0)
            except Exception as e:
                output.print_md("⚠ Could not set extensions to 0 for core #{}: {}".format(i + 1, str(e)))
            
            # ===================================================================
            # FIX 2: FORCE START/END LEVEL OFFSETS TO 0 
            # These MUST stay at 0 - we use z Offset Value instead
            # ===================================================================
            try:
                # Start Level Offset = 0
                start_offset_param = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION)
                if start_offset_param and not start_offset_param.IsReadOnly:
                    start_offset_param.Set(0.0)
                
                # End Level Offset = 0
                end_offset_param = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION)
                if end_offset_param and not end_offset_param.IsReadOnly:
                    end_offset_param.Set(0.0)
            except Exception as e:
                output.print_md("⚠ Could not set Start/End Level Offsets to 0 for core #{}: {}".format(i + 1, str(e)))
            
            # DISALLOW JOINS at both ends
            try:
                # Disallow join at start (0) and end (1)
                StructuralFramingUtils.DisallowJoinAtEnd(inst, 0)
                StructuralFramingUtils.DisallowJoinAtEnd(inst, 1)
            except Exception as e:
                output.print_md("⚠ Could not disallow joins for core #{}: {}".format(i + 1, str(e)))
            
            # ===================================================================
            # FIX 3: APPLY TOTAL OFFSET (floor_offset + z_offset) VIA z Offset Value
            # This is the ONLY place where vertical positioning happens
            # ===================================================================
            total_offset_ft = floor_offset + z_offset_ft
            
            try:
                # Try "z Offset Value" parameter (lowercase z)
                z_offset_param = inst.LookupParameter("z Offset Value")
                if z_offset_param and not z_offset_param.IsReadOnly:
                    z_offset_param.Set(total_offset_ft)
                    output.print_md("✓ Core #{}: Set 'z Offset Value' = {:.2f}mm (floor offset {:.2f} + user offset {:.2f})".format(
                        i + 1, 
                        total_offset_ft * 304.8,
                        floor_offset * 304.8,
                        z_offset_ft * 304.8
                    ))
                else:
                    # Try "Z Offset Value" (uppercase Z)
                    z_offset_param = inst.LookupParameter("Z Offset Value")
                    if z_offset_param and not z_offset_param.IsReadOnly:
                        z_offset_param.Set(total_offset_ft)
                        output.print_md("✓ Core #{}: Set 'Z Offset Value' = {:.2f}mm".format(i + 1, total_offset_ft * 304.8))
                    else:
                        # If parameter doesn't exist, use element move as last resort
                        if abs(total_offset_ft) > 1e-9:
                            translation = XYZ(0, 0, total_offset_ft)
                            ElementTransformUtils.MoveElement(doc, inst.Id, translation)
                            output.print_md("✓ Core #{}: Moved element by {:.2f}mm (parameter not found)".format(
                                i + 1, 
                                total_offset_ft * 304.8
                            ))
            except Exception as e:
                output.print_md("⚠ Could not apply offset for core #{}: {}".format(i + 1, str(e)))
            
            # ===================================================================
            # VERIFY: Double-check Start/End Level Offsets are still 0
            # ===================================================================
            try:
                start_offset_check = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION)
                end_offset_check = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION)
                
                if start_offset_check and abs(start_offset_check.AsDouble()) > 1e-9:
                    output.print_md("⚠ WARNING Core #{}: Start Level Offset = {:.2f}mm (should be 0!)".format(
                        i + 1,
                        start_offset_check.AsDouble() * 304.8
                    ))
                    # Try to force it back to 0
                    if not start_offset_check.IsReadOnly:
                        start_offset_check.Set(0.0)
                        output.print_md("  → Reset to 0")
                
                if end_offset_check and abs(end_offset_check.AsDouble()) > 1e-9:
                    output.print_md("⚠ WARNING Core #{}: End Level Offset = {:.2f}mm (should be 0!)".format(
                        i + 1,
                        end_offset_check.AsDouble() * 304.8
                    ))
                    # Try to force it back to 0
                    if not end_offset_check.IsReadOnly:
                        end_offset_check.Set(0.0)
                        output.print_md("  → Reset to 0")
            except Exception:
                pass
        
        except Exception as e:
            output.print_md("**Warning**: Could not place element {}: {}".format(i+1, str(e)))
            continue

    return placed


# ==============================================================================
# FAMILY TYPE ITEM CLASS
# ==============================================================================

class FamilyTypeItem(System.ComponentModel.INotifyPropertyChanged):
    """Family type item for list"""
    def __init__(self, family_symbol, family_name, type_name):
        self.FamilySymbol = family_symbol
        self.FamilyName = family_name
        self.TypeName = type_name
        self.DisplayText = "{} - {}".format(family_name, type_name)
        self._is_selected = False
        self._property_changed_handlers = []
    
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        if self._is_selected != value:
            self._is_selected = value
            self.OnPropertyChanged("IsSelected")
    
    def add_PropertyChanged(self, handler):
        self._property_changed_handlers.append(handler)
    
    def remove_PropertyChanged(self, handler):
        if handler in self._property_changed_handlers:
            self._property_changed_handlers.remove(handler)
    
    def OnPropertyChanged(self, prop_name):
        args = System.ComponentModel.PropertyChangedEventArgs(prop_name)
        for handler in self._property_changed_handlers:
            handler(self, args)


# ==============================================================================
# WINDOW CLASS
# ==============================================================================

class HollowCorePlacerWindow:
    """Window for hollow core placer"""
    def __init__(self, xaml_path, selected_floors, family_types, doc):
        self.selected_floors = selected_floors  # Now a list of floors
        self.family_types = family_types
        self.doc = doc
        self.z_offset = 0.0
        self.selected_family = None
        self.result = False
        
        # Load XAML
        with StreamReader(xaml_path) as reader:
            self._window = XamlReader.Load(reader.BaseStream)
        
        # Get controls
        self.family_items = ObservableCollection[FamilyTypeItem]()
        self.btnClose = self._window.FindName("btnClose")
        self.txtFloorInfo = self._window.FindName("txtFloorInfo")
        self.txtFamilyCount = self._window.FindName("txtFamilyCount")
        self.lstFamilyTypes = self._window.FindName("lstFamilyTypes")
        self.txtZOffset = self._window.FindName("txtZOffset")
        self.chkRotate90 = self._window.FindName("chkRotate90")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnPlace = self._window.FindName("btnPlace")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize data"""
        # Floor info - show multiple floors
        num_floors = len(self.selected_floors)
        if num_floors == 1:
            floor_name = self.selected_floors[0].Name if hasattr(self.selected_floors[0], 'Name') else "Floor"
            floor_id = self.selected_floors[0].Id.IntegerValue
            self.txtFloorInfo.Text = "Selected: {} (ID: {})".format(floor_name, floor_id)
        else:
            floor_ids = ", ".join([str(f.Id.IntegerValue) for f in self.selected_floors])
            self.txtFloorInfo.Text = "Selected: {} floors (IDs: {})".format(num_floors, floor_ids)
        
        # Family types count
        self.txtFamilyCount.Text = "Available: {} family types".format(len(self.family_types))
        
        # Populate family types
        for symbol in sorted(self.family_types, key=lambda x: (x.Family.Name, x.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString())):
            family_name = symbol.Family.Name
            type_name = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            
            family_item = FamilyTypeItem(symbol, family_name, type_name)
            family_item.PropertyChanged += self.OnFamilySelectionChanged
            self.family_items.Add(family_item)
        
        self.lstFamilyTypes.ItemsSource = self.family_items
        
        # Set default Z offset
        self.txtZOffset.Text = str(self.z_offset)
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.btnCancel.Click += self.OnCancel
        self.btnPlace.Click += self.OnPlace
        self.txtZOffset.TextChanged += self.OnZOffsetChanged
        # Wire drag handler declared in XAML (MouseLeftButtonDown on header Border)
        header_border = self._window.FindName("headerDragArea")
        if header_border:
            header_border.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow dragging the borderless window by its title bar"""
        try:
            self._window.DragMove()
        except Exception:
            pass
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnCancel(self, sender, args):
        """Cancel and close"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnFamilySelectionChanged(self, sender, args):
        """When family selection changes"""
        # Uncheck all others (single selection)
        for item in self.family_items:
            if item != sender:
                item.IsSelected = False
        
        self.UpdateStatus()
    
    def OnZOffsetChanged(self, sender, args):
        """When Z offset value changes"""
        try:
            offset_text = self.txtZOffset.Text.strip()
            if offset_text:
                self.z_offset = float(offset_text)
        except:
            pass
    
    def UpdateStatus(self):
        """Update status label"""
        selected = [item for item in self.family_items if item.IsSelected]
        
        if selected:
            self.txtStatus.Text = "Ready to place: {}".format(selected[0].DisplayText)
            self.btnPlace.IsEnabled = True
        else:
            self.txtStatus.Text = "Select a hollow core family type"
            self.btnPlace.IsEnabled = False
    
    def OnPlace(self, sender, args):
        """Place hollow cores on all selected floors"""
        # Get selected family
        selected = [item for item in self.family_items if item.IsSelected]
        
        if not selected:
            forms.alert("Please select a hollow core family type", title="Validation Error")
            return
        
        self.selected_family = selected[0].FamilySymbol
        
        # Validate Z offset
        try:
            offset_text = self.txtZOffset.Text.strip()
            self.z_offset = float(offset_text) if offset_text else 0.0
        except:
            forms.alert("Please enter a valid Z offset in mm (or leave as 0)", title="Validation Error")
            return
        
        # Get rotation option
        rotate_90 = False
        if self.chkRotate90 and self.chkRotate90.IsChecked:
            rotate_90 = True
        
        # Confirm
        num_floors = len(self.selected_floors)
        confirm_msg = "Place hollow core slabs on {} floor{}?\n\n".format(
            num_floors, 
            "s" if num_floors > 1 else ""
        )
        confirm_msg += "Family: {}\n".format(selected[0].DisplayText)
        confirm_msg += "Hollow Core Width: 1200 mm (fixed)\n"
        confirm_msg += "Z Offset: {} mm ".format(self.z_offset)
        if self.z_offset < 0:
            confirm_msg += "(down)\n"
        elif self.z_offset > 0:
            confirm_msg += "(up)\n"
        else:
            confirm_msg += "(no offset)\n"
        if rotate_90:
            confirm_msg += "Rotation: 90° applied\n"
        confirm_msg += "\nFIXES APPLIED:\n"
        confirm_msg += "✓ Start/End Extensions set to 0 (cores end at slab edges)\n"
        confirm_msg += "✓ Z offset applied ONLY via 'z Offset Value' parameter\n"
        confirm_msg += "✓ Start/End Level Offsets forced to 0\n"
        confirm_msg += "\nNote: Gaps > 100mm will be filled with an extra core (extends beyond boundary)"
        
        if not forms.alert(confirm_msg, yes=True, no=True, title="Confirm Placement"):
            return
        
        # Update UI
        self.btnPlace.IsEnabled = False
        self.btnPlace.Content = "PLACING..."
        self.txtStatus.Text = "Placing hollow cores on {} floor{}...".format(
            num_floors,
            "s" if num_floors > 1 else ""
        )
        
        output.print_md("### 🏗️ Hollow Core Placement Started (FIXED VERSION)")
        output.print_md("**Number of Floors**: {}".format(num_floors))
        output.print_md("**Family**: {}".format(selected[0].DisplayText))
        output.print_md("**Standard Width**: 1200 mm (fixed)")
        output.print_md("**User Z Offset**: {} mm".format(self.z_offset))
        output.print_md("**Rotate 90°**: {}".format(rotate_90))
        output.print_md("**Edge Fill**: Enabled (gaps > 100mm)")
        output.print_md("")
        output.print_md("**OFFSET STRATEGY**:")
        output.print_md("  • Beams created at Level elevation (no geometric offset)")
        output.print_md("  • Floor offset + User offset applied via 'z Offset Value' parameter")
        output.print_md("  • Start Level Offset = 0 (forced)")
        output.print_md("  • End Level Offset = 0 (forced)")
        output.print_md("")
        output.print_md("**FIXES APPLIED**:")
        output.print_md("  ✓ Start/End Extensions = 0")
        output.print_md("  ✓ All vertical offset via 'z Offset Value' only")
        
        total_placed_count = 0
        
        # Place hollow cores on each floor
        with revit.Transaction("Place Hollow Core Slabs on Multiple Floors"):
            try:
                for floor_index, floor in enumerate(self.selected_floors, 1):
                    output.print_md("\n---")
                    output.print_md("### Processing Floor {} of {} (ID: {})".format(
                        floor_index, 
                        num_floors, 
                        floor.Id.IntegerValue
                    ))
                    
                    placed_count = place_hollow_core_on_floor(
                        floor, 
                        self.selected_family, 
                        1200,  # Fixed width
                        self.z_offset,
                        rotate_90
                    )
                    
                    total_placed_count += placed_count
                    output.print_md("**Placed on this floor**: {} elements".format(placed_count))
                    
            except Exception as e:
                forms.alert("Error placing hollow cores:\n\n{}".format(str(e)), title="Error")
                output.print_md("**Error**: {}".format(str(e)))
                import traceback
                output.print_md("```\n{}\n```".format(traceback.format_exc()))
                self.btnPlace.IsEnabled = True
                self.btnPlace.Content = "PLACE HOLLOW CORES"
                self.UpdateStatus()
                return
        
        # Summary
        summary_msg = "Hollow core placement complete!\n\n"
        summary_msg += "Processed: {} floor{}\n".format(num_floors, "s" if num_floors > 1 else "")
        summary_msg += "Total Elements Placed: {}\n\n".format(total_placed_count)
        summary_msg += "FIXES APPLIED:\n"
        summary_msg += "✓ Extensions set to 0 (cores end at slab edges)\n"
        summary_msg += "✓ Z offset via 'z Offset Value' parameter only\n"
        summary_msg += "✓ Start/End Level Offsets = 0\n\n"
        summary_msg += "Check output window for details."
        
        forms.alert(summary_msg, title="Complete")
        
        output.print_md("\n---")
        output.print_md("### ✅ Placement Complete")
        output.print_md("**Total Floors Processed**: {}".format(num_floors))
        output.print_md("**Total Elements Placed**: {}".format(total_placed_count))
        
        self.result = True
        self._window.Close()
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Step 1: Select Multiple Floors
output.print_md("## Select Floors")
output.print_md("Click on floor elements to place hollow core slabs...")
output.print_md("*You can select multiple floors at once*")

try:
    selection = uidoc.Selection
    references = selection.PickObjects(ObjectType.Element, FloorSelectionFilter(), "Select floors (click to select multiple, press Finish when done)")
    
    if not references:
        script.exit()
    
    selected_floors = [doc.GetElement(ref.ElementId) for ref in references]
    selected_floors = [f for f in selected_floors if f is not None]
    
    if not selected_floors:
        script.exit()
    
    output.print_md("✓ {} floor{} selected".format(
        len(selected_floors),
        "s" if len(selected_floors) > 1 else ""
    ))
    for floor in selected_floors:
        output.print_md("  - Floor ID: {}".format(floor.Id.IntegerValue))
    
except Exception as e:
    forms.alert("Selection cancelled or failed", title="Selection")
    script.exit()

# Step 2: Get available family types
family_types = get_structural_framing_families()

if not family_types:
    forms.alert(
        "No Structural Framing families found!\n\nPlease load hollow core families first.",
        title="No Families Found",
        exitscript=True
    )

output.print_md("**Available family types**: {}".format(len(family_types)))

# Step 3: Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "HollowCorePlacer.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Step 4: Show window
window = HollowCorePlacerWindow(xaml_path, selected_floors, family_types, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Hollow Cores Placed Successfully on All Floors")
else:
    output.print_md("### Operation Cancelled or Closed")