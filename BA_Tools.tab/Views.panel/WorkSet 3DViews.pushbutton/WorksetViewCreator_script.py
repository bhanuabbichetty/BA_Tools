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
        self.Name = workset.Name          # read-only workset name (never changes)
        self._view_name = ""              # blank by default — user types their own name
        self._is_selected = False
        self._property_changed = None
        
        # Set initial status
        self._refresh_status()
    
    # ── IsSelected ────────────────────────────────────────────────────
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        if self._is_selected != value:
            self._is_selected = value
            self.OnPropertyChanged("IsSelected")

    # ── ViewName (editable — bound to the new column) ─────────────────
    @property
    def ViewName(self):
        return self._view_name

    @ViewName.setter
    def ViewName(self, value):
        # Keep whatever the user typed — including empty string
        clean = (value or "").strip()
        if self._view_name != clean:
            self._view_name = clean
            self._refresh_status()
            self.OnPropertyChanged("ViewName")
            self.OnPropertyChanged("Status")

    # ── Status (derived — read-only) ──────────────────────────────────
    @property
    def Status(self):
        return self._status

    @Status.setter
    def Status(self, value):
        self._status = value
        self.OnPropertyChanged("Status")

    def _refresh_status(self):
        """
        Re-evaluate status.
        - If ViewName is blank  → will fall back to workset name at creation time,
          so check the workset name against existing views.
        - If ViewName is filled → check that custom name against existing views.
        """
        effective_name = self._view_name if self._view_name else self.Name
        if effective_name in all_view_names:
            self._status = "Already Exists"
        else:
            self._status = "Ready to Create"

    # ── INotifyPropertyChanged ────────────────────────────────────────
    def add_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Combine(self._property_changed, handler)
    
    def remove_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Remove(self._property_changed, handler)
    
    def OnPropertyChanged(self, property_name):
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
        
        # Load XAML — use io.open() for UTF-8 (IronPython 2.7 compatible)
        try:
            if not os.path.exists(xaml_file):
                forms.alert("XAML file not found at: {}".format(xaml_file), title="Error", exitscript=True)
            
            import io
            with io.open(xaml_file, 'r', encoding='utf-8') as f:
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
        self.btnClose = self._window.FindName("btnClose")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnCreate = self._window.FindName("btnCreate")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Connect button events
        self.btnClose.Click += self.OnCancel
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnClearAll.Click += self.OnClearAll
        self.btnCancel.Click += self.OnCancel
        self.btnCreate.Click += self.OnCreate
        self._window.Closing += self.OnClose
        
        # Enable full row click — but skip toggle when clicking inside the TextBox
        self.dgWorksets.LoadingRow += self.OnRowLoading

        # Block Space key from being swallowed by DataGrid when TextBox has focus
        self.dgWorksets.PreviewKeyDown += self.OnGridPreviewKeyDown
        
        # Load worksets
        self.LoadWorksets()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()

    def OnGridPreviewKeyDown(self, sender, args):
        """
        If key input originates from a TextBox inside the grid,
        do not let the DataGrid intercept/toggle selection.
        """
        from System.Windows.Controls import TextBox as WpfTextBox
        original = args.OriginalSource
        parent = original
        while parent is not None:
            if isinstance(parent, WpfTextBox):
                args.Handled = False
                return
            try:
                parent = System.Windows.Media.VisualTreeHelper.GetParent(parent)
            except Exception:
                break
    
    def OnRowLoading(self, sender, args):
        """Handle row loading to enable full row click and suppress space in TextBox"""
        row = args.Row
        row.MouseLeftButtonUp += MouseButtonEventHandler(self.OnRowClick)
        row.PreviewKeyDown    += self.OnRowPreviewKeyDown

    def OnRowPreviewKeyDown(self, sender, args):
        """
        If Space is pressed while a TextBox inside the row has focus,
        mark event as Handled=False so it flows to the TextBox,
        but prevent the DataGrid row from intercepting it as a select/toggle.
        We achieve this by stopping routing at the DataGrid boundary.
        """
        from System.Windows.Input import Key
        from System.Windows.Controls import TextBox as WpfTextBox
        if args.Key == Key.Space:
            # Walk up from original source — if it's a TextBox, stop propagation
            original = args.OriginalSource
            parent   = original
            while parent is not None:
                if isinstance(parent, WpfTextBox):
                    args.Handled = True   # prevents DataGrid from seeing it
                    # Manually insert space into the TextBox
                    try:
                        tb = parent
                        start = tb.SelectionStart
                        tb.Text = tb.Text[:start] + " " + tb.Text[start + tb.SelectionLength:]
                        tb.SelectionStart  = start + 1
                        tb.SelectionLength = 0
                    except Exception:
                        pass
                    return
                try:
                    parent = System.Windows.Media.VisualTreeHelper.GetParent(parent)
                except Exception:
                    break
    
    def OnRowClick(self, sender, args):
        """
        Toggle workset selection on row click.
        Skip the toggle when the click originated inside the View Name TextBox
        so the user can type freely without accidentally toggling the checkbox.
        """
        try:
            # Walk up the visual tree from the original source.
            # If the click came from a TextBox (the View Name input), do nothing.
            from System.Windows.Controls import TextBox as WpfTextBox
            original = args.OriginalSource
            parent   = original
            while parent is not None:
                if isinstance(parent, WpfTextBox):
                    return   # click was inside the text input — don't toggle
                try:
                    parent = System.Windows.Media.VisualTreeHelper.GetParent(parent)
                except Exception:
                    break

            row  = sender
            item = row.Item
            if item and hasattr(item, 'IsSelected'):
                item.IsSelected = not item.IsSelected
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
    
    def UpdateCount(self):
        """Update workset count display"""
        total    = len(self.workset_items)
        selected = sum(1 for item in self.workset_items if item.IsSelected)

        self.txtWorksetCount.Text = "{} worksets loaded, {} selected".format(total, selected)

        # Update status bar
        if selected == 0:
            self.txtStatus.Text = "Select worksets to create 3D views"
        else:
            ready  = sum(1 for item in self.workset_items
                         if item.IsSelected and item.Status == "Ready to Create")
            exists = sum(1 for item in self.workset_items
                         if item.IsSelected and item.Status == "Already Exists")

            # Count how many selected items use a custom name
            custom = sum(1 for item in self.workset_items
                         if item.IsSelected and item.ViewName != item.Name)

            parts = []
            if ready > 0:
                parts.append("{} new view(s) will be created".format(ready))
            if exists > 0:
                parts.append("{} already exist (will be skipped)".format(exists))
            if custom > 0:
                parts.append("{} using custom name(s)".format(custom))

            self.txtStatus.Text = "Ready — " + "  |  ".join(parts) if parts else "Select worksets"
    def OnItemPropertyChanged(self, sender, args):
        """Handle property change in workset items"""
        if args.PropertyName in ("IsSelected", "Status"):
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
            # If user left View Name blank → use workset name as fallback
            view_name = item.ViewName.strip() if item.ViewName.strip() else item.Workset.Name
            workset = item.Workset
            all_worksets = item.AllWorksets
            
            output.print_md("**[{}/{}]** Processing: {} → View: **{}**{}".format(
                idx + 1, len(selected_workset_items),
                workset.Name,
                view_name,
                "  *(custom name)*" if view_name != workset.Name else ""
            ))
            
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
