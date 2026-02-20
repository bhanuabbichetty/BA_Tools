# -*- coding: utf-8 -*-
"""
Workset Creator
Create multiple worksets from predefined list or custom names
"""
__title__ = 'Create\nWorksets'
__doc__ = 'Create worksets from predefined list or custom names'

import clr
import os
clr.AddReference("RevitAPI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import Workset, FilteredWorksetCollector, WorksetKind
from pyrevit import revit, script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection

doc = revit.doc
output = script.get_output()


# ==============================================================================
# WORKSET MASTER LIST
# ==============================================================================

WORKSETS = [
    "AR-Civil Works-GF",
    "AR-Civil Works-FF",
    "LINK-CAD-ST",
    "LINK-RVT-AR",
    "LINK-RVT-EL",
    "LINK-RVT-GN",
    "LINK-RVT-ID",
    "LINK-RVT-LA",
    "LINK-RVT-ME",
    "LINK-RVT-PL",
    "LINK-RVT-ST",
    "ST-Beam-FF",
    "ST-Beam-RF",
    "ST-BLOCK WALL-FF",
    "ST-BLOCK WALL-GF",
    "ST-BLOCK WALL-PA",
    "ST-CIP-FF",
    "ST-CIP-RF",
    "ST-Column-FF",
    "ST-Column-GF",
    "ST-Erection Mark-FF",
    "ST-Erection Mark-GF",
    "ST-Erection Mark-RF",
    "ST-Foundation",
    "ST-Hollowcore-FF",
    "ST-Hollowcore-RF",
    "ST-Reveals-FF",
    "ST-Reveals-GF",
    "ST-Reveals-RF",
    "ST-SLAB-FF",
    "ST-SLAB-GF",
    "ST-SLAB-RF",
    "ST-STAIR-FF",
    "ST-STAIR-GF",
    "ST-Stru Opngs-FF",
    "ST-Stru Opngs-RF",
    "ST-WALL-FF",
    "ST-WALL-GF",
    "ST-WALL-RF"
]


# ==============================================================================
# DATA CLASSES
# ==============================================================================

class WorksetItem(System.ComponentModel.INotifyPropertyChanged):
    """Observable workset item for checkbox binding"""
    
    def __init__(self, workset_name):
        self._workset_name = workset_name
        self._display_text = workset_name
        self._is_selected = False
        self._property_changed = None
    
    @property
    def WorksetName(self):
        return self._workset_name
    
    @property
    def DisplayText(self):
        return self._display_text
    
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        if self._is_selected != value:
            self._is_selected = value
            self.OnPropertyChanged("IsSelected")
    
    def add_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Combine(self._property_changed, handler)
    
    def remove_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Remove(self._property_changed, handler)
    
    def OnPropertyChanged(self, property_name):
        if self._property_changed:
            args = System.ComponentModel.PropertyChangedEventArgs(property_name)
            self._property_changed(self, args)


# ==============================================================================
# CHECK WORKSHARING
# ==============================================================================

if not doc.IsWorkshared:
    forms.alert('Project is not workshared.\n\nThis tool only works with workshared projects.', 
                title='Not Workshared', exitscript=True)

# Get existing worksets
existing_worksets = [ws.Name for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)]
available_worksets = [w for w in WORKSETS if w not in existing_worksets]

