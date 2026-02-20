# -*- coding: utf-8 -*-
"""
Params2Param - WPF Modern UI
Copy values from multiple source parameters to a target parameter
"""
__title__ = 'Params\nTo Param'
__doc__ = 'Copy values from source parameters to target parameter'

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
from System.Windows import Window, Visibility
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection

doc = revit.doc
output = script.get_output()


# ==============================================================================
# DATA CLASSES
# ==============================================================================

class CategoryItem(System.ComponentModel.INotifyPropertyChanged):
    """Observable category item"""
    
    def __init__(self, name, built_in_category):
        self._name = name
        self._built_in_category = built_in_category
        self._property_changed = None
    
    @property
    def Name(self):
        return self._name
    
    @property
    def BuiltInCategory(self):
        return self._built_in_category
    
    def add_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Combine(self._property_changed, handler)
    
    def remove_PropertyChanged(self, handler):
        self._property_changed = System.Delegate.Remove(self._property_changed, handler)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_category_mapping():
    """Create a sorted mapping of category names to built-in categories"""
    categories = {}
    for cat in doc.Settings.Categories:
        try:
            if cat.AllowsBoundParameters:
                categories[cat.Name] = cat.CategoryType
        except:
            pass
    return categories


def get_elements_by_category(category_name):
    """Get all elements of the specified category"""
    elements = []
    
    # Find the category
    for cat in doc.Settings.Categories:
        if cat.Name == category_name:
            try:
                elements = list(
                    FilteredElementCollector(doc)
                    .OfCategoryId(cat.Id)
                    .WhereElementIsNotElementType()
                    .ToElements()
                )
                break
            except:
                pass
    
    return elements


def get_parameter_names(element):
    """Extract parameter names from an element"""
    param_names = []
    for param in element.Parameters:
        try:
            param_names.append(param.Definition.Name)
        except:
            pass
    return sorted(set(param_names))


def get_parameter_value(element, parameter_name):
    """Safely get parameter value as string"""
    try:
        param = element.LookupParameter(parameter_name)
        if param:
            if param.HasValue:
                value = param.AsValueString()
                if value:
                    return value
                # If AsValueString() returns None, try AsString()
                if param.StorageType == StorageType.String:
                    value = param.AsString()
                    if value:
                        return value
        return ""
    except:
        return ""


