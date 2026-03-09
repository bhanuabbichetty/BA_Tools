# -*- coding: utf-8 -*-
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

def get_project_base_point(document):
    collector = FilteredElementCollector(document)\
        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
        .WhereElementIsNotElementType()
    for elem in collector:
        return elem
    return None

def get_survey_point(document):
    collector = FilteredElementCollector(document)\
        .OfCategory(BuiltInCategory.OST_SharedBasePoint)\
        .WhereElementIsNotElementType()
    for elem in collector:
        return elem
    return None

def get_point_coordinates(point_element):
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
    try:
        location = point_element.Location
        if location and hasattr(location, 'Point'):
            return location.Point
        bbox = point_element.get_BoundingBox(None)
        if bbox:
            return (bbox.Min + bbox.Max) / 2.0
        coords = get_point_coordinates(point_element)
        if coords:
            return XYZ(coords['x'], coords['y'], coords['z'])
        return None
    except:
        return None

def unclip_point(point_element):
    try:
        clipped = point_element.get_Parameter(BuiltInParameter.BASEPOINT_CLIPPED_PARAM)
        if clipped and clipped.AsInteger() == 1:
            clipped.Set(0)
    except:
        pass
    try:
        if point_element.Pinned:
            point_element.Pinned = False
    except:
        pass

def move_point_to_location(point_element, target_location):
    try:
        unclip_point(point_element)
        current_location = get_point_3d_location(point_element)
        if not current_location:
            return False
        translation = target_location - current_location
        ElementTransformUtils.MoveElement(doc, point_element.Id, translation)
        return True
    except:
        return False

class AcquireCoordinatesWindow(Window):
    def __init__(self, xaml_path, document):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.doc = document
        self.result = False
        self.linked_models = []
        
        self.btnClose = self._window.FindName("btnClose")
        self.txtCurrentSurvey = self._window.FindName("txtCurrentSurvey")
        self.txtCurrentProject = self._window.FindName("txtCurrentProject")
        self.btnRefresh = self._window.FindName("btnRefresh")
        self.lstLinkedModels = self._window.FindName("lstLinkedModels")
        self.txtLinkInfo = self._window.FindName("txtLinkInfo")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnAcquire = self._window.FindName("btnAcquire")
        
        self.SetupEventHandlers()
        self.LoadCurrentCoordinates()
        self.LoadLinkedModels()
    
    def SetupEventHandlers(self):
        self.btnClose.Click += self.OnClose
        self.btnRefresh.Click += self.OnRefresh
        self.btnAcquire.Click += self.OnAcquire
        self.lstLinkedModels.SelectionChanged += self.OnLinkSelected
        header_border = self._window.FindName("headerDragArea")
        if header_border:
            header_border.MouseLeftButtonDown += self.OnHeaderDrag
    
    def OnHeaderDrag(self, sender, args):
        try:
            self._window.DragMove()
        except:
            pass
    
    def OnClose(self, sender, args):
        self._window.DialogResult = False
        self._window.Close()
    
    def OnRefresh(self, sender, args):
        self.LoadCurrentCoordinates()
        self.LoadLinkedModels()
        self.txtStatus.Text = "Refreshed"
    
    def OnLinkSelected(self, sender, args):
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
        self.linked_models = []
        self.lstLinkedModels.Items.Clear()
        
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
        
        for link_instance in collector:
            try:
                link_doc = link_instance.GetLinkDocument()
                if not link_doc:
                    continue
                
                transform = link_instance.GetTotalTransform()
                
                link_sp = get_survey_point(link_doc)
                sp_location = None
                if link_sp:
                    sp_local = get_point_3d_location(link_sp)
                    if sp_local:
                        sp_location = transform.OfPoint(sp_local)
                
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
                    
                    display_name = link_doc.Title
                    if sp_location:
                        display_name += " - SP: ({:.0f}, {:.0f}, {:.0f})".format(
                            sp_location.X, sp_location.Y, sp_location.Z)
                    
                    self.lstLinkedModels.Items.Add(display_name)
            except:
                pass
        
        if len(self.linked_models) == 0:
            self.txtStatus.Text = "No linked models found"
            self.btnAcquire.IsEnabled = False
        else:
            self.txtStatus.Text = "Found {} linked model(s)".format(len(self.linked_models))
            self.btnAcquire.IsEnabled = True
    
    def OnAcquire(self, sender, args):
        if self.lstLinkedModels.SelectedIndex < 0:
            forms.alert("Please select a linked model", title="No Selection")
            return
        
        selected_link = self.linked_models[self.lstLinkedModels.SelectedIndex]
        
        msg = "Acquire coordinates from:\n\n{}\n\nContinue?".format(selected_link['name'])
        
        if not forms.alert(msg, yes=True, no=True, title="Confirm"):
            return
        
        self.btnAcquire.IsEnabled = False
        self.txtStatus.Text = "Acquiring..."
        
        try:
            with revit.Transaction("Acquire Coordinates"):
                doc.AcquireCoordinates(selected_link['instance'].Id)
                
                host_sp = get_survey_point(doc)
                host_pbp = get_project_base_point(doc)
                
                if host_sp and selected_link['survey_point_location']:
                    move_point_to_location(host_sp, selected_link['survey_point_location'])
                
                if host_pbp and selected_link['project_base_point_location']:
                    move_point_to_location(host_pbp, selected_link['project_base_point_location'])
            
            self.txtStatus.Text = "✓ Success"
            self.result = True
            self.LoadCurrentCoordinates()
            forms.alert("Coordinates acquired and points aligned!", title="Success")
            self._window.DialogResult = True
            self._window.Close()
            
        except Exception as e:
            self.txtStatus.Text = "⚠ Failed"
            forms.alert("Error: {}".format(str(e)), title="Error")
            self.btnAcquire.IsEnabled = True
    
    def ShowDialog(self):
        return self._window.ShowDialog()

script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "AcquireCoordinates.xaml")

if not os.path.exists(xaml_path):
    forms.alert("XAML file not found!\n\n{}".format(xaml_path), title="Error", exitscript=True)

window = AcquireCoordinatesWindow(xaml_path, doc)
window.ShowDialog()