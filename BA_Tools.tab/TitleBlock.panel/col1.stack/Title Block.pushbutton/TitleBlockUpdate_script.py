# -*- coding: utf-8 -*-
"""
Title Block Batch Update - WPF Modern UI
Select multiple sheets and update title block parameters at once
"""
__title__ = 'Title Block\nUpdate'
__doc__ = 'Batch update title block parameters on multiple sheets'

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
from System.Collections.ObjectModel import ObservableCollection

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()


# ==============================================================================
# DATA CLASSES
# ==============================================================================

class SheetItem(System.ComponentModel.INotifyPropertyChanged):
    """Observable sheet item for checkbox binding"""
    
    def __init__(self, sheet_data):
        self._sheet_data = sheet_data
        self._display_text = "{} - {}".format(
            sheet_data['sheet_number'],
            sheet_data['sheet_name']
        )
        self._is_selected = False
        self._property_changed = None
    
    @property
    def SheetData(self):
        return self._sheet_data
    
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
# COLLECT DATA
# ==============================================================================

def get_all_sheets_with_titleblocks():
    """Get all sheets with their title blocks"""
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    sheet_data = []
    for sheet in sheets:
        titleblocks = FilteredElementCollector(doc, sheet.Id)\
            .OfCategory(BuiltInCategory.OST_TitleBlocks)\
            .WhereElementIsNotElementType()\
            .ToElements()
        
        if titleblocks:
            sheet_data.append({
                'sheet': sheet,
                'titleblock': titleblocks[0],
                'sheet_number': sheet.SheetNumber,
                'sheet_name': sheet.Name
            })
    
    return sorted(sheet_data, key=lambda x: x['sheet_number'])


# Collect data
all_sheets = get_all_sheets_with_titleblocks()

