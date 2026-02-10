# -*- coding: utf-8 -*-
"""
View Title on Sheet Renamer - WPF Modern UI
Rename view titles on sheets with find/replace, prefix & suffix
"""
__title__ = 'Rename View\nTitles'
__doc__ = 'Rename viewport titles on sheets with modern interface'

import clr
import os
import re
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

class ViewportItem(System.ComponentModel.INotifyPropertyChanged):
    """Observable viewport item for binding"""
    
    def __init__(self, vp_data):
        self._vp_data = vp_data
        self._display_text = "{} | {} | {}".format(
            vp_data['sheet_number'],
            vp_data['view_name'],
            vp_data['title'] or "(No Title)"
        )
        self._is_selected = False
        self._property_changed = None
    
    @property
    def ViewportData(self):
        return self._vp_data
    
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

def get_all_viewports():
    """Get all viewports in the project"""
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    viewport_data = []
    
    for sheet in sheets:
        viewport_ids = sheet.GetAllViewports()
        
        for vp_id in viewport_ids:
            vp = doc.GetElement(vp_id)
            view = doc.GetElement(vp.ViewId)
            
            if view:
                title_param = vp.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
                title = title_param.AsString() if title_param else ""
                
                viewport_data.append({
                    'viewport': vp,
                    'view': view,
                    'sheet': sheet,
                    'sheet_number': sheet.SheetNumber,
                    'sheet_name': sheet.Name,
                    'view_name': view.Name,
                    'title': title or ""
                })
    
    # Sort by sheet number
    viewport_data_sorted = sorted(viewport_data, key=lambda x: x['sheet_number'])
    
    return viewport_data_sorted


# Collect viewport data
all_viewports = get_all_viewports()

