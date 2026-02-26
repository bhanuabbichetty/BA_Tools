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
                      wall_location, split_enabled, interval_mm, joint_gap_mm, 
                      base_offset_mm, top_offset_mm, doc):
    """
    Create wall from line and optionally split it with gaps
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
        
        # Convert offsets from mm to feet
        base_offset_ft = base_offset_mm / 304.8
        top_offset_ft = top_offset_mm / 304.8
        
        # Calculate height
        base_elevation = base_level.Elevation
        top_elevation = top_level.Elevation
        wall_height = (top_elevation + top_offset_ft) - (base_elevation + base_offset_ft)
        
        if wall_height <= 0:
            return [], "Wall height must be positive (check offsets)"
        
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
        
        # If NO splitting, create single wall
        if not split_enabled or interval_mm <= 0:
            # Create wall with flip parameter based on location line
            flip_wall = False
            if "Interior" in wall_location:
                flip_wall = True
            
            wall = Wall.Create(doc, location_curve, wall_type_id, base_level_id, wall_height, 0, flip_wall, False)
            
            if wall:
                # Set location line AFTER creation
                location_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                if location_param and not location_param.IsReadOnly:
                    location_param.Set(int(location_line))
                
                # Set base offset
                base_offset_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
                if base_offset_param and not base_offset_param.IsReadOnly:
                    base_offset_param.Set(base_offset_ft)
                
                # Set top constraint
                top_constraint_param = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                if top_constraint_param and not top_constraint_param.IsReadOnly:
                    top_constraint_param.Set(top_level_id)
                
                # Set top offset
                top_offset_param = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                if top_offset_param and not top_offset_param.IsReadOnly:
                    top_offset_param.Set(top_offset_ft)
                
                # CRITICAL: Disallow joins at BOTH ends since this is a standalone line
                try:
                    WallUtils.DisallowWallJoinAtEnd(wall, 0)  # Start
                    WallUtils.DisallowWallJoinAtEnd(wall, 1)  # End
                except:
                    pass
                
                return [wall], "Success"
            else:
                return [], "Wall creation failed"
        
        # SPLITTING LOGIC
        # Convert to feet
        interval_ft = interval_mm / 304.8
        gap_ft = joint_gap_mm / 304.8
        
        # Get curve properties
        total_length = location_curve.Length
        
        # If curve is shorter than interval, create single wall
        if total_length <= interval_ft:
            flip_wall = "Interior" in wall_location
            wall = Wall.Create(doc, location_curve, wall_type_id, base_level_id, wall_height, 0, flip_wall, False)
            if wall:
                location_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                if location_param and not location_param.IsReadOnly:
                    location_param.Set(int(location_line))
                
                # Set base offset
                base_offset_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
                if base_offset_param and not base_offset_param.IsReadOnly:
                    base_offset_param.Set(base_offset_ft)
                
                top_constraint_param = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                if top_constraint_param and not top_constraint_param.IsReadOnly:
                    top_constraint_param.Set(top_level_id)
                
                # Set top offset
                top_offset_param = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                if top_offset_param and not top_offset_param.IsReadOnly:
                    top_offset_param.Set(top_offset_ft)
                
                # Disallow joins at both ends
                try:
                    WallUtils.DisallowWallJoinAtEnd(wall, 0)
                    WallUtils.DisallowWallJoinAtEnd(wall, 1)
                except:
                    pass
                
                return [wall], "Success (no split needed)"
            return [], "Wall creation failed"
        
        # Calculate segments
        num_full_segments = int(total_length / interval_ft)
        remaining_length = total_length - (num_full_segments * interval_ft)
        
        if remaining_length < 0.1:
            num_segments = num_full_segments
        else:
            num_segments = num_full_segments + 1
        
        # Create walls for each segment
        created_walls = []
        current_position = 0.0  # Current parameter position along curve (in feet)
        
        # Determine if we need to flip walls
        flip_wall = "Interior" in wall_location
        
        for i in range(num_segments):
            try:
                # Calculate normalized parameters (0.0 to 1.0) along the curve
                
                if isinstance(location_curve, Line):
                    # For lines, use actual distance
                    start_point = location_curve.GetEndPoint(0)
                    end_point = location_curve.GetEndPoint(1)
                    direction = (end_point - start_point).Normalize()
                    
                    # Calculate segment bounds
                    segment_start = start_point + (direction * current_position)
                    
                    if i == num_segments - 1:
                        segment_end = end_point
                    else:
                        segment_end = segment_start + (direction * interval_ft)
                    
                    # Create line for segment
                    segment_curve = Line.CreateBound(segment_start, segment_end)
                    
                else:
                    # For curves (Arc, NurbSpline, etc.), use normalized parameters
                    # Calculate start parameter (0.0 to 1.0)
                    start_param = current_position / total_length
                    
                    if i == num_segments - 1:
                        # Last segment goes to end
                        end_param = 1.0
                    else:
                        # Regular segment
                        end_param = (current_position + interval_ft) / total_length
                    
                    # Make sure parameters are within bounds
                    start_param = max(0.0, min(1.0, start_param))
                    end_param = max(0.0, min(1.0, end_param))
                    
                    # Get points on curve using Evaluate
                    segment_start = location_curve.Evaluate(start_param, True)
                    segment_end = location_curve.Evaluate(end_param, True)
                    
                    # For arcs, create arc segment
                    if isinstance(location_curve, Arc):
                        # Get middle point for arc creation
                        mid_param = (start_param + end_param) / 2.0
                        mid_point = location_curve.Evaluate(mid_param, True)
                        
                        try:
                            segment_curve = Arc.Create(segment_start, segment_end, mid_point)
                        except:
                            # If arc creation fails, use line
                            segment_curve = Line.CreateBound(segment_start, segment_end)
                    else:
                        # For other curves, use line segments
                        segment_curve = Line.CreateBound(segment_start, segment_end)
                
                # Create wall for this segment
                segment_wall = Wall.Create(doc, segment_curve, wall_type_id, base_level_id, 
                                          wall_height, 0, flip_wall, False)
                
                if segment_wall:
                    # Set location line
                    location_param = segment_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                    if location_param and not location_param.IsReadOnly:
                        location_param.Set(int(location_line))
                    
                    # Set base offset
                    base_offset_param = segment_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
                    if base_offset_param and not base_offset_param.IsReadOnly:
                        base_offset_param.Set(base_offset_ft)
                    
                    # Set top constraint
                    top_constraint_param = segment_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                    if top_constraint_param and not top_constraint_param.IsReadOnly:
                        top_constraint_param.Set(top_level_id)
                    
                    # Set top offset
                    top_offset_param = segment_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
                    if top_offset_param and not top_offset_param.IsReadOnly:
                        top_offset_param.Set(top_offset_ft)
                    
                    # CRITICAL: Disallow wall joins properly
                    # - FIRST segment (i=0): Disallow at START (line beginning), Disallow at END (gap)
                    # - MIDDLE segments: Disallow at BOTH ends (gaps on both sides)
                    # - LAST segment (i=num_segments-1): Disallow at START (gap), Disallow at END (line ending)
                    try:
                        if i == 0:
                            # First segment - disallow at START (line beginning) and END (gap)
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 0)  # Start
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 1)  # End
                        elif i == num_segments - 1:
                            # Last segment - disallow at START (gap) and END (line ending)
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 0)  # Start
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 1)  # End
                        else:
                            # Middle segments - disallow at both ends (gaps)
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 0)  # Start
                            WallUtils.DisallowWallJoinAtEnd(segment_wall, 1)  # End
                    except Exception as join_err:
                        output.print_md("      - Join disallow warning: {}".format(str(join_err)))
                    
                    created_walls.append(segment_wall)
                
                # Move to next position (add interval + gap)
                current_position += interval_ft + gap_ft
                
            except Exception as seg_err:
                output.print_md("      - Segment {} error: {}".format(i+1, str(seg_err)))
                continue
        
        if created_walls:
            return created_walls, "Success"
        else:
            return [], "No walls created"
        
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
        self.cmbTopLevel = self._window.FindName("cmbTopLevel")
        self.cmbWallLocation = self._window.FindName("cmbWallLocation")
        self.txtBaseOffset = self._window.FindName("txtBaseOffset")
        self.txtTopOffset = self._window.FindName("txtTopOffset")
        self.chkSplitWall = self._window.FindName("chkSplitWall")
        self.txtInterval = self._window.FindName("txtInterval")
        self.txtJointGap = self._window.FindName("txtJointGap")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCreateWalls = self._window.FindName("btnCreateWalls")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        self.LoadLogo()
        self.LoadLineTypes()
        self.LoadWallTypes()
        self.LoadLevels()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def LoadLogo(self):
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
            base_offset_mm = float(self.txtBaseOffset.Text)
        except:
            TaskDialog.Show("Error", "Invalid base offset value")
            return
        
        # Get top offset
        try:
            top_offset_mm = float(self.txtTopOffset.Text)
        except:
            TaskDialog.Show("Error", "Invalid top offset value")
            return
        
        interval_mm = 0
        joint_gap_mm = 16.0
        
        if split_enabled:
            try:
                interval_mm = float(self.txtInterval.Text)
                if interval_mm <= 0:
                    TaskDialog.Show("Error", "Interval must be > 0")
                    return
            except:
                TaskDialog.Show("Error", "Invalid interval")
                return
            try:
                joint_gap_mm = float(self.txtJointGap.Text)
                if joint_gap_mm < 0:
                    TaskDialog.Show("Error", "Gap cannot be negative")
                    return
            except:
                TaskDialog.Show("Error", "Invalid gap")
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
            output.print_md("**Base Level**: {}".format(base_level_name))
            output.print_md("**Top Level**: {}".format(top_level_name))
            output.print_md("**Wall Location**: {}".format(wall_location))
            output.print_md("**Base Offset**: {} mm".format(base_offset_mm))
            output.print_md("**Top Offset**: {} mm".format(top_offset_mm))
            if split_enabled:
                output.print_md("**Split**: Yes (Every {} mm with {} mm gap)".format(interval_mm, joint_gap_mm))
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
            
            with Transaction(doc, "Create Walls from Lines") as t:
                t.Start()
                for ref in selection:
                    line_element = doc.GetElement(ref.ElementId)
                    walls, msg = CreateWallFromLine(line_element, wall_type_id, base_level_id, top_level_id,
                                                   wall_location, split_enabled, interval_mm, joint_gap_mm,
                                                   base_offset_mm, top_offset_mm, doc)
                    if walls and len(walls) > 0:
                        total_walls += len(walls)
                        if len(walls) > 1:
                            output.print_md("✅ Created {} walls from line {} (split)".format(len(walls), line_element.Id))
                        else:
                            output.print_md("✅ Wall created from line {}".format(line_element.Id))
                    else:
                        failed += 1
                        output.print_md("❌ Failed for line {}: {}".format(line_element.Id, msg))
                t.Commit()
            
            output.print_md("")
            output.print_md("---")
            output.print_md("### Summary")
            output.print_md("**Walls Created**: {}".format(total_walls))
            output.print_md("**Failed**: {}".format(failed))
            
            TaskDialog.Show("Complete", "Created {} walls".format(total_walls))
            
        except Exception as e:
            output.print_md("❌ Error: {}".format(str(e)))
    
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