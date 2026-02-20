# -*- coding: utf-8 -*-
"""
Acquire Coordinates from Linked Models - WPF Modern UI
Match your model's coordinates to linked Arch/MEP models
"""
__title__ = 'Acquire\nCoordinates'
__doc__ = 'Match coordinates from linked models'

import clr
import os
clr.AddReference("RevitAPI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader

doc = revit.doc
output = script.get_output()


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_project_base_point(document):
    """Get the Project Base Point element"""
    collector = FilteredElementCollector(document)\
        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
        .WhereElementIsNotElementType()
    
    for elem in collector:
        return elem
    return None


def get_survey_point(document):
    """Get the Survey Point element"""
    collector = FilteredElementCollector(document)\
        .OfCategory(BuiltInCategory.OST_SharedBasePoint)\
        .WhereElementIsNotElementType()
    
    for elem in collector:
        return elem
    return None


def get_point_coordinates(point_element):
    """Get coordinates from point"""
    try:
        ew_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
        ns_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
        elev_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
        
        return {
            'x': ew_param.AsDouble() if ew_param else 0.0,
            'y': ns_param.AsDouble() if ns_param else 0.0,
            'z': elev_param.AsDouble() if elev_param else 0.0
        }
    except:
        return None


def get_point_3d_location(point_element):
    """Get actual 3D location of point"""
    try:
        # Try location point
        location = point_element.Location
        if location and hasattr(location, 'Point'):
            return location.Point
        
        # Try bounding box
        bbox = point_element.get_BoundingBox(None)
        if bbox:
            center = (bbox.Min + bbox.Max) / 2.0
            return center
        
        # Fall back to parameters
        coords = get_point_coordinates(point_element)
        if coords:
            return XYZ(coords['x'], coords['y'], coords['z'])
        
        return None
    except:
        return None


def set_point_coordinates(point_element, location):
    """Set point to specific location"""
    try:
        # Unclip
        try:
            clipped_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_CLIPPED_PARAM)
            if clipped_param and clipped_param.AsInteger() == 1:
                clipped_param.Set(0)
        except:
            try:
                if point_element.Pinned:
                    point_element.Pinned = False
            except:
                pass
        
        # Set coordinates
        ew_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
        ns_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
        elev_param = point_element.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
        
        success = False
        if ew_param and not ew_param.IsReadOnly:
            ew_param.Set(location.X)
            success = True
        if ns_param and not ns_param.IsReadOnly:
            ns_param.Set(location.Y)
            success = True
        if elev_param and not elev_param.IsReadOnly:
            elev_param.Set(location.Z)
            success = True
        
        return success
    except:
        return False


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class AcquireCoordinatesWindow(Window):
    def __init__(self, xaml_path, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.doc = document
        self.result = False
        self.linked_models = []
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.rbVisualPosition = self._window.FindName("rbVisualPosition")
        self.rbCoordinateValues = self._window.FindName("rbCoordinateValues")
        self.txtCurrentSurvey = self._window.FindName("txtCurrentSurvey")
        self.txtCurrentProject = self._window.FindName("txtCurrentProject")
        self.btnRefresh = self._window.FindName("btnRefresh")
        self.lstLinkedModels = self._window.FindName("lstLinkedModels")
        self.txtLinkInfo = self._window.FindName("txtLinkInfo")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnAcquire = self._window.FindName("btnAcquire")
        
        # Setup event handlers
        self.SetupEventHandlers()
        
        # Load initial data
        self.LoadCurrentCoordinates()
        self.LoadLinkedModels()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.btnRefresh.Click += self.OnRefresh
        self.btnAcquire.Click += self.OnAcquire
        self.lstLinkedModels.SelectionChanged += self.OnLinkSelected
        # Wire drag handler for borderless window
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
    
    def OnRefresh(self, sender, args):
        """Refresh data"""
        self.LoadCurrentCoordinates()
        self.LoadLinkedModels()
        self.txtStatus.Text = "Refreshed"
    
    def OnLinkSelected(self, sender, args):
        """When link is selected"""
        if self.lstLinkedModels.SelectedIndex < 0:
            self.txtLinkInfo.Text = "Select a linked model above"
            return
        
        link = self.linked_models[self.lstLinkedModels.SelectedIndex]
        
        info = "Selected: {}\n\n".format(link['name'])
        
        if link['survey_point_location']:
            sp = link['survey_point_location']
            info += "Survey Point: ({:.3f}, {:.3f}, {:.3f})\n".format(sp.X, sp.Y, sp.Z)
        
        if link['project_base_point_location']:
            pbp = link['project_base_point_location']
            info += "Project Base: ({:.3f}, {:.3f}, {:.3f})".format(pbp.X, pbp.Y, pbp.Z)
        
        self.txtLinkInfo.Text = info
    
    def LoadCurrentCoordinates(self):
        """Load current host model coordinates"""
        sp = get_survey_point(doc)
        if sp:
            coords = get_point_coordinates(sp)
            if coords:
                self.txtCurrentSurvey.Text = "({:.3f}, {:.3f}, {:.3f})".format(
                    coords['x'], coords['y'], coords['z'])
        
        pbp = get_project_base_point(doc)
        if pbp:
            coords = get_point_coordinates(pbp)
            if coords:
                self.txtCurrentProject.Text = "({:.3f}, {:.3f}, {:.3f})".format(
                    coords['x'], coords['y'], coords['z'])
    
    def LoadLinkedModels(self):
        """Load linked models"""
        self.linked_models = []
        self.lstLinkedModels.Items.Clear()
        
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
        
        for link_instance in collector:
            try:
                link_doc = link_instance.GetLinkDocument()
                if not link_doc:
                    continue
                
                transform = link_instance.GetTotalTransform()
                
                # Get Survey Point
                link_sp = get_survey_point(link_doc)
                sp_location = None
                if link_sp:
                    sp_local = get_point_3d_location(link_sp)
                    if sp_local:
                        sp_location = transform.OfPoint(sp_local)
                
                # Get Project Base Point
                link_pbp = get_project_base_point(link_doc)
                pbp_location = None
                if link_pbp:
                    pbp_local = get_point_3d_location(link_pbp)
                    if pbp_local:
                        pbp_location = transform.OfPoint(pbp_local)
                
                if sp_location or pbp_location:
                    self.linked_models.append({
                        'name': link_doc.Title,
                        'instance': link_instance,
                        'document': link_doc,
                        'survey_point_location': sp_location,
                        'project_base_point_location': pbp_location
                    })
                    
                    # Add to list
                    display_name = link_doc.Title
                    if sp_location:
                        display_name += " - SP: ({:.0f}, {:.0f}, {:.0f})".format(
                            sp_location.X, sp_location.Y, sp_location.Z)
                    
                    self.lstLinkedModels.Items.Add(display_name)
            
            except Exception as e:
                output.print_md("Error reading link: {}".format(str(e)))
        
        if len(self.linked_models) == 0:
            self.txtStatus.Text = "No linked models found"
            self.btnAcquire.IsEnabled = False
        else:
            self.txtStatus.Text = "Found {} linked model(s)".format(len(self.linked_models))
            self.btnAcquire.IsEnabled = True
    
    def OnAcquire(self, sender, args):
        """Acquire coordinates from selected link"""
        if self.lstLinkedModels.SelectedIndex < 0:
            forms.alert("Please select a linked model", title="No Selection")
            return
        
        selected_link = self.linked_models[self.lstLinkedModels.SelectedIndex]
        
        # Confirm
        msg = "Acquire coordinates from:\n\n{}\n\nThis will move your Survey Point and Project Base Point to match the linked model.\n\nContinue?".format(
            selected_link['name'])
        
        if not forms.alert(msg, yes=True, no=True, title="Confirm"):
            return
        
        # Update UI
        self.btnAcquire.IsEnabled = False
        self.txtStatus.Text = "Acquiring coordinates..."
        
        # Do acquisition
        success = True
        use_visual = self.rbVisualPosition.IsChecked
        
        with revit.Transaction("Acquire Coordinates"):
            host_sp = get_survey_point(doc)
            host_pbp = get_project_base_point(doc)
            
            # Survey Point
            if host_sp and selected_link['survey_point_location']:
                if not set_point_coordinates(host_sp, selected_link['survey_point_location']):
                    success = False
                    output.print_md("Failed to set Survey Point")
            
            # Project Base Point
            if host_pbp and selected_link['project_base_point_location']:
                if not set_point_coordinates(host_pbp, selected_link['project_base_point_location']):
                    success = False
                    output.print_md("Failed to set Project Base Point")
        
        if success:
            self.txtStatus.Text = "✓ Coordinates acquired successfully"
            self.LoadCurrentCoordinates()
            
            forms.alert(
                "Coordinates acquired!\n\nYour coordinate points now match:\n{}".format(
                    selected_link['name']),
                title="Success"
            )
            
            self.result = True
        else:
            self.txtStatus.Text = "⚠ Partial success - some points may need manual unclipping"
            
            forms.alert(
                "Partial success.\n\nSome points couldn't be moved.\nTry unclipping them manually:\n\n1. Type VG\n2. Show coordinate points\n3. Right-click → Unclip\n4. Try again",
                title="Warning"
            )
        
        self.btnAcquire.IsEnabled = True
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "AcquireCoordinates.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = AcquireCoordinatesWindow(xaml_path, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Coordinates Acquired Successfully")
else:
    output.print_md("### Operation Cancelled or Closed")
