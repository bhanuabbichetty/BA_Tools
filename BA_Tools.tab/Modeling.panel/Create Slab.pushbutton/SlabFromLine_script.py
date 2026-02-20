# -*- coding: utf-8 -*-
"""
Slab from Line
Create slabs from selected lines with specified slab type and offsets
"""
__title__ = 'Slab from\nLine'
__doc__ = 'Create slabs from lines'

import clr
import os

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
from System.Collections.Generic import List

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
output = script.get_output()


# ==============================================================================
# SLAB CREATION FUNCTION
# ==============================================================================

def CreateSlabFromLine(line_element, slab_type_id, level_id, offset_ft, left_width_ft, right_width_ft, doc):
    """
    Create slab from line with left and right offsets
    """
    try:
        # Get the line geometry
        location_curve = line_element.GeometryCurve
        
        if not location_curve:
            return [], "No curve found"
        
        # Get level
        level = doc.GetElement(level_id)
        if not level:
            return [], "Invalid level"
        
        # Create profile for slab
        # We need to create a closed curve loop offset from the line
        
        if isinstance(location_curve, Line):
            start_pt = location_curve.GetEndPoint(0)
            end_pt = location_curve.GetEndPoint(1)
            direction = (end_pt - start_pt).Normalize()
            
            # Calculate perpendicular direction
            perp = XYZ(-direction.Y, direction.X, 0).Normalize()
            
            # Create 4 corners of the slab
            p1 = start_pt + (perp * left_width_ft)   # Left start
            p2 = end_pt + (perp * left_width_ft)     # Left end
            p3 = end_pt - (perp * right_width_ft)    # Right end
            p4 = start_pt - (perp * right_width_ft)  # Right start
            
            # Create closed curve loop
            curves = List[Curve]()
            curves.Add(Line.CreateBound(p1, p2))
            curves.Add(Line.CreateBound(p2, p3))
            curves.Add(Line.CreateBound(p3, p4))
            curves.Add(Line.CreateBound(p4, p1))
            
            curve_loop = CurveLoop.Create(curves)
            
        elif isinstance(location_curve, Arc):
            # For arcs, we need to create offset arcs on both sides
            arc = location_curve
            
            # Get arc properties
            center = arc.Center
            radius = arc.Radius
            
            # Create outer and inner arcs
            # Offset arc outward (left)
            outer_radius = radius + left_width_ft
            # Offset arc inward (right)
            inner_radius = radius - right_width_ft
            
            if inner_radius <= 0:
                return [], "Right offset too large for arc radius"
            
            # Get start and end angles
            start_param = arc.GetEndParameter(0)
            end_param = arc.GetEndParameter(1)
            
            # Create outer arc (left offset)
            outer_arc = Arc.Create(center, outer_radius, start_param, end_param, arc.XDirection, arc.YDirection)
            
            # Create inner arc (right offset)
            inner_arc = Arc.Create(center, inner_radius, start_param, end_param, arc.XDirection, arc.YDirection)
            
            # Get connection lines at ends
            start_outer = outer_arc.Evaluate(0.0, True)
            start_inner = inner_arc.Evaluate(0.0, True)
            end_outer = outer_arc.Evaluate(1.0, True)
            end_inner = inner_arc.Evaluate(1.0, True)
            
            # Create closed curve loop
            curves = List[Curve]()
            curves.Add(outer_arc)
            curves.Add(Line.CreateBound(end_outer, end_inner))
            curves.Add(inner_arc.CreateReversed())
            curves.Add(Line.CreateBound(start_inner, start_outer))
            
            curve_loop = CurveLoop.Create(curves)
        
        else:
            return [], "Unsupported curve type"
        
        # Create profile
        curve_loops = List[CurveLoop]()
        curve_loops.Add(curve_loop)
        
        # Create slab
        slab = Floor.Create(doc, curve_loops, slab_type_id, level_id)
        
        if not slab:
            return [], "Slab creation failed"
        
        # Set height offset from level
        offset_param = slab.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
        if offset_param and not offset_param.IsReadOnly:
            offset_param.Set(offset_ft)
        
        return [slab], "Success"
        
    except Exception as e:
        return [], str(e)