if not all_sheets:
    forms.alert('No sheets with title blocks found', exitscript=True)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class TitleBlockUpdateWindow(Window):
    def __init__(self, xaml_path, sheet_data, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.all_sheet_data = sheet_data
        self.sheet_items = ObservableCollection[SheetItem]()
        self.filtered_sheet_items = ObservableCollection[SheetItem]()
        self.doc = document
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.txtSheetFilter = self._window.FindName("txtSheetFilter")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnClearAll = self._window.FindName("btnClearAll")
        self.txtSheetCount = self._window.FindName("txtSheetCount")
        self.lstSheets = self._window.FindName("lstSheets")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Parameter controls
        self.txtDrawnBy = self._window.FindName("txtDrawnBy")
        self.txtCheckedBy = self._window.FindName("txtCheckedBy")
        self.txtDesignedBy = self._window.FindName("txtDesignedBy")
        self.txtApprovedBy = self._window.FindName("txtApprovedBy")
        self.txtProjectNumber = self._window.FindName("txtProjectNumber")
        self.txtProjectName = self._window.FindName("txtProjectName")
        self.datePicker = self._window.FindName("datePicker")
        self.btnClearFields = self._window.FindName("btnClearFields")
        
        # Action buttons
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnCancel = self._window.FindName("btnCancel")
        self.btnUpdate = self._window.FindName("btnUpdate")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def InitializeData(self):
        """Initialize sheet items"""
        for sheet_data in self.all_sheet_data:
            sheet_item = SheetItem(sheet_data)
            sheet_item.PropertyChanged += self.OnSheetSelectionChanged
            self.sheet_items.Add(sheet_item)
            self.filtered_sheet_items.Add(sheet_item)
        
        self.lstSheets.ItemsSource = self.filtered_sheet_items
        self.UpdateSheetCount()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.txtSheetFilter.TextChanged += self.OnFilterChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnClearAll.Click += self.OnClearAll
        self.btnClearFields.Click += self.OnClearFields
        self.btnCancel.Click += self.OnCancel
        self.btnUpdate.Click += self.OnUpdate
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnCancel(self, sender, args):
        """Cancel and close"""
        self._window.DialogResult = False
        self._window.Close()
    
    def PopulateSheets(self):
        """Populate sheet list with filtered data"""
        filter_text = self.txtSheetFilter.Text.lower() if self.txtSheetFilter.Text else ""
        
        self.filtered_sheet_items.Clear()
        
        for sheet_item in self.sheet_items:
            if not filter_text or filter_text in sheet_item.DisplayText.lower():
                self.filtered_sheet_items.Add(sheet_item)
        
        self.UpdateSheetCount()
    
    def OnFilterChanged(self, sender, args):
        """When filter text changes"""
        self.PopulateSheets()
    
    def OnSelectAll(self, sender, args):
        """Select all visible sheets"""
        for item in self.filtered_sheet_items:
            item.IsSelected = True
        self.UpdateSheetCount()
    
    def OnClearAll(self, sender, args):
        """Clear all selections"""
        for item in self.sheet_items:
            item.IsSelected = False
        self.UpdateSheetCount()
    
    def OnSheetSelectionChanged(self, sender, args):
        """When sheet selection changes"""
        self.UpdateSheetCount()
    
    def UpdateSheetCount(self):
        """Update sheet count label"""
        selected_count = sum(1 for item in self.sheet_items if item.IsSelected)
        total_count = len(self.filtered_sheet_items)
        self.txtSheetCount.Text = "{} / {} selected".format(selected_count, total_count)
    
    def OnClearFields(self, sender, args):
        """Clear all parameter fields"""
        self.txtDrawnBy.Text = ""
        self.txtCheckedBy.Text = ""
        self.txtDesignedBy.Text = ""
        self.txtApprovedBy.Text = ""
        self.txtProjectNumber.Text = ""
        self.txtProjectName.Text = ""
        self.datePicker.SelectedDate = None
    
    def OnUpdate(self, sender, args):
        """Update title blocks on selected sheets"""
        # Get selected sheets
        selected_items = [item for item in self.sheet_items if item.IsSelected]
        
        if not selected_items:
            forms.alert("Please select at least one sheet", title="Validation Error")
            return
        
        selected_sheets = [item.SheetData for item in selected_items]
        
        # Collect parameters to update
        params = {}
        
        if self.txtDrawnBy.Text.strip():
            params['Drawn By'] = self.txtDrawnBy.Text.strip()
        
        if self.txtCheckedBy.Text.strip():
            params['Checked By'] = self.txtCheckedBy.Text.strip()
        
        if self.txtDesignedBy.Text.strip():
            params['Designed By'] = self.txtDesignedBy.Text.strip()
        
        if self.txtApprovedBy.Text.strip():
            params['Approved By'] = self.txtApprovedBy.Text.strip()
        
        if self.txtProjectNumber.Text.strip():
            params['Project Number'] = self.txtProjectNumber.Text.strip()
        
        if self.txtProjectName.Text.strip():
            params['Project Name'] = self.txtProjectName.Text.strip()
        
        if self.datePicker.SelectedDate:
            date_value = self.datePicker.SelectedDate.ToString("dd-MM-yyyy")
            params['Sheet Issue Date'] = date_value
        
        if not params:
            forms.alert("Please fill in at least one parameter", title="Validation Error")
            return
        
        # Confirm
        confirm_msg = "Update {} sheet(s) with {} parameter(s)?\n\nParameters:\n{}".format(
            len(selected_sheets),
            len(params),
            "\n".join("• {}".format(k) for k in params.keys())
        )
        
        if not forms.alert(confirm_msg, yes=True, no=True):
            return
        
        # Update UI
        self.btnUpdate.IsEnabled = False
        self.btnUpdate.Content = "UPDATING..."
        self.txtStatus.Text = "Updating title blocks..."
        
        success_count = 0
        error_count = 0
        
        # Start transaction
        with revit.Transaction("Update Title Blocks"):
            for sheet_data in selected_sheets:
                try:
                    updated_params = []
                    
                    for param_name, param_value in params.items():
                        # Try title block first, then sheet
                        param = sheet_data['titleblock'].LookupParameter(param_name)
                        if not param:
                            param = sheet_data['sheet'].LookupParameter(param_name)
                        
                        if param and not param.IsReadOnly:
                            try:
                                param.Set(param_value)
                                updated_params.append(param_name)
                            except Exception as e:
                                output.print_md("⚠ {} - {}: {}".format(
                                    sheet_data['sheet_number'],
                                    param_name,
                                    str(e)
                                ))
                    
                    if updated_params:
                        success_count += 1
                        output.print_md("✓ {} - {} - Updated: {}".format(
                            sheet_data['sheet_number'],
                            sheet_data['sheet_name'],
                            ", ".join(updated_params)
                        ))
                    else:
                        error_count += 1
                        output.print_md("✗ {} - {} - No parameters updated".format(
                            sheet_data['sheet_number'],
                            sheet_data['sheet_name']
                        ))
                
                except Exception as e:
                    error_count += 1
                    output.print_md("✗ {} - {}: {}".format(
                        sheet_data['sheet_number'],
                        sheet_data['sheet_name'],
                        str(e)
                    ))
        
        # Summary
        summary_msg = "Title block update complete!\n\n"
        summary_msg += "Success: {}\n".format(success_count)
        summary_msg += "Errors: {}\n\n".format(error_count)
        summary_msg += "Check output window for details."
        
        forms.alert(summary_msg, title="Complete")
        
        output.print_md("### ✅ Update Complete")
        output.print_md("**Success**: {}".format(success_count))
        output.print_md("**Errors**: {}".format(error_count))
        
        self.result = True
        
        # Close window after successful update
        self._window.Close()
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "TitleBlockUpdate.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

output.print_md("**Found {} sheets with title blocks**".format(len(all_sheets)))

# Show window
window = TitleBlockUpdateWindow(xaml_path, all_sheets, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Title Blocks Updated Successfully")
else:
    output.print_md("### Operation Cancelled or Closed")