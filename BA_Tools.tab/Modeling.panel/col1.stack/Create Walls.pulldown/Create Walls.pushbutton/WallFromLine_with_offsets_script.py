# -*- coding: utf-8 -*-
"""
Wall from Line
Create walls from selected lines with specified wall type and levels
"""
__title__ = 'Wall from\nLine'
__doc__ = 'Create walls from lines'

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

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
output = script.get_output()


# ==============================================================================
# WALL CREATION FUNCTION
# ==============================================================================

def CreateWallFromLine(line_element, wall_type_id, base_level_id, top_level_id, 
                      base_offset_ft, top_offset_ft, wall_location, split_enabled, 
                      interval_ft, joint_gap_ft, doc):
    """
    Create wall from line (no splitting here - handled at higher level)
    """
    try:
        # Get the line geometry
        location_curve = line_element.GeometryCurve
        
        if not location_curve:
            return [], "No curve found"
        
        # Get levels
        base_level = doc.GetElement(base_level_id)
        top_level = doc.GetElement(top_level_id)
        
        if not base_level or not top_level:
            return [], "Invalid levels"
        
        # Calculate height (including offsets)
        base_elevation = base_level.Elevation + base_offset_ft
        top_elevation = top_level.Elevation + top_offset_ft
        wall_height = top_elevation - base_elevation
        
        if wall_height <= 0:
            return [], "Top level + offset must be higher than base level + offset"
        
        # Get wall location line value
        location_line_map = {
            "Wall Centerline": WallLocationLine.WallCenterline,
            "Finish Face: Exterior": WallLocationLine.FinishFaceExterior,
            "Finish Face: Interior": WallLocationLine.FinishFaceInterior,
            "Core Centerline": WallLocationLine.CoreCenterline,
            "Core Face: Exterior": WallLocationLine.CoreExterior,
            "Core Face: Interior": WallLocationLine.CoreInterior
        }
        
        location_line = location_line_map.get(wall_location, WallLocationLine.WallCenterline)
        flip_wall = "Interior" in wall_location
        
        # Create the wall
        wall = Wall.Create(doc, location_curve, wall_type_id, base_level_id, wall_height, base_offset_ft, flip_wall, False)
        
        if not wall:
            return [], "Wall creation failed"
        
        # Set location line
        location_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if location_param and not location_param.IsReadOnly:
            location_param.Set(int(location_line))
        
        # Set top constraint
        top_constraint_param = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if top_constraint_param and not top_constraint_param.IsReadOnly:
            top_constraint_param.Set(top_level_id)
        
        # Set top offset
        top_offset_param = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
        if top_offset_param and not top_offset_param.IsReadOnly:
            top_offset_param.Set(top_offset_ft)
        
        return [wall], "Success"
        
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