if not all_viewports:
    forms.alert('No views found on sheets', exitscript=True)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class ViewTitleRenamerWindow(Window):
    def __init__(self, xaml_path, viewport_data, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.all_viewport_data = viewport_data
        self.viewport_items = ObservableCollection[ViewportItem]()
        self.filtered_viewport_items = ObservableCollection[ViewportItem]()
        self.doc = document
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.txtViewFilter = self._window.FindName("txtViewFilter")
        self.btnSelectAllViews = self._window.FindName("btnSelectAllViews")
        self.btnClearAllViews = self._window.FindName("btnClearAllViews")
        self.btnSelectFiltered = self._window.FindName("btnSelectFiltered")
        self.txtViewCount = self._window.FindName("txtViewCount")
        self.lstViews = self._window.FindName("lstViews")
        
        self.txtFind = self._window.FindName("txtFind")
        self.txtReplace = self._window.FindName("txtReplace")
        self.chkUseViewName = self._window.FindName("chkUseViewName")
        self.chkAddSheetNumber = self._window.FindName("chkAddSheetNumber")
        self.txtPrefix = self._window.FindName("txtPrefix")
        self.txtSuffix = self._window.FindName("txtSuffix")
        self.chkCaseSensitive = self._window.FindName("chkCaseSensitive")
        
        self.txtPreview = self._window.FindName("txtPreview")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnApplyRename = self._window.FindName("btnApplyRename")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize viewport items"""
        for vp_data in self.all_viewport_data:
            vp_item = ViewportItem(vp_data)
            vp_item.PropertyChanged += self.OnViewportSelectionChanged
            self.viewport_items.Add(vp_item)
            self.filtered_viewport_items.Add(vp_item)
        
        self.lstViews.ItemsSource = self.filtered_viewport_items
        self.UpdateViewCount()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.txtViewFilter.TextChanged += self.OnFilterChanged
        self.btnSelectAllViews.Click += self.OnSelectAllViews
        self.btnClearAllViews.Click += self.OnClearAllViews
        self.btnSelectFiltered.Click += self.OnSelectFiltered
        
        # Options changed
        self.txtFind.TextChanged += self.OnOptionsChanged
        self.txtReplace.TextChanged += self.OnOptionsChanged
        self.chkUseViewName.Checked += self.OnOptionsChanged
        self.chkUseViewName.Unchecked += self.OnOptionsChanged
        self.chkAddSheetNumber.Checked += self.OnOptionsChanged
        self.chkAddSheetNumber.Unchecked += self.OnOptionsChanged
        self.txtPrefix.TextChanged += self.OnOptionsChanged
        self.txtSuffix.TextChanged += self.OnOptionsChanged
        self.chkCaseSensitive.Checked += self.OnOptionsChanged
        self.chkCaseSensitive.Unchecked += self.OnOptionsChanged
        
        self.btnApplyRename.Click += self.OnApplyRename
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnFilterChanged(self, sender, args):
        """Filter viewports based on text input"""
        filter_text = self.txtViewFilter.Text.lower()
        
        self.filtered_viewport_items.Clear()
        
        for item in self.viewport_items:
            vp_data = item.ViewportData
            search_text = "{} {} {}".format(
                vp_data['sheet_number'],
                vp_data['view_name'],
                vp_data['title']
            ).lower()
            
            if not filter_text or filter_text in search_text:
                self.filtered_viewport_items.Add(item)
        
        self.UpdateViewCount()
    
    def OnSelectAllViews(self, sender, args):
        """Select all visible views"""
        for item in self.filtered_viewport_items:
            item.IsSelected = True
        self.UpdateViewCount()
        self.UpdatePreview()
    
    def OnClearAllViews(self, sender, args):
        """Clear all view selections"""
        for item in self.viewport_items:
            item.IsSelected = False
        self.UpdateViewCount()
        self.UpdatePreview()
    
    def OnSelectFiltered(self, sender, args):
        """Select all filtered views"""
        for item in self.filtered_viewport_items:
            item.IsSelected = True
        self.UpdateViewCount()
        self.UpdatePreview()
    
    def OnViewportSelectionChanged(self, sender, args):
        """When viewport selection changes"""
        self.UpdateViewCount()
        self.UpdatePreview()
    
    def OnOptionsChanged(self, sender, args):
        """When any option changes"""
        self.UpdatePreview()
    
    def UpdateViewCount(self):
        """Update view count label"""
        selected_count = sum(1 for item in self.viewport_items if item.IsSelected)
        total_count = len(self.filtered_viewport_items)
        self.txtViewCount.Text = "Selected: {} / {}".format(selected_count, total_count)
    
    def GenerateNewTitle(self, vp_data):
        """Generate new title based on current settings"""
        # Base title
        if self.chkUseViewName.IsChecked:
            base_title = vp_data['view_name']
        else:
            base_title = vp_data['title']
        
        # Find and replace
        find_text = self.txtFind.Text
        if find_text:
            replace_text = self.txtReplace.Text
            if self.chkCaseSensitive.IsChecked:
                base_title = base_title.replace(find_text, replace_text)
            else:
                base_title = re.sub(re.escape(find_text), replace_text, base_title, flags=re.IGNORECASE)
        
        # Add sheet number suffix
        if self.chkAddSheetNumber.IsChecked:
            base_title = base_title + " - " + vp_data['sheet_number']
        
        # Add custom prefix
        custom_prefix = self.txtPrefix.Text
        if custom_prefix:
            base_title = custom_prefix + base_title
        
        # Add custom suffix
        custom_suffix = self.txtSuffix.Text
        if custom_suffix:
            base_title = base_title + custom_suffix
        
        return base_title
    
    def UpdatePreview(self):
        """Update preview with sample renames"""
        selected_items = [item for item in self.viewport_items if item.IsSelected]
        
        if not selected_items:
            self.txtPreview.Text = "Select views to see preview..."
            return
        
        # Get sample (first 3 selected items)
        samples = []
        for i, item in enumerate(selected_items[:3]):
            vp_data = item.ViewportData
            old_title = vp_data['title'] or "(No Title)"
            new_title = self.GenerateNewTitle(vp_data)
            
            samples.append("{}\n  → {}".format(old_title, new_title))
        
        preview_text = "Preview ({} views):\n\n".format(len(selected_items))
        preview_text += "\n\n".join(samples)
        
        if len(selected_items) > 3:
            preview_text += "\n\n... and {} more".format(len(selected_items) - 3)
        
        self.txtPreview.Text = preview_text
    
    def OnApplyRename(self, sender, args):
        """Apply rename to selected viewports"""
        selected_items = [item for item in self.viewport_items if item.IsSelected]
        
        if not selected_items:
            forms.alert("Please select at least one view", title="Validation Error")
            return
        
        # Confirm
        confirm_msg = "Rename {} view title(s)?\n\nContinue?".format(len(selected_items))
        
        if not forms.alert(confirm_msg, yes=True, no=True):
            return
        
        # Update UI
        self.btnApplyRename.IsEnabled = False
        self.btnApplyRename.Content = "RENAMING..."
        self.txtStatus.Text = "Renaming view titles..."
        
        success_count = 0
        error_count = 0
        
        with revit.Transaction("Rename View Titles on Sheets"):
            for item in selected_items:
                try:
                    vp_data = item.ViewportData
                    viewport = vp_data['viewport']
                    old_title = vp_data['title']
                    new_title = self.GenerateNewTitle(vp_data)
                    
                    # Set new title
                    title_param = viewport.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
                    if title_param and not title_param.IsReadOnly:
                        title_param.Set(new_title)
                        success_count += 1
                        output.print_md("✓ {} | {} → {}".format(
                            vp_data['sheet_number'],
                            old_title or "(No Title)",
                            new_title
                        ))
                    else:
                        error_count += 1
                        output.print_md("✗ {} | {} - Parameter read-only".format(
                            vp_data['sheet_number'],
                            vp_data['view_name']
                        ))
                
                except Exception as e:
                    error_count += 1
                    output.print_md("✗ {} | {} - {}".format(
                        vp_data['sheet_number'],
                        vp_data['view_name'],
                        str(e)
                    ))
        
        # Summary
        msg = "View title rename complete!\n\n"
        msg += "Success: {}\n".format(success_count)
        msg += "Errors: {}".format(error_count)
        
        forms.alert(msg, title="Complete")
        
        self.result = True
        self.btnApplyRename.IsEnabled = True
        self.btnApplyRename.Content = "APPLY RENAME"
        self.txtStatus.Text = "Rename complete! Success: {}, Errors: {}".format(
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
xaml_path = os.path.join(script_dir, "ViewTitleRenamer.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = ViewTitleRenamerWindow(xaml_path, all_viewports, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ View Titles Renamed Successfully")
else:
    output.print_md("### Operation Cancelled or Closed")