# ==============================================================================
# LINE SELECTION FILTER
# ==============================================================================

class LineSelectionFilter(ISelectionFilter):
    """Filter to only allow line selection"""
    def __init__(self, line_category_id):
        self.line_category_id = line_category_id
    
    def AllowElement(self, element):
        """Check if element is a line"""
        try:
            if element.Category and element.Category.Id.IntegerValue == self.line_category_id.IntegerValue:
                if hasattr(element, 'GeometryCurve'):
                    curve = element.GeometryCurve
                    if curve:
                        return True
            return False
        except:
            return False
    
    def AllowReference(self, ref, point):
        return False


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class SlabFromLineWindow(Window):
    def __init__(self, xaml_path, script_dir):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.line_types = {}
        self.slab_types = {}
        self.levels = {}
        
        # Get controls
        self.imgLogo = self._window.FindName("imgLogo")
        self.btnClose = self._window.FindName("btnClose")
        self.cmbLineType = self._window.FindName("cmbLineType")
        self.cmbSlabType = self._window.FindName("cmbSlabType")
        self.cmbLevel = self._window.FindName("cmbLevel")
        self.txtOffsetFeet = self._window.FindName("txtOffsetFeet")
        self.txtOffsetInches = self._window.FindName("txtOffsetInches")
        self.txtLeftWidthFeet = self._window.FindName("txtLeftWidthFeet")
        self.txtLeftWidthInches = self._window.FindName("txtLeftWidthInches")
        self.txtRightWidthFeet = self._window.FindName("txtRightWidthFeet")
        self.txtRightWidthInches = self._window.FindName("txtRightWidthInches")
        self.chkSplitSlab = self._window.FindName("chkSplitSlab")
        self.txtIntervalFeet = self._window.FindName("txtIntervalFeet")
        self.txtIntervalInches = self._window.FindName("txtIntervalInches")
        self.txtJointGap = self._window.FindName("txtJointGap")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCreateSlabs = self._window.FindName("btnCreateSlabs")
        
        self.LoadLogo()
        self.LoadLineTypes()
        self.LoadSlabTypes()
        self.LoadLevels()
        self.SetupEventHandlers()
    
    def LoadLogo(self):
        """Load BA logo"""
        try:
            import System.Windows.Media.Imaging as Imaging
            
            logo_path = os.path.join(self.script_dir, "BA_logo.png")
            if not os.path.exists(logo_path):
                logo_path = os.path.join(self.script_dir, "icon.png")
            
            if os.path.exists(logo_path):
                bitmap = Imaging.BitmapImage()
                bitmap.BeginInit()
                bitmap.UriSource = System.Uri(logo_path)
                bitmap.CacheOption = Imaging.BitmapCacheOption.OnLoad
                bitmap.EndInit()
                self.imgLogo.Source = bitmap
        except:
            pass
    
    def LoadLineTypes(self):
        try:
            categories = doc.Settings.Categories
            line_categories = [
                (BuiltInCategory.OST_Lines, "Model Lines"),
                (BuiltInCategory.OST_SketchLines, "Sketch Lines"),
                (BuiltInCategory.OST_RoomSeparationLines, "Room Separation Lines"),
            ]
            for cat_id, cat_name in line_categories:
                try:
                    category = categories.get_Item(cat_id)
                    if category:
                        self.cmbLineType.Items.Add(cat_name)
                        self.line_types[cat_name] = category.Id
                except:
                    pass
            if self.cmbLineType.Items.Count > 0:
                self.cmbLineType.SelectedIndex = 0
        except Exception as e:
            output.print_md("Error: {}".format(str(e)))
    
    def LoadSlabTypes(self):
        try:
            floor_types = FilteredElementCollector(doc).OfClass(FloorType).ToElements()
            for ft in sorted(floor_types, key=lambda x: x.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM).AsString()):
                slab_name = ft.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM).AsString()
                self.cmbSlabType.Items.Add(slab_name)
                self.slab_types[slab_name] = ft.Id
            if self.cmbSlabType.Items.Count > 0:
                self.cmbSlabType.SelectedIndex = 0
        except Exception as e:
            output.print_md("Error: {}".format(str(e)))
    
    def LoadLevels(self):
        try:
            levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
            sorted_levels = sorted(levels, key=lambda x: x.Elevation)
            for level in sorted_levels:
                level_name = level.Name
                self.cmbLevel.Items.Add(level_name)
                self.levels[level_name] = level.Id
            if self.cmbLevel.Items.Count > 0:
                self.cmbLevel.SelectedIndex = 0
        except Exception as e:
            output.print_md("Error: {}".format(str(e)))
    
    def CreateSlabs(self):
        if not self.cmbLineType.SelectedItem:
            TaskDialog.Show("Error", "Please select a line type")
            return
        if not self.cmbSlabType.SelectedItem:
            TaskDialog.Show("Error", "Please select a slab type")
            return
        if not self.cmbLevel.SelectedItem:
            TaskDialog.Show("Error", "Please select a level")
            return
        
        line_type_name = str(self.cmbLineType.SelectedItem)
        slab_type_name = str(self.cmbSlabType.SelectedItem)
        level_name = str(self.cmbLevel.SelectedItem)
        split_enabled = self.chkSplitSlab.IsChecked == True
        
        # Get offset
        try:
            offset_feet = float(self.txtOffsetFeet.Text)
        except:
            TaskDialog.Show("Error", "Invalid offset feet value")
            return
        
        try:
            offset_inches = float(self.txtOffsetInches.Text)
            if offset_inches < 0 or offset_inches >= 12:
                TaskDialog.Show("Error", "Offset inches must be between 0 and 11.99")
                return
        except:
            TaskDialog.Show("Error", "Invalid offset inches value")
            return
        
        offset_ft = offset_feet + (offset_inches / 12.0)
        
        # Get left width
        try:
            left_feet = float(self.txtLeftWidthFeet.Text)
            if left_feet < 0:
                TaskDialog.Show("Error", "Left width cannot be negative")
                return
        except:
            TaskDialog.Show("Error", "Invalid left width feet value")
            return
        
        try:
            left_inches = float(self.txtLeftWidthInches.Text)
            if left_inches < 0 or left_inches >= 12:
                TaskDialog.Show("Error", "Left width inches must be between 0 and 11.99")
                return
        except:
            TaskDialog.Show("Error", "Invalid left width inches value")
            return
        
        left_width_ft = left_feet + (left_inches / 12.0)
        
        # Get right width
        try:
            right_feet = float(self.txtRightWidthFeet.Text)
            if right_feet < 0:
                TaskDialog.Show("Error", "Right width cannot be negative")
                return
        except:
            TaskDialog.Show("Error", "Invalid right width feet value")
            return
        
        try:
            right_inches = float(self.txtRightWidthInches.Text)
            if right_inches < 0 or right_inches >= 12:
                TaskDialog.Show("Error", "Right width inches must be between 0 and 11.99")
                return
        except:
            TaskDialog.Show("Error", "Invalid right width inches value")
            return
        
        right_width_ft = right_feet + (right_inches / 12.0)
        
        if left_width_ft + right_width_ft <= 0:
            TaskDialog.Show("Error", "Total slab width must be greater than 0")
            return
        
        # Get split parameters
        interval_ft = 0.0
        joint_gap_ft = 0.0
        
        if split_enabled:
            try:
                feet = float(self.txtIntervalFeet.Text)
                if feet < 0:
                    TaskDialog.Show("Error", "Interval feet cannot be negative")
                    return
            except:
                TaskDialog.Show("Error", "Invalid interval feet value")
                return
            
            try:
                inches = float(self.txtIntervalInches.Text)
                if inches < 0 or inches >= 12:
                    TaskDialog.Show("Error", "Interval inches must be between 0 and 11.99")
                    return
            except:
                TaskDialog.Show("Error", "Invalid interval inches value")
                return
            
            interval_ft = feet + (inches / 12.0)
            
            if interval_ft <= 0:
                TaskDialog.Show("Error", "Interval must be greater than 0")
                return
            
            try:
                gap_inches = float(self.txtJointGap.Text)
                if gap_inches < 0:
                    TaskDialog.Show("Error", "Joint gap cannot be negative")
                    return
                joint_gap_ft = gap_inches / 12.0
            except:
                TaskDialog.Show("Error", "Invalid joint gap value")
                return
        
        line_category_id = self.line_types[line_type_name]
        slab_type_id = self.slab_types[slab_type_name]
        level_id = self.levels[level_name]
        
        self._window.Close()
        
        try:
            output.print_md("# Slab from Line")
            output.print_md("**Line Type**: {}".format(line_type_name))
            output.print_md("**Slab Type**: {}".format(slab_type_name))
            output.print_md("**Level**: {}".format(level_name))
            output.print_md("**Offset**: {}' {:.1f}\"".format(int(offset_ft), (offset_ft - int(offset_ft)) * 12.0))
            output.print_md("**Left Width**: {}' {:.1f}\"".format(int(left_width_ft), (left_width_ft - int(left_width_ft)) * 12.0))
            output.print_md("**Right Width**: {}' {:.1f}\"".format(int(right_width_ft), (right_width_ft - int(right_width_ft)) * 12.0))
            if split_enabled:
                interval_feet = int(interval_ft)
                interval_inches = (interval_ft - interval_feet) * 12.0
                gap_inches = joint_gap_ft * 12.0
                output.print_md("**Split**: Yes (Every {}' {:.1f}\" with {:.2f}\" gap)".format(
                    interval_feet, interval_inches, gap_inches))
            else:
                output.print_md("**Split**: No")
            output.print_md("---")
            
            selection_filter = LineSelectionFilter(line_category_id)
            selection = uidoc.Selection.PickObjects(ObjectType.Element, selection_filter, 
                                                   "Select lines (ESC when done)")
            
            if not selection:
                output.print_md("No lines selected")
                return
            
            output.print_md("Selected {} lines".format(len(selection)))
            output.print_md("")
            
            total_slabs = 0
            failed = 0
            
            # STEP 1: Create slabs for all selected lines first (NO splitting yet)
            with Transaction(doc, "Create Slabs from Lines") as t:
                t.Start()
                
                created_slabs_map = {}
                
                for ref in selection:
                    line_element = doc.GetElement(ref.ElementId)
                    slabs, msg = CreateSlabFromLine(line_element, slab_type_id, level_id, 
                                                   offset_ft, left_width_ft, right_width_ft, doc)
                    if slabs and len(slabs) > 0:
                        created_slabs_map[line_element.Id] = slabs
                        output.print_md("✅ Slab created from line {}".format(line_element.Id))
                    else:
                        failed += 1
                        output.print_md("❌ Failed for line {}: {}".format(line_element.Id, msg))
                
                doc.Regenerate()
                
                # STEP 2: If splitting is enabled, split based on TOTAL line length
                if split_enabled and len(created_slabs_map) > 0:
                    output.print_md("")
                    output.print_md("### Splitting slabs based on total line length...")
                    
                    # Calculate total line length
                    total_line_length = 0.0
                    for ref in selection:
                        line_elem = doc.GetElement(ref.ElementId)
                        if line_elem and hasattr(line_elem, 'GeometryCurve'):
                            curve = line_elem.GeometryCurve
                            if curve:
                                total_line_length += curve.Length
                    
                    output.print_md("  Total line length: {:.2f} ft".format(total_line_length))
                    
                    if total_line_length > interval_ft:
                        # Calculate split positions based on TOTAL length
                        split_positions = []
                        current_pos = interval_ft
                        
                        while current_pos < total_line_length - 0.01:
                            split_positions.append(current_pos)
                            current_pos += interval_ft + joint_gap_ft
                        
                        output.print_md("  {} split positions calculated".format(len(split_positions)))
                        
                        # For each split position, find which slab segment it falls on
                        cumulative_length = 0.0
                        all_new_slabs = []
                        slabs_to_delete = []
                        
                        for ref in selection:
                            line_elem = doc.GetElement(ref.ElementId)
                            if line_elem.Id not in created_slabs_map:
                                continue
                            
                            slabs = created_slabs_map[line_elem.Id]
                            if not slabs or len(slabs) == 0:
                                continue
                            
                            slab = slabs[0]
                            line_curve = line_elem.GeometryCurve
                            line_length = line_curve.Length
                            segment_start = cumulative_length
                            segment_end = cumulative_length + line_length
                            
                            # Find splits that fall within this line segment
                            splits_in_this_segment = [sp for sp in split_positions 
                                                     if segment_start < sp < segment_end]
                            
                            if not splits_in_this_segment:
                                # No splits in this segment, keep original slab
                                all_new_slabs.extend(slabs)
                            else:
                                # Split this slab
                                gap_inches = joint_gap_ft * 12.0
                                output.print_md("    Splitting slab {} at {} positions (gap: {:.2f}\")".format(
                                    slab.Id, len(splits_in_this_segment), gap_inches))
                                
                                # Create sub-segments
                                sub_slabs = []
                                prev_distance = 0.0
                                
                                for idx, split_pos in enumerate(splits_in_this_segment):
                                    # Distance on THIS line where split should occur
                                    distance_on_line = split_pos - segment_start
                                    
                                    # Create slab from prev_distance to (distance_on_line - gap/2)
                                    try:
                                        seg_start_dist = prev_distance
                                        seg_end_dist = distance_on_line - joint_gap_ft/2.0
                                        
                                        if seg_end_dist - seg_start_dist > 0.01:
                                            # Create offset curves for this segment
                                            if isinstance(line_curve, Line):
                                                start_pt = line_curve.GetEndPoint(0)
                                                end_pt = line_curve.GetEndPoint(1)
                                                direction = (end_pt - start_pt).Normalize()
                                                perp = XYZ(-direction.Y, direction.X, 0).Normalize()
                                                
                                                # Segment points on centerline
                                                seg_start_pt = start_pt + (direction * seg_start_dist)
                                                seg_end_pt = start_pt + (direction * seg_end_dist)
                                                
                                                # Create left boundary
                                                left_start = seg_start_pt + (perp * left_width_ft)
                                                left_end = seg_end_pt + (perp * left_width_ft)
                                                
                                                # Create right boundary
                                                right_start = seg_start_pt - (perp * right_width_ft)
                                                right_end = seg_end_pt - (perp * right_width_ft)
                                                
                                                # Create closed loop
                                                curves = List[Curve]()
                                                curves.Add(Line.CreateBound(left_start, left_end))
                                                curves.Add(Line.CreateBound(left_end, right_end))
                                                curves.Add(Line.CreateBound(right_end, right_start))
                                                curves.Add(Line.CreateBound(right_start, left_start))
                                                
                                                curve_loop = CurveLoop.Create(curves)
                                                curve_loops = List[CurveLoop]()
                                                curve_loops.Add(curve_loop)
                                                
                                                seg_slab = Floor.Create(doc, curve_loops, slab_type_id, level_id)
                                                
                                                if seg_slab:
                                                    offset_param = seg_slab.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                                                    if offset_param and not offset_param.IsReadOnly:
                                                        offset_param.Set(offset_ft)
                                                    sub_slabs.append(seg_slab)
                                            
                                            elif isinstance(line_curve, Arc):
                                                arc = line_curve
                                                center = arc.Center
                                                radius = arc.Radius
                                                
                                                # Calculate arc parameters
                                                start_param = seg_start_dist / line_length
                                                end_param = seg_end_dist / line_length
                                                
                                                start_param = max(0.0, min(1.0, start_param))
                                                end_param = max(0.0, min(1.0, end_param))
                                                
                                                if end_param - start_param > 0.001:
                                                    full_start = arc.GetEndParameter(0)
                                                    full_end = arc.GetEndParameter(1)
                                                    param_range = full_end - full_start
                                                    
                                                    seg_start_angle = full_start + (start_param * param_range)
                                                    seg_end_angle = full_start + (end_param * param_range)
                                                    
                                                    # Create outer and inner arcs
                                                    outer_radius = radius + left_width_ft
                                                    inner_radius = radius - right_width_ft
                                                    
                                                    if inner_radius > 0:
                                                        outer_arc = Arc.Create(center, outer_radius, seg_start_angle, seg_end_angle,
                                                                             arc.XDirection, arc.YDirection)
                                                        inner_arc = Arc.Create(center, inner_radius, seg_start_angle, seg_end_angle,
                                                                             arc.XDirection, arc.YDirection)
                                                        
                                                        # Get connection points
                                                        start_outer = outer_arc.Evaluate(0.0, True)
                                                        start_inner = inner_arc.Evaluate(0.0, True)
                                                        end_outer = outer_arc.Evaluate(1.0, True)
                                                        end_inner = inner_arc.Evaluate(1.0, True)
                                                        
                                                        # Create closed loop
                                                        curves = List[Curve]()
                                                        curves.Add(outer_arc)
                                                        curves.Add(Line.CreateBound(end_outer, end_inner))
                                                        curves.Add(inner_arc.CreateReversed())
                                                        curves.Add(Line.CreateBound(start_inner, start_outer))
                                                        
                                                        curve_loop = CurveLoop.Create(curves)
                                                        curve_loops = List[CurveLoop]()
                                                        curve_loops.Add(curve_loop)
                                                        
                                                        seg_slab = Floor.Create(doc, curve_loops, slab_type_id, level_id)
                                                        
                                                        if seg_slab:
                                                            offset_param = seg_slab.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                                                            if offset_param and not offset_param.IsReadOnly:
                                                                offset_param.Set(offset_ft)
                                                            sub_slabs.append(seg_slab)
                                    
                                    except Exception as seg_err:
                                        output.print_md("      Segment {} error: {}".format(idx, str(seg_err)))
                                    
                                    # Next segment starts AFTER the gap
                                    prev_distance = distance_on_line + joint_gap_ft/2.0
                                
                                # Last segment from last split to end
                                if prev_distance < line_length:
                                    try:
                                        seg_start_dist = prev_distance
                                        seg_end_dist = line_length
                                        
                                        if seg_end_dist - seg_start_dist > 0.01:
                                            if isinstance(line_curve, Line):
                                                start_pt = line_curve.GetEndPoint(0)
                                                end_pt = line_curve.GetEndPoint(1)
                                                direction = (end_pt - start_pt).Normalize()
                                                perp = XYZ(-direction.Y, direction.X, 0).Normalize()
                                                
                                                seg_start_pt = start_pt + (direction * seg_start_dist)
                                                seg_end_pt = end_pt
                                                
                                                left_start = seg_start_pt + (perp * left_width_ft)
                                                left_end = seg_end_pt + (perp * left_width_ft)
                                                right_start = seg_start_pt - (perp * right_width_ft)
                                                right_end = seg_end_pt - (perp * right_width_ft)
                                                
                                                curves = List[Curve]()
                                                curves.Add(Line.CreateBound(left_start, left_end))
                                                curves.Add(Line.CreateBound(left_end, right_end))
                                                curves.Add(Line.CreateBound(right_end, right_start))
                                                curves.Add(Line.CreateBound(right_start, left_start))
                                                
                                                curve_loop = CurveLoop.Create(curves)
                                                curve_loops = List[CurveLoop]()
                                                curve_loops.Add(curve_loop)
                                                
                                                seg_slab = Floor.Create(doc, curve_loops, slab_type_id, level_id)
                                                
                                                if seg_slab:
                                                    offset_param = seg_slab.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                                                    if offset_param and not offset_param.IsReadOnly:
                                                        offset_param.Set(offset_ft)
                                                    sub_slabs.append(seg_slab)
                                            
                                            elif isinstance(line_curve, Arc):
                                                arc = line_curve
                                                center = arc.Center
                                                radius = arc.Radius
                                                
                                                start_param = seg_start_dist / line_length
                                                end_param = 1.0
                                                
                                                start_param = max(0.0, min(1.0, start_param))
                                                
                                                if end_param - start_param > 0.001:
                                                    full_start = arc.GetEndParameter(0)
                                                    full_end = arc.GetEndParameter(1)
                                                    param_range = full_end - full_start
                                                    
                                                    seg_start_angle = full_start + (start_param * param_range)
                                                    seg_end_angle = full_end
                                                    
                                                    outer_radius = radius + left_width_ft
                                                    inner_radius = radius - right_width_ft
                                                    
                                                    if inner_radius > 0:
                                                        outer_arc = Arc.Create(center, outer_radius, seg_start_angle, seg_end_angle,
                                                                             arc.XDirection, arc.YDirection)
                                                        inner_arc = Arc.Create(center, inner_radius, seg_start_angle, seg_end_angle,
                                                                             arc.XDirection, arc.YDirection)
                                                        
                                                        start_outer = outer_arc.Evaluate(0.0, True)
                                                        start_inner = inner_arc.Evaluate(0.0, True)
                                                        end_outer = outer_arc.Evaluate(1.0, True)
                                                        end_inner = inner_arc.Evaluate(1.0, True)
                                                        
                                                        curves = List[Curve]()
                                                        curves.Add(outer_arc)
                                                        curves.Add(Line.CreateBound(end_outer, end_inner))
                                                        curves.Add(inner_arc.CreateReversed())
                                                        curves.Add(Line.CreateBound(start_inner, start_outer))
                                                        
                                                        curve_loop = CurveLoop.Create(curves)
                                                        curve_loops = List[CurveLoop]()
                                                        curve_loops.Add(curve_loop)
                                                        
                                                        seg_slab = Floor.Create(doc, curve_loops, slab_type_id, level_id)
                                                        
                                                        if seg_slab:
                                                            offset_param = seg_slab.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                                                            if offset_param and not offset_param.IsReadOnly:
                                                                offset_param.Set(offset_ft)
                                                            sub_slabs.append(seg_slab)
                                    
                                    except Exception as last_err:
                                        output.print_md("      Last segment error: {}".format(str(last_err)))
                                
                                if sub_slabs:
                                    all_new_slabs.extend(sub_slabs)
                                    slabs_to_delete.append(slab)
                                else:
                                    all_new_slabs.extend(slabs)
                            
                            cumulative_length += line_length
                        
                        # Delete original slabs that were split
                        for slab in slabs_to_delete:
                            try:
                                doc.Delete(slab.Id)
                            except:
                                pass
                        
                        total_slabs = len(all_new_slabs)
                        output.print_md("  Final: {} slab segments created".format(total_slabs))
                    else:
                        # Not long enough to split
                        for slabs_list in created_slabs_map.values():
                            total_slabs += len(slabs_list)
                else:
                    # No splitting, just count slabs
                    for slabs_list in created_slabs_map.values():
                        total_slabs += len(slabs_list)
                
                t.Commit()
            
            output.print_md("")
            output.print_md("---")
            output.print_md("### Summary")
            output.print_md("**Slabs Created**: {}".format(total_slabs))
            output.print_md("**Failed**: {}".format(failed))
            
            TaskDialog.Show("Complete", "Created {} slabs".format(total_slabs))
            
        except Exception as e:
            output.print_md("❌ Error: {}".format(str(e)))
            import traceback
            output.print_md("```\n{}\n```".format(traceback.format_exc()))
    
    def SetupEventHandlers(self):
        self.btnClose.Click += self.OnClose
        self.btnCreateSlabs.Click += self.OnCreateSlabs
    
    def OnClose(self, sender, args):
        self._window.Close()
    
    def OnCreateSlabs(self, sender, args):
        self.CreateSlabs()
    
    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, 'SlabFromLine.xaml')

if not os.path.exists(xaml_path):
    forms.alert("XAML file not found!", exitscript=True)

try:
    window = SlabFromLineWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)))
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