class WallFromLineWindow(Window):
    def __init__(self, xaml_path, script_dir):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.line_types = {}
        self.wall_types = {}
        self.levels = {}
        
        # Get controls
        self.imgLogo = self._window.FindName("imgLogo")
        self.btnClose = self._window.FindName("btnClose")
        self.cmbLineType = self._window.FindName("cmbLineType")
        self.cmbWallType = self._window.FindName("cmbWallType")
        self.cmbBaseLevel = self._window.FindName("cmbBaseLevel")
        self.txtBaseOffset = self._window.FindName("txtBaseOffset")
        self.cmbTopLevel = self._window.FindName("cmbTopLevel")
        self.txtTopOffset = self._window.FindName("txtTopOffset")
        self.cmbWallLocation = self._window.FindName("cmbWallLocation")
        self.chkSplitWall = self._window.FindName("chkSplitWall")
        self.txtIntervalFeet = self._window.FindName("txtIntervalFeet")
        self.txtIntervalInches = self._window.FindName("txtIntervalInches")
        self.txtJointGap = self._window.FindName("txtJointGap")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCreateWalls = self._window.FindName("btnCreateWalls")
        
        self.LoadLogo()
        self.LoadLineTypes()
        self.LoadWallTypes()
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
    
    def LoadWallTypes(self):
        try:
            wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
            for wt in sorted(wall_types, key=lambda x: x.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM).AsString()):
                wall_name = wt.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM).AsString()
                self.cmbWallType.Items.Add(wall_name)
                self.wall_types[wall_name] = wt.Id
            if self.cmbWallType.Items.Count > 0:
                self.cmbWallType.SelectedIndex = 0
        except Exception as e:
            output.print_md("Error: {}".format(str(e)))
    
    def LoadLevels(self):
        try:
            levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
            sorted_levels = sorted(levels, key=lambda x: x.Elevation)
            for level in sorted_levels:
                level_name = level.Name
                self.cmbBaseLevel.Items.Add(level_name)
                self.cmbTopLevel.Items.Add(level_name)
                self.levels[level_name] = level.Id
            if self.cmbBaseLevel.Items.Count > 0:
                self.cmbBaseLevel.SelectedIndex = 0
            if self.cmbTopLevel.Items.Count > 1:
                self.cmbTopLevel.SelectedIndex = 1
            elif self.cmbTopLevel.Items.Count > 0:
                self.cmbTopLevel.SelectedIndex = 0
        except Exception as e:
            output.print_md("Error: {}".format(str(e)))
    
    def CreateWalls(self):
        if not self.cmbLineType.SelectedItem:
            TaskDialog.Show("Error", "Please select a line type")
            return
        if not self.cmbWallType.SelectedItem:
            TaskDialog.Show("Error", "Please select a wall type")
            return
        if not self.cmbBaseLevel.SelectedItem or not self.cmbTopLevel.SelectedItem:
            TaskDialog.Show("Error", "Please select levels")
            return
        
        line_type_name = str(self.cmbLineType.SelectedItem)
        wall_type_name = str(self.cmbWallType.SelectedItem)
        base_level_name = str(self.cmbBaseLevel.SelectedItem)
        top_level_name = str(self.cmbTopLevel.SelectedItem)
        wall_location = str(self.cmbWallLocation.SelectedItem.Content)
        split_enabled = self.chkSplitWall.IsChecked == True
        
        # Get base offset
        try:
            base_offset_ft = float(self.txtBaseOffset.Text)
        except:
            TaskDialog.Show("Error", "Invalid base offset value")
            return
        
        # Get top offset
        try:
            top_offset_ft = float(self.txtTopOffset.Text)
        except:
            TaskDialog.Show("Error", "Invalid top offset value")
            return
        
        interval_ft = 0.0
        joint_gap_ft = 0.0
        
        if split_enabled:
            # Get interval feet and inches
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
            
            # Convert to total feet
            interval_ft = feet + (inches / 12.0)
            
            if interval_ft <= 0:
                TaskDialog.Show("Error", "Interval must be greater than 0")
                return
            
            # Get joint gap in inches
            try:
                gap_inches = float(self.txtJointGap.Text)
                if gap_inches < 0:
                    TaskDialog.Show("Error", "Joint gap cannot be negative")
                    return
                joint_gap_ft = gap_inches / 12.0  # Convert inches to feet
            except:
                TaskDialog.Show("Error", "Invalid joint gap value")
                return
        
        line_category_id = self.line_types[line_type_name]
        wall_type_id = self.wall_types[wall_type_name]
        base_level_id = self.levels[base_level_name]
        top_level_id = self.levels[top_level_name]
        
        self._window.Close()
        
        try:
            output.print_md("# Wall from Line")
            output.print_md("**Line Type**: {}".format(line_type_name))
            output.print_md("**Wall Type**: {}".format(wall_type_name))
            output.print_md("**Base Level**: {} (Offset: {:.2f} ft)".format(base_level_name, base_offset_ft))
            output.print_md("**Top Level**: {} (Offset: {:.2f} ft)".format(top_level_name, top_offset_ft))
            output.print_md("**Wall Location**: {}".format(wall_location))
            if split_enabled:
                # Convert back to feet and inches for display
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
            
            total_walls = 0
            failed = 0
            
            # STEP 1: Create walls for all selected lines first (NO splitting yet)
            with Transaction(doc, "Create Walls from Lines") as t:
                t.Start()
                
                created_walls_map = {}  # Map line_id -> wall list
                
                for ref in selection:
                    line_element = doc.GetElement(ref.ElementId)
                    # Create wall WITHOUT splitting
                    walls, msg = CreateWallFromLine(line_element, wall_type_id, base_level_id, top_level_id,
                                                   base_offset_ft, top_offset_ft, wall_location, 
                                                   False, interval_ft, joint_gap_ft, doc)
                    if walls and len(walls) > 0:
                        created_walls_map[line_element.Id] = walls
                        output.print_md("✅ Wall created from line {}".format(line_element.Id))
                    else:
                        failed += 1
                        output.print_md("❌ Failed for line {}: {}".format(line_element.Id, msg))
                
                doc.Regenerate()
                
                # STEP 2: If splitting is enabled, split based on TOTAL line length
                if split_enabled and len(created_walls_map) > 0:
                    output.print_md("")
                    output.print_md("### Splitting walls based on total line length...")
                    
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
                        
                        # For each split position, find which wall segment it falls on
                        cumulative_length = 0.0
                        all_new_walls = []
                        walls_to_delete = []
                        
                        for ref in selection:
                            line_elem = doc.GetElement(ref.ElementId)
                            if line_elem.Id not in created_walls_map:
                                continue
                            
                            walls = created_walls_map[line_elem.Id]
                            if not walls or len(walls) == 0:
                                continue
                            
                            wall = walls[0]
                            wall_loc = wall.Location
                            if not isinstance(wall_loc, LocationCurve):
                                all_new_walls.extend(walls)
                                continue
                            
                            wall_curve = wall_loc.Curve
                            wall_length = wall_curve.Length
                            segment_start = cumulative_length
                            segment_end = cumulative_length + wall_length
                            
                            # Find splits that fall within this wall segment
                            splits_in_this_segment = [sp for sp in split_positions 
                                                     if segment_start < sp < segment_end]
                            
                            if not splits_in_this_segment:
                                # No splits in this segment, keep original wall
                                all_new_walls.extend(walls)
                            else:
                                # Split this wall
                                gap_inches = joint_gap_ft * 12.0
                                output.print_md("    Splitting wall {} at {} positions (gap: {:.2f}\")".format(
                                    wall.Id, len(splits_in_this_segment), gap_inches))
                                
                                # Get wall parameters once
                                wall_height_param = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
                                wall_loc_line = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
                                
                                # Create sub-segments
                                sub_walls = []
                                prev_distance = 0.0
                                
                                for idx, split_pos in enumerate(splits_in_this_segment):
                                    # Distance on THIS wall where split should occur
                                    distance_on_wall = split_pos - segment_start
                                    
                                    # Create wall from prev_distance to (distance_on_wall - gap/2)
                                    if isinstance(wall_curve, Line):
                                        start_pt = wall_curve.GetEndPoint(0)
                                        end_pt = wall_curve.GetEndPoint(1)
                                        direction = (end_pt - start_pt).Normalize()
                                        
                                        # Wall segment BEFORE the gap
                                        seg_start = start_pt + (direction * prev_distance)
                                        seg_end = start_pt + (direction * (distance_on_wall - joint_gap_ft/2.0))
                                        
                                        # Only create if segment has meaningful length
                                        if seg_start.DistanceTo(seg_end) > 0.01:
                                            seg_curve = Line.CreateBound(seg_start, seg_end)
                                            
                                            seg_wall = Wall.Create(doc, seg_curve, wall_type_id, base_level_id,
                                                                 wall_height_param, base_offset_ft, "Interior" in wall_location, False)
                                            
                                            if seg_wall:
                                                # Copy parameters
                                                loc_param = seg_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                                                if loc_param and not loc_param.IsReadOnly:
                                                    loc_param.Set(wall_loc_line)
                                                top_param = seg_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                                                if top_param and not top_param.IsReadOnly:
                                                    top_param.Set(top_level_id)
                                                top_offset_param = seg_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                                                if top_offset_param and not top_offset_param.IsReadOnly:
                                                    top_offset_param.Set(top_offset_ft)
                                                
                                                # Disallow wall joins at gap ends
                                                WallUtils.DisallowWallJoinAtEnd(seg_wall, 1)  # End
                                                if idx > 0 or prev_distance > 0:
                                                    WallUtils.DisallowWallJoinAtEnd(seg_wall, 0)  # Start
                                                
                                                sub_walls.append(seg_wall)
                                    
                                    elif isinstance(wall_curve, Arc):
                                        # Handle arc curves
                                        # Convert distances to normalized parameters (0.0 to 1.0)
                                        start_param = prev_distance / wall_length
                                        end_param = (distance_on_wall - joint_gap_ft/2.0) / wall_length
                                        
                                        # Clamp parameters
                                        start_param = max(0.0, min(1.0, start_param))
                                        end_param = max(0.0, min(1.0, end_param))
                                        
                                        if end_param - start_param > 0.001:  # Meaningful arc segment
                                            # Get points on arc
                                            seg_start = wall_curve.Evaluate(start_param, True)
                                            seg_end = wall_curve.Evaluate(end_param, True)
                                            mid_param = (start_param + end_param) / 2.0
                                            seg_mid = wall_curve.Evaluate(mid_param, True)
                                            
                                            try:
                                                seg_curve = Arc.Create(seg_start, seg_end, seg_mid)
                                            except:
                                                # If arc creation fails, use line
                                                seg_curve = Line.CreateBound(seg_start, seg_end)
                                            
                                            seg_wall = Wall.Create(doc, seg_curve, wall_type_id, base_level_id,
                                                                 wall_height_param, base_offset_ft, "Interior" in wall_location, False)
                                            
                                            if seg_wall:
                                                loc_param = seg_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                                                if loc_param and not loc_param.IsReadOnly:
                                                    loc_param.Set(wall_loc_line)
                                                top_param = seg_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                                                if top_param and not top_param.IsReadOnly:
                                                    top_param.Set(top_level_id)
                                                top_offset_param = seg_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                                                if top_offset_param and not top_offset_param.IsReadOnly:
                                                    top_offset_param.Set(top_offset_ft)
                                                
                                                WallUtils.DisallowWallJoinAtEnd(seg_wall, 1)
                                                if idx > 0 or prev_distance > 0:
                                                    WallUtils.DisallowWallJoinAtEnd(seg_wall, 0)
                                                
                                                sub_walls.append(seg_wall)
                                    
                                    # Next segment starts AFTER the gap
                                    prev_distance = distance_on_wall + joint_gap_ft/2.0
                                
                                # Last segment from last split to end
                                if prev_distance < wall_length:
                                    if isinstance(wall_curve, Line):
                                        start_pt = wall_curve.GetEndPoint(0)
                                        end_pt = wall_curve.GetEndPoint(1)
                                        direction = (end_pt - start_pt).Normalize()
                                        
                                        seg_start = start_pt + (direction * prev_distance)
                                        seg_end = end_pt
                                        
                                        if seg_start.DistanceTo(seg_end) > 0.01:
                                            seg_curve = Line.CreateBound(seg_start, seg_end)
                                            
                                            seg_wall = Wall.Create(doc, seg_curve, wall_type_id, base_level_id,
                                                                 wall_height_param, base_offset_ft, "Interior" in wall_location, False)
                                            
                                            if seg_wall:
                                                loc_param = seg_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                                                if loc_param and not loc_param.IsReadOnly:
                                                    loc_param.Set(wall_loc_line)
                                                top_param = seg_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                                                if top_param and not top_param.IsReadOnly:
                                                    top_param.Set(top_level_id)
                                                top_offset_param = seg_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                                                if top_offset_param and not top_offset_param.IsReadOnly:
                                                    top_offset_param.Set(top_offset_ft)
                                                
                                                WallUtils.DisallowWallJoinAtEnd(seg_wall, 0)
                                                
                                                sub_walls.append(seg_wall)
                                    
                                    elif isinstance(wall_curve, Arc):
                                        start_param = prev_distance / wall_length
                                        end_param = 1.0
                                        
                                        start_param = max(0.0, min(1.0, start_param))
                                        
                                        if end_param - start_param > 0.001:
                                            seg_start = wall_curve.Evaluate(start_param, True)
                                            seg_end = wall_curve.Evaluate(end_param, True)
                                            mid_param = (start_param + end_param) / 2.0
                                            seg_mid = wall_curve.Evaluate(mid_param, True)
                                            
                                            try:
                                                seg_curve = Arc.Create(seg_start, seg_end, seg_mid)
                                            except:
                                                seg_curve = Line.CreateBound(seg_start, seg_end)
                                            
                                            seg_wall = Wall.Create(doc, seg_curve, wall_type_id, base_level_id,
                                                                 wall_height_param, base_offset_ft, "Interior" in wall_location, False)
                                            
                                            if seg_wall:
                                                loc_param = seg_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                                                if loc_param and not loc_param.IsReadOnly:
                                                    loc_param.Set(wall_loc_line)
                                                top_param = seg_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                                                if top_param and not top_param.IsReadOnly:
                                                    top_param.Set(top_level_id)
                                                top_offset_param = seg_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                                                if top_offset_param and not top_offset_param.IsReadOnly:
                                                    top_offset_param.Set(top_offset_ft)
                                                
                                                WallUtils.DisallowWallJoinAtEnd(seg_wall, 0)
                                                
                                                sub_walls.append(seg_wall)
                                
                                if sub_walls:
                                    all_new_walls.extend(sub_walls)
                                    walls_to_delete.append(wall)
                                else:
                                    all_new_walls.extend(walls)
                            
                            cumulative_length += wall_length
                        
                        # Delete original walls that were split
                        for wall in walls_to_delete:
                            try:
                                doc.Delete(wall.Id)
                            except:
                                pass
                        
                        total_walls = len(all_new_walls)
                        output.print_md("  Final: {} wall segments created".format(total_walls))
                    else:
                        # Not long enough to split
                        for walls_list in created_walls_map.values():
                            total_walls += len(walls_list)
                else:
                    # No splitting, just count walls
                    for walls_list in created_walls_map.values():
                        total_walls += len(walls_list)
                
                t.Commit()
            
            output.print_md("")
            output.print_md("---")
            output.print_md("### Summary")
            output.print_md("**Walls Created**: {}".format(total_walls))
            output.print_md("**Failed**: {}".format(failed))
            
            TaskDialog.Show("Complete", "Created {} walls".format(total_walls))
            
        except Exception as e:
            output.print_md("❌ Error: {}".format(str(e)))
            import traceback
            output.print_md("```\n{}\n```".format(traceback.format_exc()))
    
    def SetupEventHandlers(self):
        self.btnClose.Click += self.OnClose
        self.btnCreateWalls.Click += self.OnCreateWalls
    
    def OnClose(self, sender, args):
        self._window.Close()
    
    def OnCreateWalls(self, sender, args):
        self.CreateWalls()
    
    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, 'WallFromLine.xaml')

if not os.path.exists(xaml_path):
    forms.alert("XAML file not found!", exitscript=True)

try:
    window = WallFromLineWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)))
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
