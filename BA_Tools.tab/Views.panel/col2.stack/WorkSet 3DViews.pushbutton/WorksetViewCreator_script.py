# -*- coding: utf-8 -*-
__title__ = "Workset 3D Views"
__author__ = "Bhanu Prakash A"
__doc__ = """Version = 1.0
Date    = 2025.02.10
_____________________________________________________________________
Description:

Create 3D View for selected worksets and isolate their elements.
Improved UI - Click anywhere on row to select workset.
_____________________________________________________________________
"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
import os
import sys
import clr

# Add WPF references
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')
clr.AddReference('System')

from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Controls import DataGrid, DataGridRow
from System.Collections.Generic import List
import System
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs

from Autodesk.Revit.DB import (
    View3D, FilteredWorksetCollector, WorksetKind, WorksetVisibility,
    ViewFamilyType, FilteredElementCollector, Transaction,
    BuiltInParameter, BuiltInCategory
)

# pyRevit
from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

# Get all existing view names
all_views = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Views).ToElements()
all_view_names = [view.Name for view in all_views]


# ╔═╗╦  ╔═╗╔═╗╔═╗╔═╗╔═╗
# ╠═╝║  ╠═╣╚═╗╚═╗║╣ ╚═╗
# ╩  ╩═╝╩ ╩╚═╝╚═╝╚═╝╚═╝ CLASSES
# ==================================================

class WorksetItem(INotifyPropertyChanged):
    """Class to represent a workset in the UI with proper property change notification"""
    
    def __init__(self, workset, all_worksets):
        self.Workset = workset
        self.AllWorksets = all_worksets
        self.Name = workset.Name
        self.ViewName = workset.Name
        self._is_selected = False
        self._property_changed = None
        
        # Check if view already exists
        if self.ViewName in all_view_names:
            self.Status = "Already Exists"
        else:
            self.Status = "Ready to Create"
    
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        if self._is_selected != value:
            self._is_selected = value
            self.OnPropertyChanged("IsSelected")
    
    def add_PropertyChanged(self, handler):
        """Add PropertyChanged event handler"""
        self._property_changed = System.Delegate.Combine(self._property_changed, handler)
    
    def remove_PropertyChanged(self, handler):
        """Remove PropertyChanged event handler"""
        self._property_changed = System.Delegate.Remove(self._property_changed, handler)
    
    def OnPropertyChanged(self, property_name):
        """Raise PropertyChanged event"""
        if self._property_changed:
            args = PropertyChangedEventArgs(property_name)
            self._property_changed(self, args)


class WorksetViewCreatorWindow(object):
    """Main window for workset 3D view creator"""
    
    def __init__(self, xaml_file, document):
        self.doc = document
        self.result = False
        self.selected_worksets = []
        self.workset_items = []
        
        # Load XAML
        try:
            if not os.path.exists(xaml_file):
                forms.alert("XAML file not found at: {}".format(xaml_file), title="Error", exitscript=True)
            
            with open(xaml_file, 'r') as f:
                xaml_content = f.read()
                self._window = XamlReader.Parse(xaml_content)
        except Exception as e:
            error_msg = "Error loading XAML:\n\n{}".format(str(e))
            forms.alert(error_msg, title="XAML Error", exitscript=True)
        
        # Get controls
        self.dgWorksets = self._window.FindName("dgWorksets")
        self.txtWorksetCount = self._window.FindName("txtWorksetCount")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnClearAll = self._window.FindName("btnClearAll")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnCreate = self._window.FindName("btnCreate")
        
        # Connect button events
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnClearAll.Click += self.OnClearAll
        self.btnCancel.Click += self.OnCancel
        self.btnCreate.Click += self.OnCreate
        self._window.Closing += self.OnClose
        
        # Enable full row click - this is the key improvement
        self.dgWorksets.LoadingRow += self.OnRowLoading
        
        # Load worksets
        self.LoadWorksets()
    
    def OnRowLoading(self, sender, args):
        """Handle row loading to enable full row click"""
        row = args.Row
        # Add mouse click handler to the entire row
        row.MouseLeftButtonUp += MouseButtonEventHandler(self.OnRowClick)
    
    def OnRowClick(self, sender, args):
        """Handle row click - toggle selection"""
        try:
            row = sender
            item = row.Item
            if item and hasattr(item, 'IsSelected'):
                # Toggle selection
                item.IsSelected = not item.IsSelected
                # Refresh to update UI
                self.dgWorksets.Items.Refresh()
        except Exception as e:
            output.print_md("Row click error: {}".format(str(e)))
    
    def LoadWorksets(self):
        """Load all worksets into the DataGrid"""
        try:
            # Get all user worksets
            all_worksets = FilteredWorksetCollector(self.doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
            
            if not all_worksets:
                forms.alert('No User Worksets found in the current project.', 
                           title="No Worksets", exitscript=True)
                return
            
            # Create workset items
            items_list = List[object]()
            for workset in all_worksets:
                item = WorksetItem(workset, all_worksets)
                # Subscribe to property changes
                item.PropertyChanged += self.OnItemPropertyChanged
                self.workset_items.append(item)
                items_list.Add(item)
            
            # Bind to DataGrid
            self.dgWorksets.ItemsSource = items_list
            
            # Update count
            self.UpdateCount()
            
            output.print_md("## ✅ Loaded {} worksets".format(len(all_worksets)))
            
        except Exception as e:
            forms.alert("Error loading worksets: {}".format(str(e)), title="Error")
    
    def OnItemPropertyChanged(self, sender, args):
        """Handle property change in workset items"""
        if args.PropertyName == "IsSelected":
            self.UpdateCount()
    
    def UpdateCount(self):
        """Update workset count display"""
        total = len(self.workset_items)
        selected = sum(1 for item in self.workset_items if item.IsSelected)
        
        self.txtWorksetCount.Text = "{} worksets loaded, {} selected".format(total, selected)
        
        # Update status
        if selected == 0:
            self.txtStatus.Text = "Select worksets to create 3D views"
        else:
            ready = sum(1 for item in self.workset_items if item.IsSelected and item.Status == "Ready to Create")
            exists = sum(1 for item in self.workset_items if item.IsSelected and item.Status == "Already Exists")
            
            if ready > 0 and exists > 0:
                self.txtStatus.Text = "Ready: {} new views will be created ({} already exist)".format(ready, exists)
            elif ready > 0:
                self.txtStatus.Text = "Ready: {} new views will be created".format(ready)
            else:
                self.txtStatus.Text = "All selected views already exist"
    
    def OnSelectAll(self, sender, args):
        """Select all worksets"""
        for item in self.workset_items:
            item.IsSelected = True
        self.dgWorksets.Items.Refresh()
    
    def OnClearAll(self, sender, args):
        """Clear all selections"""
        for item in self.workset_items:
            item.IsSelected = False
        self.dgWorksets.Items.Refresh()
    
    def OnCancel(self, sender, args):
        """Handle Cancel button"""
        self.result = False
        self._window.Close()
    
    def OnCreate(self, sender, args):
        """Handle Create button"""
        # Get selected items
        self.selected_worksets = [item for item in self.workset_items if item.IsSelected]
        
        if not self.selected_worksets:
            forms.alert("Please select at least one workset.", title="No Selection")
            return
        
        self.result = True
        self._window.Close()
    
    def OnClose(self, sender, args):
        """Handle window closing"""
        pass
    
    def ShowDialog(self):
        """Show the window as a dialog"""
        try:
            self._window.ShowDialog()
            return self.result
        except Exception as e:
            forms.alert("Error showing dialog: {}".format(str(e)), title="Error")
            return False


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ FUNCTIONS
# ==================================================

def get_view_type_3D():
    """Function to get ViewType - 3D View"""
    all_view_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    for view_type in all_view_types:
        try:
            type_name = view_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
            if type_name and '3D' in type_name:
                return view_type
        except:
            continue
    return None


def create_workset_views(selected_workset_items, view_type_3D):
    """Create 3D views for selected worksets"""
    created_views = []
    skipped_views = []
    failed_views = []
    last_view = None
    
    output.print_md("## 🚀 Creating Workset 3D Views")
    output.print_md("---")
    output.print_md("**Processing {} workset(s)...**".format(len(selected_workset_items)))
    output.print_md("")
    
    # Create transaction for all view creation
    t = Transaction(doc, "Create Workset 3D Views")
    t.Start()
    
    try:
        for idx, item in enumerate(selected_workset_items):
            view_name = item.ViewName
            workset = item.Workset
            all_worksets = item.AllWorksets
            
            output.print_md("**[{}/{}]** Processing: {}".format(idx + 1, len(selected_workset_items), workset.Name))
            
            # Skip if already exists
            if item.Status == "Already Exists":
                output.print_md("  ⏭ **SKIPPED**: {} (already exists)".format(view_name))
                skipped_views.append(view_name)
                continue
            
            # Create new 3D view
            try:
                # Create isometric view
                new_view = View3D.CreateIsometric(doc, view_type_3D.Id)
                
                # Set name
                new_view.Name = view_name
                output.print_md("  📝 View created: {}".format(view_name))
                
                # Set workset visibilities
                visibility_set = 0
                for ws in all_worksets:
                    try:
                        if workset.Id.IntegerValue == ws.Id.IntegerValue:
                            new_view.SetWorksetVisibility(ws.Id, WorksetVisibility.Visible)
                            visibility_set += 1
                        else:
                            new_view.SetWorksetVisibility(ws.Id, WorksetVisibility.Hidden)
                    except Exception as vis_error:
                        output.print_md("  ⚠ Visibility warning for workset {}: {}".format(ws.Name, str(vis_error)))
                
                output.print_md("  ✅ **CREATED**: {} (visibility set for {} worksets)".format(view_name, visibility_set))
                created_views.append(view_name)
                last_view = new_view
                
            except Exception as e:
                output.print_md("  ❌ **FAILED**: {} - Error: {}".format(view_name, str(e)))
                failed_views.append((view_name, str(e)))
        
        # Commit transaction
        t.Commit()
        output.print_md("")
        output.print_md("**✅ Transaction committed successfully**")
        
    except Exception as e:
        # Rollback on error
        t.RollBack()
        output.print_md("")
        output.print_md("## ❌ Transaction Failed")
        output.print_md("**Error:** {}".format(str(e)))
        import traceback
        output.print_md("```\n{}\n```".format(traceback.format_exc()))
        return None, created_views, skipped_views, failed_views
    
    # Summary
    output.print_md("---")
    output.print_md("## 📊 Summary")
    output.print_md("✅ **Created**: {} view(s)".format(len(created_views)))
    if created_views:
        for view_name in created_views:
            output.print_md("   - {}".format(view_name))
    
    output.print_md("⏭ **Skipped**: {} view(s)".format(len(skipped_views)))
    if skipped_views:
        for view_name in skipped_views:
            output.print_md("   - {}".format(view_name))
    
    if failed_views:
        output.print_md("❌ **Failed**: {} view(s)".format(len(failed_views)))
        for view_name, error in failed_views:
            output.print_md("   - {}: {}".format(view_name, error))
    
    output.print_md("---")
    
    return last_view, created_views, skipped_views, failed_views


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================

if __name__ == '__main__':
    try:
        # Get XAML file path
        script_dir = os.path.dirname(__file__)
        xaml_file = os.path.join(script_dir, "WorksetViewCreator.xaml")
        
        # Check if XAML exists
        if not os.path.exists(xaml_file):
            forms.alert(
                "XAML file not found!\n\nExpected location:\n{}".format(script_dir),
                title="Missing XAML File", 
                exitscript=True
            )
        
        # Check if worksets are enabled
        if not doc.IsWorkshared:
            forms.alert(
                "This project is not workshared.\n\nWorksets are not available.",
                title="Not Workshared", 
                exitscript=True
            )
        
        # Get 3D view type
        view_type_3D = get_view_type_3D()
        if not view_type_3D:
            forms.alert(
                "Could not find 3D View Type in the project.\n\nPlease ensure a 3D view type exists.",
                title="Missing View Type", 
                exitscript=True
            )
        
        # Show UI
        output.print_md("## 🚀 Workset 3D View Creator")
        output.print_md("Loading interface...")
        
        ui = WorksetViewCreatorWindow(xaml_file, doc)
        result = ui.ShowDialog()
        
        # Process if user clicked Create
        if result and ui.selected_worksets:
            output.print_md("## 🔧 Processing selected worksets...")
            output.print_md("Total selected: {}".format(len(ui.selected_worksets)))
            
            # Filter only items that need to be created
            to_create = [item for item in ui.selected_worksets if item.Status == "Ready to Create"]
            
            output.print_md("Items to create: {}".format(len(to_create)))
            for item in to_create:
                output.print_md("  - {}".format(item.Name))
            output.print_md("")
            
            if to_create:
                # Create views
                last_view, created, skipped, failed = create_workset_views(to_create, view_type_3D)
                
                # Show summary
                summary_parts = []
                summary_parts.append("✅ Created: {}".format(len(created)))
                summary_parts.append("⏭ Skipped: {}".format(len(skipped)))
                if failed:
                    summary_parts.append("❌ Failed: {}".format(len(failed)))
                
                summary = "\n".join(summary_parts)
                forms.alert(summary, title="Complete")
                
                # Set active view to last created view
                if last_view:
                    try:
                        uidoc.ActiveView = last_view
                        output.print_md("## ✅ Active view set to: {}".format(last_view.Name))
                    except:
                        pass
            else:
                output.print_md("## ℹ All selected views already exist")
                forms.alert("All selected views already exist.", title="Nothing to Create")
        else:
            output.print_md("## ⏹ Operation Cancelled")
    
    except Exception as e:
        import traceback
        error_msg = "Script Error:\n\n{}".format(str(e))
        output.print_md("## ❌ ERROR")
        output.print_md("```\n{}\n```".format(traceback.format_exc()))
        forms.alert(error_msg, title="Script Error")
