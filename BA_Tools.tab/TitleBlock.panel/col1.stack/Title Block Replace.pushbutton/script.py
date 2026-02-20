# -*- coding: utf-8 -*-
"""
Title Block Replacer - WPF Modern UI
Replace title blocks on selected sheets with modern interface
"""
__title__ = 'Replace'
__doc__ = 'Replace title blocks on selected sheets'

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
    """Observable sheet item for binding"""
    
    def __init__(self, sheet, display_text):
        self._sheet = sheet
        self._display_text = display_text
        self._is_selected = False
        
        # Event for property changes
        self._property_changed = None
    
    @property
    def Sheet(self):
        return self._sheet
    
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

def get_all_titleblock_types():
    """Get all title block family types in the project"""
    titleblock_types = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_TitleBlocks)\
        .WhereElementIsElementType()\
        .ToElements()
    
    # Group by family name
    titleblock_dict = {}
    for tb_type in titleblock_types:
        family_name = tb_type.FamilyName
        type_name = Element.Name.GetValue(tb_type)
        
        if family_name not in titleblock_dict:
            titleblock_dict[family_name] = []
        
        titleblock_dict[family_name].append({
            'type': tb_type,
            'name': type_name,
            'family': family_name
        })
    
    return titleblock_dict


def get_all_sheets():
    """Get all sheets in the project"""
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    # Sort by sheet number
    sheets_sorted = sorted(sheets, key=lambda s: s.SheetNumber)
    
    return sheets_sorted


def get_sheet_titleblock(sheet):
    """Get the title block instance on a sheet"""
    titleblocks = FilteredElementCollector(doc, sheet.Id)\
        .OfCategory(BuiltInCategory.OST_TitleBlocks)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    if titleblocks:
        return titleblocks[0]
    return None


# Collect data
titleblock_families = get_all_titleblock_types()
all_sheets = get_all_sheets()

if not titleblock_families:
    forms.alert('No title block families found in the project', exitscript=True)