def create_parameter_value(element, parameter_names, separator, space_option):
    """Create combined parameter value from multiple parameters"""
    if not parameter_names:
        return ""
    
    values = []
    for param_name in parameter_names:
        value = get_parameter_value(element, param_name)
        if value:
            values.append(value)
    
    if not values:
        return ""
    
    # Handle separator spacing
    if space_option == "none":
        sep = separator
    elif space_option == "before":
        sep = " " + separator
    elif space_option == "after":
        sep = separator + " "
    else:  # both
        sep = " " + separator + " "
    
    return sep.join(values)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class Params2ParamWindow(Window):
    def __init__(self, xaml_path, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.doc = document
        self.category_items = ObservableCollection[CategoryItem]()
        self.source_params = ObservableCollection[str]()
        self.target_params = ObservableCollection[str]()
        self.elements = []
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.cmbCategory = self._window.FindName("cmbCategory")
        self.lstSourceParams = self._window.FindName("lstSourceParams")
        self.lstTargetParam = self._window.FindName("lstTargetParam")
        self.txtSeparator = self._window.FindName("txtSeparator")
        self.rbSpaceNone = self._window.FindName("rbSpaceNone")
        self.rbSpaceBefore = self._window.FindName("rbSpaceBefore")
        self.rbSpaceAfter = self._window.FindName("rbSpaceAfter")
        self.rbSpaceBoth = self._window.FindName("rbSpaceBoth")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnExecute = self._window.FindName("btnExecute")
        self.headerDragArea = self._window.FindName("headerDragArea")
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize categories"""
        # Get all categories
        categories = []
        for cat in doc.Settings.Categories:
            try:
                if cat.AllowsBoundParameters:
                    categories.append((cat.Name, cat.CategoryType))
            except:
                pass
        
        # Sort and populate
        for name, cat_type in sorted(categories):
            self.category_items.Add(CategoryItem(name, cat_type))
        
        self.cmbCategory.ItemsSource = self.category_items
        self.lstSourceParams.ItemsSource = self.source_params
        self.lstTargetParam.ItemsSource = self.target_params
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbCategory.SelectionChanged += self.OnCategoryChanged
        self.btnCancel.Click += self.OnCancel
        self.btnExecute.Click += self.OnExecute
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag
    
    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnCancel(self, sender, args):
        """Cancel and close"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnCategoryChanged(self, sender, args):
        """When category changes"""
        if self.cmbCategory.SelectedItem is None:
            return
        
        selected_category = self.cmbCategory.SelectedItem.Name
        
        # Get elements
        self.elements = get_elements_by_category(selected_category)
        
        if not self.elements:
            self.txtStatus.Text = "No elements found in this category"
            self.source_params.Clear()
            self.target_params.Clear()
            return
        
        self.txtStatus.Text = "{} elements found - Select parameters".format(len(self.elements))
        
        # Get all parameter names
        all_param_names = set()
        writable_param_names = set()
        
        # Sample first 10 elements to get parameters
        for elem in self.elements[:min(10, len(self.elements))]:
            for param in elem.Parameters:
                try:
                    param_name = param.Definition.Name
                    all_param_names.add(param_name)
                    
                    # Check if writable string parameter
                    if (param.StorageType == StorageType.String and 
                        not param.IsReadOnly):
                        writable_param_names.add(param_name)
                except:
                    pass
        
        # Populate source parameters (all parameters)
        self.source_params.Clear()
        for param_name in sorted(all_param_names):
            self.source_params.Add(param_name)
        
        # Populate target parameters (only writable string parameters)
        self.target_params.Clear()
        for param_name in sorted(writable_param_names):
            self.target_params.Add(param_name)
        
        output.print_md("**Category**: {}".format(selected_category))
        output.print_md("**Elements**: {}".format(len(self.elements)))
        output.print_md("**Source Parameters**: {}".format(len(self.source_params)))
        output.print_md("**Target Parameters**: {}".format(len(self.target_params)))
    
    def OnExecute(self, sender, args):
        """Execute parameter copying"""
        # Validate selections
        if self.cmbCategory.SelectedItem is None:
            forms.alert("Please select a category", title="Validation Error")
            return
        
        if not self.elements:
            forms.alert("No elements found for selected category", title="Validation Error")
            return
        
        # Get selected source parameters
        selected_sources = []
        for item in self.lstSourceParams.SelectedItems:
            selected_sources.append(str(item))
        
        if not selected_sources:
            forms.alert("Please select at least one source parameter", title="Validation Error")
            return
        
        # Get selected target parameter
        if self.lstTargetParam.SelectedItem is None:
            forms.alert("Please select a target parameter", title="Validation Error")
            return
        
        target_param = str(self.lstTargetParam.SelectedItem)
        
        # Get separator
        separator = self.txtSeparator.Text if self.txtSeparator.Text else "-"
        
        # Get spacing option
        space_option = "both"
        if self.rbSpaceNone.IsChecked:
            space_option = "none"
        elif self.rbSpaceBefore.IsChecked:
            space_option = "before"
        elif self.rbSpaceAfter.IsChecked:
            space_option = "after"
        elif self.rbSpaceBoth.IsChecked:
            space_option = "both"
        
        # Confirm
        confirm_msg = "Copy values from:\n"
        for src in selected_sources:
            confirm_msg += "  • {}\n".format(src)
        confirm_msg += "\nTo: {}\n\n".format(target_param)
        confirm_msg += "For {} elements?".format(len(self.elements))
        
        if not forms.alert(confirm_msg, yes=True, no=True, title="Confirm"):
            return
        
        # Execute
        self.btnExecute.IsEnabled = False
        self.btnExecute.Content = "COPYING..."
        self.txtStatus.Text = "Copying parameter values..."
        
        success = 0
        errors = 0
        
        with revit.Transaction("Copy Parameter Values"):
            for elem in self.elements:
                try:
                    # Get target parameter
                    target = elem.LookupParameter(target_param)
                    if not target or target.IsReadOnly:
                        errors += 1
                        continue
                    
                    # Create combined value
                    combined_value = create_parameter_value(
                        elem, selected_sources, separator, space_option
                    )
                    
                    # Set value
                    if target.StorageType == StorageType.String:
                        target.Set(combined_value)
                        success += 1
                        output.print_md("✓ ID: {} → {}".format(elem.Id, combined_value[:50]))
                    else:
                        errors += 1
                        output.print_md("✗ ID: {} - Not a string parameter".format(elem.Id))
                except Exception as e:
                    errors += 1
                    output.print_md("✗ ID: {} - {}".format(elem.Id, str(e)))
        
        # Summary
        summary = "Parameter copy complete!\n\n"
        summary += "Success: {}\n".format(success)
        summary += "Errors: {}\n\n".format(errors)
        summary += "Source: {}\n".format(", ".join(selected_sources))
        summary += "Target: {}".format(target_param)
        
        forms.alert(summary, title="Complete")
        
        output.print_md("### ✅ Parameter Copy Complete")
        output.print_md("**Success**: {}".format(success))
        output.print_md("**Errors**: {}".format(errors))
        
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
xaml_path = os.path.join(script_dir, "Params2Param.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = Params2ParamWindow(xaml_path, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Parameters Copied Successfully")
else:
    output.print_md("### Operation Cancelled or Closed")
