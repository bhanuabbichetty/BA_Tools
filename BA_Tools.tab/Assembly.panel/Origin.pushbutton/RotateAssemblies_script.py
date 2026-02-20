# -*- coding: utf-8 -*-
"""
Assembly Rotation Tool
Rotate assemblies based on erection mark orientation
"""
__title__ = 'Rotate\nAssemblies'
__doc__ = 'Rotate assemblies from erection marks'

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
from pyrevit import script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()


# ==============================================================================
# DATA CLASS
# ==============================================================================

class AssemblyData:
    """Represents an assembly with rotation info"""
    def __init__(self, assembly):
        self.Assembly = assembly
        self.AssemblyId = str(assembly.Id.IntegerValue)
        self._isSelected = False
        
        # Get assembly name
        self.AssemblyName = assembly.AssemblyTypeName if hasattr(assembly, 'AssemblyTypeName') else "Unknown"
        
        # Get member count
        self.ElementCount = 0
        self.ErectionMarkStatus = "Not Found"
        self.ErectionMarkElement = None
        self.CurrentAngle = "0°"
        
        try:
            # Get member ids
            member_ids = assembly.GetMemberIds()
            self.ElementCount = member_ids.Count
            
            # Find erection mark
            for member_id in member_ids:
                elem = doc.GetElement(member_id)
                if elem and elem.Category:
                    # Check if it's a face-based family (Generic Models or Specialty Equipment)
                    if elem.Category.Id.IntegerValue in [int(BuiltInCategory.OST_GenericModel), 
                                                          int(BuiltInCategory.OST_SpecialityEquipment)]:
                        # Check if it has "erection" or "mark" in name/family name
                        family_name = ""
                        type_name = ""
                        
                        elem_type = doc.GetElement(elem.GetTypeId())
                        if elem_type:
                            type_name = elem_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if elem_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM) else ""
                            family_param = elem_type.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
                            if family_param:
                                family_name = family_param.AsString()
                        
                        # Check if name contains "erection" or "mark"
                        combined = (family_name + " " + type_name).lower()
                        if "erection" in combined or "mark" in combined:
                            self.ErectionMarkElement = elem
                            self.ErectionMarkStatus = "✓ Found"
                            break
            
            # Calculate current angle if erection mark found
            if self.ErectionMarkElement:
                self.CurrentAngle = self.GetErectionMarkAngle()
                
        except:
            pass
    
    def GetErectionMarkAngle(self):
        """Get the rotation angle needed to align assembly with erection mark"""
        try:
            mark = self.ErectionMarkElement
            assembly = self.Assembly
            
            # Get erection mark's transform
            mark_trans = mark.GetTransform()
            mark_x = mark_trans.BasisX
            
            # Get assembly's current transform
            assembly_trans = assembly.GetTransform()
            assembly_x = assembly_trans.BasisX
            
            # Project to XY plane
            mark_x_2d = XYZ(mark_x.X, mark_x.Y, 0).Normalize()
            assembly_x_2d = XYZ(assembly_x.X, assembly_x.Y, 0).Normalize()
            
            # Calculate angles
            mark_angle = math.atan2(mark_x_2d.Y, mark_x_2d.X)
            assembly_angle = math.atan2(assembly_x_2d.Y, assembly_x_2d.X)
            
            # Difference is the rotation needed
            angle_rad = mark_angle - assembly_angle
            angle_deg = math.degrees(angle_rad)
            
            # Normalize to -180 to 180
            while angle_deg > 180:
                angle_deg -= 360
            while angle_deg < -180:
                angle_deg += 360
            
            return "{:.1f}°".format(angle_deg)
        except:
            return "Unknown"
    
    @property
    def IsSelected(self):
        return self._isSelected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class RotateAssembliesWindow(Window):
    def __init__(self, xaml_path, script_dir):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.all_assemblies = []
        
        # Get controls
        self.imgLogo = self._window.FindName("imgLogo")
        self.btnClose = self._window.FindName("btnClose")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Rotation settings
        self.rbZ = self._window.FindName("rbZ")
        self.rbX = self._window.FindName("rbX")
        self.rbY = self._window.FindName("rbY")
        self.rbAuto = self._window.FindName("rbAuto")
        self.rbManual = self._window.FindName("rbManual")
        self.txtAngle = self._window.FindName("txtAngle")
        
        # Assembly table
        self.txtAssemblyCount = self._window.FindName("txtAssemblyCount")
        self.txtSelectedCount = self._window.FindName("txtSelectedCount")
        self.btnRefresh = self._window.FindName("btnRefresh")
        self.txtSearch = self._window.FindName("txtSearch")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnDeselectAll = self._window.FindName("btnDeselectAll")
        self.dgAssemblies = self._window.FindName("dgAssemblies")
        
        # Footer
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnRotate = self._window.FindName("btnRotate")
        
        # Setup
        self.LoadLogo()
        self.LoadAssemblies()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
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
    
    def LoadAssemblies(self):
        """Load all assemblies in the project"""
        self.txtStatus.Text = "Loading assemblies..."
        
        # Get all assembly instances
        collector = FilteredElementCollector(doc)\
            .OfClass(AssemblyInstance)\
            .WhereElementIsNotElementType()
        
        assembly_list = []
        for assembly in collector:
            try:
                assembly_data = AssemblyData(assembly)
                assembly_list.append(assembly_data)
            except:
                continue
        
        self.all_assemblies = assembly_list
        self.RefreshGrid()
        
        self.txtAssemblyCount.Text = "Found {} assemblies in project".format(len(assembly_list))
        self.UpdateSelectedCount()
        self.txtStatus.Text = "Ready - Select assemblies to rotate"
    
    def RefreshGrid(self):
        """Refresh the assemblies DataGrid"""
        search_text = self.txtSearch.Text.lower() if self.txtSearch.Text else ""
        
        if search_text:
            filtered = [a for a in self.all_assemblies 
                       if search_text in a.AssemblyName.lower() 
                       or search_text in a.AssemblyId.lower()]
        else:
            filtered = self.all_assemblies
        
        collection = ObservableCollection[object]()
        for assembly in filtered:
            collection.Add(assembly)
        
        self.dgAssemblies.ItemsSource = collection
    
    def UpdateSelectedCount(self):
        """Update selected count text"""
        if self.dgAssemblies.ItemsSource:
            selected = sum(1 for a in self.dgAssemblies.ItemsSource if a.IsSelected)
            self.txtSelectedCount.Text = "{} selected".format(selected)
    
    def GetRotationAxis(self):
        """Get selected rotation axis"""
        if self.rbZ.IsChecked:
            return XYZ(0, 0, 1)  # Z-axis (vertical)
        elif self.rbX.IsChecked:
            return XYZ(1, 0, 0)  # X-axis
        elif self.rbY.IsChecked:
            return XYZ(0, 1, 0)  # Y-axis
        else:
            return XYZ(0, 0, 1)  # Default to Z
    
    def CalculateRotationAngle(self, assembly_data):
        """Calculate rotation angle to align assembly with erection mark"""
        if self.rbAuto.IsChecked:
            # Auto mode - align assembly with erection mark orientation
            if assembly_data.ErectionMarkElement:
                try:
                    mark = assembly_data.ErectionMarkElement
                    assembly = assembly_data.Assembly
                    
                    # Get erection mark's transform (target orientation)
                    mark_trans = mark.GetTransform()
                    mark_x = mark_trans.BasisX
                    mark_y = mark_trans.BasisY
                    
                    # Get assembly's current transform
                    assembly_trans = assembly.GetTransform()
                    assembly_x = assembly_trans.BasisX
                    assembly_y = assembly_trans.BasisY
                    
                    # Calculate angle between assembly X and mark X (in XY plane)
                    # This gives us the rotation needed to align them
                    
                    # Project vectors to XY plane (ignore Z component)
                    mark_x_2d = XYZ(mark_x.X, mark_x.Y, 0).Normalize()
                    assembly_x_2d = XYZ(assembly_x.X, assembly_x.Y, 0).Normalize()
                    
                    # Calculate angle using atan2 for proper quadrant
                    mark_angle = math.atan2(mark_x_2d.Y, mark_x_2d.X)
                    assembly_angle = math.atan2(assembly_x_2d.Y, assembly_x_2d.X)
                    
                    # Difference is the rotation needed
                    angle_rad = mark_angle - assembly_angle
                    
                    # Convert to degrees
                    angle_deg = math.degrees(angle_rad)
                    
                    # Normalize to -180 to 180 range
                    while angle_deg > 180:
                        angle_deg -= 360
                    while angle_deg < -180:
                        angle_deg += 360
                    
                    return angle_deg
                    
                except Exception as e:
                    output.print_md("Error calculating angle: {}".format(str(e)))
                    return 0.0
            else:
                return 0.0
        else:
            # Manual mode - use specified angle
            try:
                return float(self.txtAngle.Text)
            except:
                return 0.0
    
    def RotateAssemblies(self):
        """Rotate selected assemblies"""
        # Get selected assemblies
        selected = [a for a in self.dgAssemblies.ItemsSource if a.IsSelected]
        
        if not selected:
            TaskDialog.Show("Error", "Please select assemblies to rotate")
            return
        
        # Check if using auto mode
        if self.rbAuto.IsChecked:
            # Check how many have erection marks
            with_marks = [a for a in selected if a.ErectionMarkElement is not None]
            if len(with_marks) == 0:
                TaskDialog.Show("Error", "None of the selected assemblies have erection marks.\n\nSwitch to Manual mode or select assemblies with erection marks.")
                return
            
            if len(with_marks) < len(selected):
                result = TaskDialog.Show("Warning", 
                    "{} of {} selected assemblies have erection marks.\n\nContinue with rotation?".format(
                        len(with_marks), len(selected)),
                    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
                if result != TaskDialogResult.Yes:
                    return
        
        # Get rotation axis
        axis = self.GetRotationAxis()
        axis_name = "Z-Axis" if self.rbZ.IsChecked else ("X-Axis" if self.rbX.IsChecked else "Y-Axis")
        
        # Confirm
        mode = "Auto (from erection marks)" if self.rbAuto.IsChecked else "Manual ({} degrees)".format(self.txtAngle.Text)
        message = "Rotate {} assemblies?\n\n".format(len(selected))
        message += "Rotation Mode: {}\n".format(mode)
        message += "Rotation Axis: {}\n\n".format(axis_name)
        message += "Continue?"
        
        result = TaskDialog.Show("Confirm", message, 
                                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result != TaskDialogResult.Yes:
            return
        
        self._window.Close()
        
        # Rotate assemblies
        output.print_md("# Assembly Rotation")
        output.print_md("**Selected**: {} assemblies".format(len(selected)))
        output.print_md("**Mode**: {}".format(mode))
        output.print_md("**Axis**: {}".format(axis_name))
        output.print_md("---")
        
        rotated = 0
        skipped = 0
        failed = 0
        
        # Process each assembly in its own transaction
        for i, assembly_data in enumerate(selected):
            t = Transaction(doc, "Rotate Assembly {}".format(i + 1))
            t.Start()
            
            try:
                assembly = assembly_data.Assembly
                
                # Calculate rotation angle
                angle_deg = self.CalculateRotationAngle(assembly_data)
                
                if angle_deg == 0:
                    output.print_md("- ⚠ **Skipped**: {} (angle = 0°)".format(assembly_data.AssemblyName))
                    skipped += 1
                    t.RollBack()
                    continue
                
                # Get assembly transform and origin
                trans = assembly.GetTransform()
                origin = trans.Origin
                
                # Normalize axis
                axis_normalized = axis.Normalize()
                
                # Create rotation transform
                angle_rad = math.radians(angle_deg)
                rotation_transform = Transform.CreateRotationAtPoint(
                    axis_normalized,
                    angle_rad,
                    origin
                )
                
                # Apply rotation
                new_transform = rotation_transform.Multiply(trans)
                assembly.SetTransform(new_transform)
                
                t.Commit()
                
                output.print_md("- ✅ **Rotated**: {} by {:.1f}°".format(
                    assembly_data.AssemblyName, angle_deg))
                rotated += 1
                
            except Exception as e:
                t.RollBack()
                output.print_md("- ❌ **Failed**: {} - {}".format(
                    assembly_data.AssemblyName, str(e)))
                failed += 1
        
        # Report
        output.print_md("---")
        output.print_md("### 📊 Summary")
        output.print_md("**Rotated**: {}".format(rotated))
        output.print_md("**Skipped**: {}".format(skipped))
        output.print_md("**Failed**: {}".format(failed))
        
        if rotated > 0:
            TaskDialog.Show("Complete", 
                "Assembly rotation complete!\n\n"
                "Rotated: {}\n"
                "Skipped: {}\n"
                "Failed: {}".format(rotated, skipped, failed))
        else:
            TaskDialog.Show("No Changes", 
                "No assemblies were rotated.\n\n"
                "Skipped: {}\n"
                "Failed: {}".format(skipped, failed))
    
    # EVENT HANDLERS
    def SetupEventHandlers(self):
        """Setup all event handlers"""
        self.btnClose.Click += self.OnClose
        self.btnRefresh.Click += self.OnRefresh
        self.txtSearch.TextChanged += self.OnSearchChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnDeselectAll.Click += self.OnDeselectAll
        self.btnRotate.Click += self.OnRotate
        self.dgAssemblies.CellEditEnding += self.OnCellEditEnding
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.Close()
    
    def OnRefresh(self, sender, args):
        """Refresh assemblies list"""
        self.LoadAssemblies()
    
    def OnSearchChanged(self, sender, args):
        """Search text changed"""
        self.RefreshGrid()
    
    def OnSelectAll(self, sender, args):
        """Select all visible assemblies"""
        if self.dgAssemblies.ItemsSource:
            for item in self.dgAssemblies.ItemsSource:
                item.IsSelected = True
            self.dgAssemblies.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnDeselectAll(self, sender, args):
        """Deselect all assemblies"""
        if self.dgAssemblies.ItemsSource:
            for item in self.dgAssemblies.ItemsSource:
                item.IsSelected = False
            self.dgAssemblies.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnRotate(self, sender, args):
        """Rotate button clicked"""
        self.RotateAssemblies()
    
    def OnCellEditEnding(self, sender, args):
        """Update when checkbox changes"""
        self._window.Dispatcher.BeginInvoke(
            System.Windows.Threading.DispatcherPriority.Background,
            System.Action(self.UpdateSelectedCount)
        )
    
    def ShowDialog(self):
        """Show the window"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get paths
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, 'RotateAssemblies.xaml')

# Check XAML exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected: {}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
try:
    window = RotateAssembliesWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)), title="Error")
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