if not all_sheets:
    forms.alert('No sheets found in the project', exitscript=True)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class TitleBlockReplacerWindow(Window):
    def __init__(self, xaml_path, titleblocks, sheets, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.titleblocks = titleblocks
        self.all_sheets = sheets
        self.doc = document
        self.sheet_items = ObservableCollection[SheetItem]()
        self.filtered_sheet_items = ObservableCollection[SheetItem]()
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.cmbFamily = self._window.FindName("cmbFamily")
        self.cmbType = self._window.FindName("cmbType")
        self.rbAll = self._window.FindName("rbAll")           # may be None - not in current XAML
        self.rbUnissued = self._window.FindName("rbUnissued")  # may be None - not in current XAML
        self.txtCurrentTitleBlocks = self._window.FindName("txtCurrentTitleBlocks")  # may be None
        self.txtSheetFilter = self._window.FindName("txtSheetFilter")
        self.btnSelectAllSheets = self._window.FindName("btnSelectAllSheets")
        self.btnClearAllSheets = self._window.FindName("btnClearAllSheets")
        self.btnSelectFiltered = self._window.FindName("btnSelectFiltered")
        self.txtSheetCount = self._window.FindName("txtSheetCount")
        self.lstSheets = self._window.FindName("lstSheets")
        self.txtLog = self._window.FindName("txtLog")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnViewReport = self._window.FindName("btnViewReport")
        self.btnReplace = self._window.FindName("btnReplace")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize combo boxes and sheet list"""
        # Family combo
        self.cmbFamily.Items.Add("-- Select Title Block Family --")
        for family_name in sorted(self.titleblocks.keys()):
            self.cmbFamily.Items.Add(family_name)
        self.cmbFamily.SelectedIndex = 0
        
        # Type combo
        self.cmbType.Items.Add("-- Select Type --")
        self.cmbType.SelectedIndex = 0
        self.cmbType.IsEnabled = False
        
        # Sheet items
        for sheet in self.all_sheets:
            display_text = "{} - {}".format(sheet.SheetNumber, sheet.Name)
            sheet_item = SheetItem(sheet, display_text)
            sheet_item.PropertyChanged += self.OnSheetSelectionChanged
            self.sheet_items.Add(sheet_item)
            self.filtered_sheet_items.Add(sheet_item)
        
        self.lstSheets.ItemsSource = self.filtered_sheet_items
        self.UpdateSheetCount()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbFamily.SelectionChanged += self.OnFamilyChanged
        self.txtSheetFilter.TextChanged += self.OnFilterChanged
        self.btnSelectAllSheets.Click += self.OnSelectAllSheets
        self.btnClearAllSheets.Click += self.OnClearAllSheets
        self.btnSelectFiltered.Click += self.OnSelectFiltered
        self.btnViewReport.Click += self.OnViewReport
        self.btnReplace.Click += self.OnReplace
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnFamilyChanged(self, sender, args):
        """When family is selected, populate type dropdown"""
        self.cmbType.Items.Clear()
        self.cmbType.Items.Add("-- Select Type --")
        
        if self.cmbFamily.SelectedIndex > 0:
            family_name = self.cmbFamily.SelectedItem.ToString()
            types = self.titleblocks[family_name]
            
            for tb_type in types:
                self.cmbType.Items.Add(tb_type['name'])
            
            self.cmbType.IsEnabled = True
            if len(types) == 1:
                self.cmbType.SelectedIndex = 1
            else:
                self.cmbType.SelectedIndex = 0
        else:
            self.cmbType.IsEnabled = False
            self.cmbType.SelectedIndex = 0
    
    def OnFilterChanged(self, sender, args):
        """Filter sheets based on text input"""
        filter_text = self.txtSheetFilter.Text.lower()
        
        self.filtered_sheet_items.Clear()
        
        for item in self.sheet_items:
            if not filter_text or filter_text in item.DisplayText.lower():
                self.filtered_sheet_items.Add(item)
        
        self.UpdateSheetCount()
    
    def OnSelectAllSheets(self, sender, args):
        """Select all visible sheets"""
        for item in self.filtered_sheet_items:
            item.IsSelected = True
        self.UpdateSheetCount()
        self.UpdateCurrentTitleBlocks()
    
    def OnClearAllSheets(self, sender, args):
        """Clear all sheet selections"""
        for item in self.sheet_items:
            item.IsSelected = False
        self.UpdateSheetCount()
        self.UpdateCurrentTitleBlocks()
    
    def OnSelectFiltered(self, sender, args):
        """Select all filtered sheets"""
        for item in self.filtered_sheet_items:
            item.IsSelected = True
        self.UpdateSheetCount()
        self.UpdateCurrentTitleBlocks()
    
    def OnSheetSelectionChanged(self, sender, args):
        """When sheet selection changes"""
        try:
            self.UpdateSheetCount()
            self.UpdateCurrentTitleBlocks()
        except Exception:
            pass
    
    def UpdateSheetCount(self):
        """Update sheet count label"""
        selected_count = sum(1 for item in self.sheet_items if item.IsSelected)
        total_count = len(self.filtered_sheet_items)
        self.txtSheetCount.Text = "Selected: {} / {}".format(selected_count, total_count)
    
    def UpdateCurrentTitleBlocks(self):
        """Show current title blocks for selected sheets"""
        # Guard: control doesn't exist in this XAML version
        if not self.txtCurrentTitleBlocks:
            return

        selected_items = [item for item in self.sheet_items if item.IsSelected]
        
        if not selected_items:
            self.txtCurrentTitleBlocks.Text = "Select sheets to see current title blocks..."
            return
        
        # Get current title blocks
        tb_info = {}
        
        for item in selected_items:
            sheet = item.Sheet
            current_tb = get_sheet_titleblock(sheet)
            
            if current_tb:
                tb_type = self.doc.GetElement(current_tb.GetTypeId())
                tb_name = "{} : {}".format(
                    tb_type.FamilyName,
                    Element.Name.GetValue(tb_type)
                )
                
                if tb_name not in tb_info:
                    tb_info[tb_name] = []
                tb_info[tb_name].append(sheet.SheetNumber)
        
        # Display info
        info_text = "Selected {} sheet(s):\n\n".format(len(selected_items))
        for tb_name, sheet_numbers in tb_info.items():
            info_text += "• {}\n".format(tb_name)
            info_text += "  Sheets: {}\n\n".format(", ".join(sheet_numbers[:5]))
            if len(sheet_numbers) > 5:
                info_text += "  ... and {} more\n\n".format(len(sheet_numbers) - 5)
        
        self.txtCurrentTitleBlocks.Text = info_text
    
    def AddLog(self, message):
        """Add log message"""
        timestamp = System.DateTime.Now.ToString("HH:mm:ss")
        log_line = "[{}] {}\n".format(timestamp, message)
        self.txtLog.AppendText(log_line)
        self.txtLog.ScrollToEnd()
    
    def OnViewReport(self, sender, args):
        """View report (placeholder)"""
        forms.alert("Report functionality coming soon", title="View Report")
    
    def OnReplace(self, sender, args):
        """Replace title blocks"""
        # Validate selections
        if self.cmbFamily.SelectedIndex == 0:
            forms.alert("Please select a title block family", title="Validation Error")
            return
        
        if self.cmbType.SelectedIndex == 0:
            forms.alert("Please select a title block type", title="Validation Error")
            return
        
        selected_sheets = [item.Sheet for item in self.sheet_items if item.IsSelected]
        
        if not selected_sheets:
            forms.alert("Please select at least one sheet", title="Validation Error")
            return
        
        # Get selected title block type
        family_name = self.cmbFamily.SelectedItem.ToString()
        type_name = self.cmbType.SelectedItem.ToString()
        
        selected_tb = None
        for tb_data in self.titleblocks[family_name]:
            if tb_data['name'] == type_name:
                selected_tb = tb_data['type']
                break
        
        if not selected_tb:
            forms.alert("Could not find selected title block type", title="Error")
            return
        
        # Confirm
        confirm_msg = "Replace title blocks on {} sheet(s) with:\n\n{} : {}\n\nContinue?".format(
            len(selected_sheets),
            family_name,
            type_name
        )
        
        if not forms.alert(confirm_msg, yes=True, no=True):
            return
        
        # Update UI
        self.btnReplace.IsEnabled = False
        self.btnReplace.Content = "REPLACING..."
        self.txtLog.Clear()
        
        self.AddLog("Starting title block replacement...")
        self.AddLog("Target: {} : {}".format(family_name, type_name))
        self.AddLog("Sheets: {}".format(len(selected_sheets)))
        self.AddLog("")
        
        success_count = 0
        error_count = 0
        
        with revit.Transaction("Replace Title Blocks"):
            # Activate symbol if needed
            if not selected_tb.IsActive:
                selected_tb.Activate()
                self.doc.Regenerate()
                self.AddLog("Activated title block symbol")
            
            for sheet in selected_sheets:
                try:
                    # Get current title block
                    current_tb = get_sheet_titleblock(sheet)
                    
                    if current_tb:
                        # Get current location
                        current_location = current_tb.Location.Point
                        
                        # Delete current title block
                        self.doc.Delete(current_tb.Id)
                        
                        # Create new title block
                        new_tb = self.doc.Create.NewFamilyInstance(
                            current_location,
                            selected_tb,
                            sheet
                        )
                        
                        success_count += 1
                        self.AddLog("✓ {} - {}".format(sheet.SheetNumber, sheet.Name))
                    else:
                        # No existing title block, create new one
                        new_tb = self.doc.Create.NewFamilyInstance(
                            XYZ.Zero,
                            selected_tb,
                            sheet
                        )
                        success_count += 1
                        self.AddLog("✓ {} - {} (new)".format(sheet.SheetNumber, sheet.Name))
                
                except Exception as e:
                    error_count += 1
                    self.AddLog("✗ {} - {}: {}".format(
                        sheet.SheetNumber,
                        sheet.Name,
                        str(e)
                    ))
        
        # Summary
        self.AddLog("")
        self.AddLog("=== COMPLETE ===")
        self.AddLog("Success: {}".format(success_count))
        self.AddLog("Errors: {}".format(error_count))
        
        msg = "Title block replacement complete!\n\n"
        msg += "Success: {}\n".format(success_count)
        msg += "Errors: {}".format(error_count)
        
        forms.alert(msg, title="Complete")
        
        self.result = True
        self.btnReplace.IsEnabled = True
        self.btnReplace.Content = "REPLACE TITLE BLOCKS"
        self.txtStatus.Text = "Replacement complete! Success: {}, Errors: {}".format(
            success_count, error_count
        )
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "TitleBlockReplacer.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = TitleBlockReplacerWindow(xaml_path, titleblock_families, all_sheets, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Title Block Replacement Completed")
else:
    output.print_md("### Operation Cancelled or Closed")
