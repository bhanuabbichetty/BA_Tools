# -*- coding: utf-8 -*-
"""
Export NWC Files - WPF Modern UI
"""
__title__ = 'Export\nNWC'
__doc__ = 'Export Navisworks Cache files with modern UI'

import clr
import os
import time
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
from System.Windows.Forms import FolderBrowserDialog, DialogResult

doc = revit.doc
output = script.get_output()


# ==============================================================================
# COLLECT DATA
# ==============================================================================

def get_3d_views():
    """Get all valid 3D views in the project"""
    all_views = FilteredElementCollector(doc)\
        .OfClass(View3D)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    valid_3d_views = [view for view in all_views if not view.IsTemplate]
    
    return sorted(valid_3d_views, key=lambda v: v.Name)


# Collect data
valid_3d_views = get_3d_views()

if not valid_3d_views:
    forms.alert('No 3D views found in the project', exitscript=True)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class NWCExporterWindow(Window):
    def __init__(self, xaml_path, views, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.views = views
        self.view_dict = {view.Name: view for view in views}
        self.doc = document
        self.export_path = "C:\\Projects\\BIM\\Exports\\NWC"
        self.file_name = doc.Title or "Untitled"
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.cmbSourceView = self._window.FindName("cmbSourceView")
        self.txtOutputPath = self._window.FindName("txtOutputPath")
        self.btnBrowse = self._window.FindName("btnBrowse")
        self.txtFilename = self._window.FindName("txtFilename")
        self.chkUseProjectName = self._window.FindName("chkUseProjectName")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Export options
        self.chkExportLinks = self._window.FindName("chkExportLinks")
        self.chkExportRoomGeometry = self._window.FindName("chkExportRoomGeometry")
        self.chkExportRoomAsAttribute = self._window.FindName("chkExportRoomAsAttribute")
        self.chkConvertElementProperties = self._window.FindName("chkConvertElementProperties")
        self.chkExportUrls = self._window.FindName("chkExportUrls")
        self.chkConvertLights = self._window.FindName("chkConvertLights")
        
        # Log and status
        self.txtLog = self._window.FindName("txtLog")
        self.txtStatus = self._window.FindName("txtStatus")
        self.txtFileInfo = self._window.FindName("txtFileInfo")
        self.btnExport = self._window.FindName("btnExport")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def InitializeData(self):
        """Initialize controls with data"""
        # Source view combo
        self.cmbSourceView.Items.Add("-- Select 3D View --")
        for view in self.views:
            self.cmbSourceView.Items.Add(view.Name)
        self.cmbSourceView.SelectedIndex = 0
        
        # Output path
        self.txtOutputPath.Text = self.export_path
        
        # Filename
        self.txtFilename.Text = self.file_name
        self.UpdateFileInfo()
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbSourceView.SelectionChanged += self.OnViewChanged
        self.btnBrowse.Click += self.OnBrowse
        self.txtFilename.TextChanged += self.OnFilenameChanged
        self.chkUseProjectName.Checked += self.OnUseProjectNameChanged
        self.chkUseProjectName.Unchecked += self.OnUseProjectNameChanged
        self.btnExport.Click += self.OnExport
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnViewChanged(self, sender, args):
        """When source view is changed"""
        if self.cmbSourceView.SelectedIndex > 0:
            view_name = self.cmbSourceView.SelectedItem.ToString()
            self.AddLog("Selected view: {}".format(view_name))
            self.UpdateFileInfo()
    
    def OnBrowse(self, sender, args):
        """Browse for output folder"""
        dialog = FolderBrowserDialog()
        dialog.Description = "Select Export Folder"
        dialog.SelectedPath = self.export_path
        
        if dialog.ShowDialog() == DialogResult.OK:
            self.export_path = dialog.SelectedPath
            self.txtOutputPath.Text = self.export_path
            self.AddLog("Export path updated: {}".format(self.export_path))
            self.UpdateFileInfo()
    
    def OnFilenameChanged(self, sender, args):
        """When filename is changed"""
        self.UpdateFileInfo()
    
    def OnUseProjectNameChanged(self, sender, args):
        """When Use Project Name checkbox is changed"""
        if self.chkUseProjectName.IsChecked:
            self.txtFilename.Text = self.file_name
            self.txtFilename.IsReadOnly = True
            self.txtFilename.Background = System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromArgb(255, 25, 25, 30)
            )
        else:
            self.txtFilename.IsReadOnly = False
            self.txtFilename.Background = System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromArgb(255, 10, 10, 15)
            )
        self.UpdateFileInfo()
    
    def UpdateFileInfo(self):
        """Update file info in footer"""
        file_name = self.txtFilename.Text.strip()
        if file_name and self.cmbSourceView.SelectedIndex > 0:
            full_path = os.path.join(self.export_path, file_name + ".nwc")
            self.txtFileInfo.Text = full_path
        else:
            self.txtFileInfo.Text = "No file selected"
    
    def AddLog(self, message):
        """Add log message"""
        timestamp = System.DateTime.Now.ToString("HH:mm:ss")
        log_line = "[{}] {}\n".format(timestamp, message)
        self.txtLog.AppendText(log_line)
        self.txtLog.ScrollToEnd()
    
    def OnExport(self, sender, args):
        """Export NWC file"""
        # Validate
        if self.cmbSourceView.SelectedIndex == 0:
            forms.alert("Please select a 3D view", title="Validation Error")
            return
        
        selected_view_name = self.cmbSourceView.SelectedItem.ToString()
        selected_view = self.view_dict[selected_view_name]
        
        file_name = self.txtFilename.Text.strip()
        if not file_name:
            forms.alert("Please enter a file name", title="Validation Error")
            return
        
        # Remove invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            file_name = file_name.replace(char, '_')
        
        nwc_file_path = os.path.join(self.export_path, file_name + '.nwc')
        
        # Check if directory exists
        if not os.path.exists(self.export_path):
            try:
                os.makedirs(self.export_path)
                self.AddLog("Created export directory: {}".format(self.export_path))
            except Exception as e:
                forms.alert("Failed to create export directory:\n\n{}".format(str(e)), 
                          title="Export Error")
                return
        
        # Update UI
        self.btnExport.IsEnabled = False
        self.btnExport.Content = "EXPORTING..."
        self.txtStatus.Text = "BUSY"
        self.txtStatus.Foreground = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromArgb(255, 74, 222, 128)
        )
        
        self.AddLog("Starting export process...")
        self.AddLog("View: {}".format(selected_view_name))
        self.AddLog("Output: {}".format(nwc_file_path))
        self.AddLog("Export directory exists: {}".format(os.path.exists(self.export_path)))
        
        try:
            # Configure NWC export options
            nwc_options = NavisworksExportOptions()
            nwc_options.ExportScope = NavisworksExportScope.View
            nwc_options.ViewId = selected_view.Id
            nwc_options.ExportLinks = self.chkExportLinks.IsChecked
            nwc_options.ExportRoomAsAttribute = self.chkExportRoomAsAttribute.IsChecked
            nwc_options.ExportRoomGeometry = self.chkExportRoomGeometry.IsChecked
            nwc_options.ConvertElementProperties = self.chkConvertElementProperties.IsChecked
            nwc_options.Coordinates = NavisworksCoordinates.Shared
            nwc_options.FacetingFactor = 1.0
            nwc_options.ExportUrls = self.chkExportUrls.IsChecked
            nwc_options.ConvertLights = self.chkConvertLights.IsChecked
            
            self.AddLog("Configuring export settings...")
            self.AddLog("  Export scope: Selected View")
            self.AddLog("  Coordinates: Shared")
            self.AddLog("  Export links: {}".format(self.chkExportLinks.IsChecked))
            self.AddLog("  Room geometry: {}".format(self.chkExportRoomGeometry.IsChecked))
            
            # Perform export
            self.AddLog("Processing geometry...")
            
            # Export returns True/False, but sometimes it completes without returning True
            # We need to check if file was actually created
            try:
                result = self.doc.Export(self.export_path, file_name + '.nwc', nwc_options)
                self.AddLog("Export command completed")
            except Exception as export_ex:
                self.AddLog("Export command exception: {}".format(str(export_ex)))
                raise
            
            # Wait a moment for file to be written
            time.sleep(0.5)
            
            # Check if file exists (this is the real success indicator)
            if os.path.exists(nwc_file_path):
                file_size = os.path.getsize(nwc_file_path)
                file_size_mb = file_size / (1024.0 * 1024.0)
                
                self.AddLog("SUCCESS: Export completed!")
                self.AddLog("File created: {}".format(nwc_file_path))
                self.AddLog("File size: {:.2f} MB".format(file_size_mb))
                
                output.print_md("### ✅ Export Completed Successfully")
                output.print_md("**File**: {}.nwc".format(file_name))
                output.print_md("**Location**: {}".format(self.export_path))
                output.print_md("**Size**: {:.2f} MB".format(file_size_mb))
                
                forms.alert(
                    "NWC file exported successfully!\n\n"
                    "File: {}.nwc\n"
                    "Location: {}\n"
                    "Size: {:.2f} MB".format(file_name, self.export_path, file_size_mb),
                    title="Export Complete"
                )
                
                self.result = True
                self._window.Close()
            else:
                self.AddLog("ERROR: Export file not found at: {}".format(nwc_file_path))
                self.AddLog("Export result value: {}".format(result))
                forms.alert(
                    "Export may have completed, but file was not found at expected location.\n\n"
                    "Expected: {}\n\n"
                    "Please check the export directory manually.".format(nwc_file_path),
                    title="Export Status Unknown"
                )
        
        except Exception as e:
            self.AddLog("ERROR: {}".format(str(e)))
            forms.alert("Export failed:\n\n{}".format(str(e)), title="Export Error")
        
        finally:
            self.btnExport.IsEnabled = True
            self.btnExport.Content = "EXPORT NWC FILE"
            self.txtStatus.Text = "IDLE"
            self.txtStatus.Foreground = System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromArgb(255, 128, 128, 144)
            )
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "NWCExporter.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = NWCExporterWindow(xaml_path, valid_3d_views, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Export Completed Successfully")
else:
    output.print_md("### Export Cancelled or Failed")