output.print_md("**Existing worksets**: {}".format(len(existing_worksets)))
output.print_md("**Available to create**: {}".format(len(available_worksets)))


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class WorksetCreatorWindow(Window):
    def __init__(self, xaml_path, available_worksets, existing_count, document, existing_workset_names):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.available_worksets = available_worksets
        self.existing_count = existing_count
        self.existing_workset_names = existing_workset_names
        self.workset_items = ObservableCollection[WorksetItem]()
        self.doc = document
        self.result = False
        self.selected_worksets = []
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.txtExistingCount = self._window.FindName("txtExistingCount")
        self.txtAvailableCount = self._window.FindName("txtAvailableCount")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnClearAll = self._window.FindName("btnClearAll")
        self.txtSelectedCount = self._window.FindName("txtSelectedCount")
        self.lstWorksets = self._window.FindName("lstWorksets")
        self.borderNoWorksets = self._window.FindName("borderNoWorksets")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnCreate = self._window.FindName("btnCreate")
        
        # Custom workset input controls
        self.txtCustomWorkset = self._window.FindName("txtCustomWorkset")
        self.btnAddCustom = self._window.FindName("btnAddCustom")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize workset items"""
        # Update counts
        self.txtExistingCount.Text = str(self.existing_count)
        self.txtAvailableCount.Text = str(len(self.available_worksets))
        
        # Check if no worksets available
        if not self.available_worksets:
            self.borderNoWorksets.Visibility = System.Windows.Visibility.Visible
            self.txtStatus.Text = "All predefined worksets exist - Use custom input to add more"
        else:
            self.borderNoWorksets.Visibility = System.Windows.Visibility.Collapsed
        
        # Populate workset items
        for workset_name in sorted(self.available_worksets):
            workset_item = WorksetItem(workset_name)
            workset_item.PropertyChanged += self.OnWorksetSelectionChanged
            self.workset_items.Add(workset_item)
        
        self.lstWorksets.ItemsSource = self.workset_items
        self.UpdateSelectedCount()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnClearAll.Click += self.OnClearAll
        self.btnCancel.Click += self.OnCancel
        self.btnCreate.Click += self.OnCreate
        self.btnAddCustom.Click += self.OnAddCustomWorkset
        self.txtCustomWorkset.KeyDown += self.OnCustomWorksetKeyDown
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
        self._window.Close()
    
    def OnCancel(self, sender, args):
        """Cancel and close"""
        self._window.Close()
    
    def OnSelectAll(self, sender, args):
        """Select all worksets"""
        for item in self.workset_items:
            item.IsSelected = True
        self.UpdateSelectedCount()
    
    def OnClearAll(self, sender, args):
        """Clear all selections"""
        for item in self.workset_items:
            item.IsSelected = False
        self.UpdateSelectedCount()
    
    def OnWorksetSelectionChanged(self, sender, args):
        """When workset selection changes"""
        self.UpdateSelectedCount()
    
    def UpdateSelectedCount(self):
        """Update selected count label"""
        selected_count = sum(1 for item in self.workset_items if item.IsSelected)
        total_count = len(self.workset_items)
        self.txtSelectedCount.Text = "{} / {}".format(selected_count, total_count)
        
        # Update status
        if selected_count == 0:
            self.txtStatus.Text = "Select worksets or add custom names to begin"
        else:
            self.txtStatus.Text = "Ready to create {} workset(s)".format(selected_count)
    
    def OnCustomWorksetKeyDown(self, sender, args):
        """Handle Enter key in custom workset textbox"""
        if args.Key == System.Windows.Input.Key.Return:
            self.OnAddCustomWorkset(sender, args)
    
    def OnAddCustomWorkset(self, sender, args):
        """Add custom workset to the list"""
        custom_name = self.txtCustomWorkset.Text.strip()
        
        if not custom_name:
            forms.alert("Please enter a workset name", title="Validation Error")
            return
        
        # Check if already exists in project
        if custom_name in self.existing_workset_names:
            forms.alert("Workset '{}' already exists in the project".format(custom_name), 
                       title="Already Exists")
            return
        
        # Check if already in the list
        existing_in_list = [item for item in self.workset_items if item.WorksetName == custom_name]
        if existing_in_list:
            forms.alert("Workset '{}' is already in the list".format(custom_name), 
                       title="Already in List")
            return
        
        # Add to list
        workset_item = WorksetItem(custom_name)
        workset_item.IsSelected = True
        workset_item.PropertyChanged += self.OnWorksetSelectionChanged
        self.workset_items.Add(workset_item)
        
        # Clear textbox
        self.txtCustomWorkset.Text = ""
        
        # Update UI
        if self.borderNoWorksets.Visibility == System.Windows.Visibility.Visible:
            self.borderNoWorksets.Visibility = System.Windows.Visibility.Collapsed
        
        self.UpdateSelectedCount()
        
        # Focus back to textbox
        self.txtCustomWorkset.Focus()
        
        output.print_md("Added custom workset to list: **{}**".format(custom_name))
    
    def OnCreate(self, sender, args):
        """Create selected worksets"""
        # Get selected worksets
        selected_items = [item for item in self.workset_items if item.IsSelected]
        
        if not selected_items:
            forms.alert("Please select at least one workset or add a custom workset", 
                       title="Validation Error")
            return
        
        self.selected_worksets = [item.WorksetName for item in selected_items]
        
        # Confirm
        confirm_msg = "Create {} workset(s)?\n\n".format(len(self.selected_worksets))
        if len(self.selected_worksets) <= 10:
            confirm_msg += "Worksets:\n"
            for ws in self.selected_worksets:
                confirm_msg += "• {}\n".format(ws)
        else:
            confirm_msg += "First 10 worksets:\n"
            for ws in self.selected_worksets[:10]:
                confirm_msg += "• {}\n".format(ws)
            confirm_msg += "• ... and {} more\n".format(len(self.selected_worksets) - 10)
        
        if not forms.alert(confirm_msg, yes=True, no=True, title="Confirm Creation"):
            return
        
        # Update UI
        self.btnCreate.IsEnabled = False
        self.btnCreate.Content = "CREATING..."
        self.txtStatus.Text = "Creating worksets..."
        
        success_count = 0
        error_count = 0
        
        output.print_md("\n### Creating Worksets")
        output.print_md("---")
        
        # Create worksets
        with revit.Transaction("Create Worksets"):
            for workset_name in self.selected_worksets:
                try:
                    Workset.Create(self.doc, workset_name)
                    success_count += 1
                    output.print_md("✓ Created: **{}**".format(workset_name))
                except Exception as e:
                    error_count += 1
                    output.print_md("✗ Failed: **{}** - {}".format(workset_name, str(e)))
        
        # Summary
        summary_msg = "Workset creation complete!\n\n"
        summary_msg += "✓ Success: {}\n".format(success_count)
        if error_count > 0:
            summary_msg += "✗ Errors: {}\n".format(error_count)
        summary_msg += "\nCheck output window for details."
        
        forms.alert(summary_msg, title="Complete")
        
        output.print_md("\n### ✅ Workset Creation Complete")
        output.print_md("**Success**: {}".format(success_count))
        output.print_md("**Errors**: {}".format(error_count))
        
        self.result = True
        self._window.Close()
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "WorksetCreator.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = WorksetCreatorWindow(xaml_path, available_worksets, len(existing_worksets), doc, existing_worksets)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Worksets Created Successfully")
else:
    output.print_md("### Operation Cancelled")
