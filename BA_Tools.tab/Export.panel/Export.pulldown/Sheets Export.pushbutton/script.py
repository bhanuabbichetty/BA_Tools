# -*- coding: utf-8 -*-
"""
PDF & DWG Export Manager - WPF Modern UI
Export production and shop drawing sets to PDF and DWG
"""
__title__ = 'Export\nPDF/DWG'
__doc__ = 'Export sheets to PDF and DWG with custom naming and settings'

import clr
import os
import re
import datetime
import locale

clr.AddReference("RevitAPI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms, coreutils, HOST_APP
from pyrevit.framework import Windows, ObjectModel, Forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window, Visibility
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection
from System.Collections.Generic import List
from System.Windows.Forms import FolderBrowserDialog, DialogResult
from collections import namedtuple

doc = revit.doc
output = script.get_output()
config = script.get_config()

# Naming format helper classes
NamingFormatter = namedtuple('NamingFormatter', ['template', 'desc'])


# ==============================================================================
# NAMING FORMAT CLASSES
# ==============================================================================

class NamingFormat(forms.Reactive):
    """File Naming Format"""
    def __init__(self, name, template, builtin=False):
        self._name = name
        self._template = self.verify_template(template)
        self.builtin = builtin

    @staticmethod
    def verify_template(value):
        """Verify template is valid"""
        if not value.lower().endswith('.pdf'):
            value += '.pdf'
        return value

    @forms.reactive
    def name(self):
        """Format name"""
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @forms.reactive
    def template(self):
        """Format template string"""
        return self._template

    @template.setter
    def template(self, value):
        self._template = self.verify_template(value)


class EditNamingFormatsWindow(forms.WPFWindow):
    """Edit Naming Formats Dialog"""
    def __init__(self, xaml_file_name, start_with=None):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self._drop_pos = 0
        self._starting_item = start_with
        self._saved = False
        
        self.reset_naming_formats()
        self.reset_formatters()
    
    @staticmethod
    def get_default_formatters():
        return [
            NamingFormatter(
                template='{index}',
                desc='Print Index Number e.g. "0001"'
            ),
            NamingFormatter(
                template='{number}',
                desc='Sheet Number e.g. "A1.00"'
            ),
            NamingFormatter(
                template='{name}',
                desc='Sheet Name e.g. "1ST FLOOR PLAN"'
            ),
            NamingFormatter(
                template='{name_dash}',
                desc='Sheet Name (with - for space) e.g. "1ST-FLOOR-PLAN"'
            ),
            NamingFormatter(
                template='{name_underline}',
                desc='Sheet Name (with _ for space) e.g. "1ST_FLOOR_PLAN"'
            ),
            NamingFormatter(
                template='{current_date}',
                desc='Today\'s Date e.g. "2019-10-12"'
            ),
            NamingFormatter(
                template='{issue_date}',
                desc='Sheet Issue Date e.g. "2019-10-12"'
            ),
            NamingFormatter(
                template='{rev_number}',
                desc='Revision Number e.g. "01"'
            ),
            NamingFormatter(
                template='{rev_desc}',
                desc='Revision Description e.g. "ASI01"'
            ),
            NamingFormatter(
                template='{rev_date}',
                desc='Revision Date e.g. "2019-10-12"'
            ),
            NamingFormatter(
                template='{proj_name}',
                desc='Project Name e.g. "MY_PROJECT"'
            ),
            NamingFormatter(
                template='{proj_number}',
                desc='Project Number e.g. "PR2019.12"'
            ),
            NamingFormatter(
                template='{proj_building_name}',
                desc='Project Building Name e.g. "BLDG01"'
            ),
            NamingFormatter(
                template='{proj_issue_date}',
                desc='Project Issue Date e.g. "2019-10-12"'
            ),
            NamingFormatter(
                template='{proj_org_name}',
                desc='Project Organization Name e.g. "MYCOMP"'
            ),
            NamingFormatter(
                template='{proj_status}',
                desc='Project Status e.g. "CD100"'
            ),
            NamingFormatter(
                template='{username}',
                desc='Active User e.g. "eirannejad"'
            ),
            NamingFormatter(
                template='{revit_version}',
                desc='Active Revit Version e.g. "2019"'
            ),
            NamingFormatter(
                template='{sheet_param:PARAM_NAME}',
                desc='Value of Given Sheet Parameter e.g. '
                     'Replace PARAM_NAME with target parameter name'
            ),
            NamingFormatter(
                template='{tblock_param:PARAM_NAME}',
                desc='Value of Given TitleBlock Parameter e.g. '
                     'Replace PARAM_NAME with target parameter name'
            ),
            NamingFormatter(
                template='{proj_param:PARAM_NAME}',
                desc='Value of Given Project Information Parameter e.g. '
                     'Replace PARAM_NAME with target parameter name'
            ),
            NamingFormatter(
                template='{glob_param:PARAM_NAME}',
                desc='Value of Given Global Parameter. '
                     'Replace PARAM_NAME with target parameter name'
            ),
        ]
    
    @staticmethod
    def get_default_naming_formats():
        return [
            NamingFormat(
                name='0001 A1.00 1ST FLOOR PLAN.pdf',
                template='{index} {number} {name}.pdf',
                builtin=True
            ),
            NamingFormat(
                name='0001_A1.00_1ST FLOOR PLAN.pdf',
                template='{index}_{number}_{name}.pdf',
                builtin=True
            ),
            NamingFormat(
                name='0001-A1.00-1ST FLOOR PLAN.pdf',
                template='{index}-{number}-{name}.pdf',
                builtin=True
            ),
        ]
    
    @staticmethod
    def get_naming_formats():
        naming_formats = EditNamingFormatsWindow.get_default_naming_formats()
        naming_formats_dict = config.get_option('namingformats', {})
        for name, template in naming_formats_dict.items():
            naming_formats.append(NamingFormat(name=name, template=template))
        return naming_formats
    
    @staticmethod
    def set_naming_formats(naming_formats):
        naming_formats_dict = {
            x.name:x.template for x in naming_formats if not x.builtin
        }
        config.namingformats = naming_formats_dict
        script.save_config()
    
    @property
    def naming_formats(self):
        return self.formats_lb.ItemsSource
    
    @property
    def selected_naming_format(self):
        return self.formats_lb.SelectedItem
    
    @selected_naming_format.setter
    def selected_naming_format(self, value):
        self.formats_lb.SelectedItem = value
        self.namingformat_edit.DataContext = value
    
    def reset_formatters(self):
        self.formatters_wp.ItemsSource = \
            EditNamingFormatsWindow.get_default_formatters()
    
    def reset_naming_formats(self):
        self.formats_lb.ItemsSource = \
                ObjectModel.ObservableCollection[object](
                    EditNamingFormatsWindow.get_naming_formats()
                )
        if isinstance(self._starting_item, NamingFormat):
            for item in self.formats_lb.ItemsSource:
                if item.name == self._starting_item.name:
                    self.selected_naming_format = item
                    break
    
    def start_drag(self, sender, args):
        name_formatter = args.OriginalSource.DataContext
        Windows.DragDrop.DoDragDrop(
            self.formatters_wp,
            Windows.DataObject("name_formatter", name_formatter),
            Windows.DragDropEffects.Copy
            )
    
    def preview_drag(self, sender, args):
        mouse_pos = Forms.Cursor.Position
        mouse_po_pt = Windows.Point(mouse_pos.X, mouse_pos.Y)
        self._drop_pos = \
            self.template_tb.GetCharacterIndexFromPoint(
                point=self.template_tb.PointFromScreen(mouse_po_pt),
                snapToText=True
                )
        self.template_tb.SelectionStart = self._drop_pos
        self.template_tb.SelectionLength = 0
        self.template_tb.Focus()
        args.Effects = Windows.DragDropEffects.Copy
        args.Handled = True
    
    def stop_drag(self, sender, args):
        name_formatter = args.Data.GetData("name_formatter")
        if name_formatter:
            new_template = \
                str(self.template_tb.Text)[:self._drop_pos] \
                + name_formatter.template \
                + str(self.template_tb.Text)[self._drop_pos:]
            self.template_tb.Text = new_template
            self.template_tb.Focus()
    
    def namingformat_changed(self, sender, args):
        naming_format = self.selected_naming_format
        self.namingformat_edit.DataContext = naming_format
    
    def duplicate_namingformat(self, sender, args):
        naming_format = self.selected_naming_format
        new_naming_format = NamingFormat(
            name='<unnamed>',
            template=naming_format.template
            )
        self.naming_formats.Add(new_naming_format)
        self.selected_naming_format = new_naming_format
    
    def delete_namingformat(self, sender, args):
        naming_format = self.selected_naming_format
        if naming_format.builtin:
            return
        item_index = self.naming_formats.IndexOf(naming_format)
        self.naming_formats.Remove(naming_format)
        next_index = min([item_index, self.naming_formats.Count-1])
        self.selected_naming_format = self.naming_formats[next_index]
    
    def save_formats(self, sender, args):
        EditNamingFormatsWindow.set_naming_formats(self.naming_formats)
        self._saved = True
        self.Close()
    
    def cancelled(self, sender, args):
        if not self._saved:
            self.reset_naming_formats()


# ==============================================================================
# DATA CLASSES
# ==============================================================================

class SheetItem(System.ComponentModel.INotifyPropertyChanged):
    """Observable sheet item for checkbox binding"""
    
    def __init__(self, sheet):
        self._sheet = sheet
        self._sheet_number = sheet.SheetNumber
        self._sheet_name = sheet.Name
        self._display_text = "{} - {}".format(self._sheet_number, self._sheet_name)
        self._is_selected = False
        self._property_changed = None
    
    @property
    def Sheet(self):
        return self._sheet
    
    @property
    def SheetNumber(self):
        return self._sheet_number
    
    @property
    def SheetName(self):
        return self._sheet_name
    
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
# DATA COLLECTION FUNCTIONS
# ==============================================================================

def get_all_sheets():
    """Get all sheets in the project"""
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    # Sort by sheet number
    return sorted(sheets, key=lambda s: s.SheetNumber)


def get_view_sets():
    """Get all view sheet sets"""
    view_sets = FilteredElementCollector(doc)\
        .OfClass(ViewSheetSet)\
        .ToElements()
    
    return sorted(view_sets, key=lambda v: v.Name)


def get_dwg_export_setups():
    """Get all DWG export setups"""
    try:
        export_setups = BaseExportOptions.GetPredefinedSetupNames(doc)
        return list(export_setups) if export_setups else []
    except:
        return []


# Collect data
all_sheets = get_all_sheets()
view_sets = get_view_sets()
dwg_setups = get_dwg_export_setups()

if not all_sheets:
    forms.alert('No sheets found in the project', exitscript=True)


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class ExportPDFDWGWindow(Window):
    def __init__(self, xaml_path, sheets, viewsets, dwg_setups, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.all_sheets = sheets
        self.viewsets = viewsets
        self.dwg_setups = dwg_setups
        self.doc = document
        self.sheet_items = ObservableCollection[SheetItem]()
        self.filtered_sheet_items = ObservableCollection[SheetItem]()
        self.result = False
        
        # Default paths
        self.pdf_path = "C:\\Projects\\BIM\\Exports\\PDF"
        self.dwg_path = "C:\\Projects\\BIM\\Exports\\DWG"
        
        # Naming formats
        self.naming_formats = EditNamingFormatsWindow.get_naming_formats()
        self.selected_pdf_naming_format = self.naming_formats[0] if self.naming_formats else None
        self.selected_dwg_naming_format = self.naming_formats[0] if self.naming_formats else None
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.cmbViewSet = self._window.FindName("cmbViewSet")
        self.txtSheetFilter = self._window.FindName("txtSheetFilter")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnClearAll = self._window.FindName("btnClearAll")
        self.txtSheetCount = self._window.FindName("txtSheetCount")
        self.lstSheets = self._window.FindName("lstSheets")
        
        # Export format checkboxes
        self.chkExportPDF = self._window.FindName("chkExportPDF")
        self.chkExportDWG = self._window.FindName("chkExportDWG")
        
        # PDF settings
        self.txtPDFPath = self._window.FindName("txtPDFPath")
        self.btnBrowsePDF = self._window.FindName("btnBrowsePDF")
        self.cmbPDFNaming = self._window.FindName("cmbPDFNaming")
        self.btnEditPDFFormats = self._window.FindName("btnEditPDFFormats")
        self.chkPDFCombine = self._window.FindName("chkPDFCombine")
        
        # DWG settings
        self.txtDWGPath = self._window.FindName("txtDWGPath")
        self.btnBrowseDWG = self._window.FindName("btnBrowseDWG")
        self.cmbDWGNaming = self._window.FindName("cmbDWGNaming")
        self.btnEditDWGFormats = self._window.FindName("btnEditDWGFormats")
        self.cmbDWGSetup = self._window.FindName("cmbDWGSetup")
        self.cmbDWGVersion = self._window.FindName("cmbDWGVersion")
        
        # Preview and actions
        self.txtNamingPreview = self._window.FindName("txtNamingPreview")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnExport = self._window.FindName("btnExport")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize all dropdowns and data"""
        # View sets
        self.cmbViewSet.Items.Add("(All Sheets)")
        for viewset in self.viewsets:
            self.cmbViewSet.Items.Add(viewset.Name)
        self.cmbViewSet.SelectedIndex = 0
        
        # Naming formats
        self.LoadNamingFormats()
        
        # DWG export setups
        if self.dwg_setups:
            for setup in self.dwg_setups:
                self.cmbDWGSetup.Items.Add(setup)
            self.cmbDWGSetup.SelectedIndex = 0
        else:
            self.cmbDWGSetup.Items.Add("(Default)")
            self.cmbDWGSetup.SelectedIndex = 0
        
        # AutoCAD versions
        versions = [
            "AutoCAD 2018",
            "AutoCAD 2013",
            "AutoCAD 2010",
            "AutoCAD 2007"
        ]
        for version in versions:
            self.cmbDWGVersion.Items.Add(version)
        self.cmbDWGVersion.SelectedIndex = 0
        
        # Set default paths
        self.txtPDFPath.Text = self.pdf_path
        self.txtDWGPath.Text = self.dwg_path
        
        # Populate sheets
        for sheet in self.all_sheets:
            sheet_item = SheetItem(sheet)
            sheet_item.PropertyChanged += self.OnSheetSelectionChanged
            self.sheet_items.Add(sheet_item)
            self.filtered_sheet_items.Add(sheet_item)
        
        self.lstSheets.ItemsSource = self.filtered_sheet_items
        self.UpdateSheetCount()
    
    def LoadNamingFormats(self):
        """Load naming formats into combo boxes"""
        self.cmbPDFNaming.Items.Clear()
        self.cmbDWGNaming.Items.Clear()
        
        for fmt in self.naming_formats:
            self.cmbPDFNaming.Items.Add(fmt.name)
            self.cmbDWGNaming.Items.Add(fmt.name)
        
        if self.naming_formats:
            self.cmbPDFNaming.SelectedIndex = 0
            self.cmbDWGNaming.SelectedIndex = 0
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbViewSet.SelectionChanged += self.OnViewSetChanged
        self.txtSheetFilter.TextChanged += self.OnFilterChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnClearAll.Click += self.OnClearAll
        self.btnBrowsePDF.Click += self.OnBrowsePDF
        self.btnBrowseDWG.Click += self.OnBrowseDWG
        self.cmbPDFNaming.SelectionChanged += self.OnNamingChanged
        self.cmbDWGNaming.SelectionChanged += self.OnNamingChanged
        self.btnEditPDFFormats.Click += self.OnEditPDFFormats
        self.btnEditDWGFormats.Click += self.OnEditDWGFormats
        self.btnExport.Click += self.OnExport
    
    def OnEditPDFFormats(self, sender, args):
        """Open Edit Formats dialog for PDF"""
        script_dir = os.path.dirname(__file__)
        xaml_path = os.path.join(script_dir, "EditNamingFormats.xaml")
        
        if os.path.exists(xaml_path):
            editfmt_wnd = EditNamingFormatsWindow(
                xaml_path,
                start_with=self.selected_pdf_naming_format
            )
            editfmt_wnd.ShowDialog()
            # Reload formats
            self.naming_formats = list(editfmt_wnd.naming_formats)
            self.LoadNamingFormats()
            # Try to select the previously selected format
            if editfmt_wnd.selected_naming_format:
                for i, fmt in enumerate(self.naming_formats):
                    if fmt.name == editfmt_wnd.selected_naming_format.name:
                        self.cmbPDFNaming.SelectedIndex = i
                        break
        else:
            forms.alert("EditNamingFormats.xaml not found in script directory")
    
    def OnEditDWGFormats(self, sender, args):
        """Open Edit Formats dialog for DWG"""
        script_dir = os.path.dirname(__file__)
        xaml_path = os.path.join(script_dir, "EditNamingFormats.xaml")
        
        if os.path.exists(xaml_path):
            editfmt_wnd = EditNamingFormatsWindow(
                xaml_path,
                start_with=self.selected_dwg_naming_format
            )
            editfmt_wnd.ShowDialog()
            # Reload formats
            self.naming_formats = list(editfmt_wnd.naming_formats)
            self.LoadNamingFormats()
            # Try to select the previously selected format
            if editfmt_wnd.selected_naming_format:
                for i, fmt in enumerate(self.naming_formats):
                    if fmt.name == editfmt_wnd.selected_naming_format.name:
                        self.cmbDWGNaming.SelectedIndex = i
                        break
        else:
            forms.alert("EditNamingFormats.xaml not found in script directory")
    
    def OnViewSetChanged(self, sender, args):
        """Handle view set change"""
        self.FilterSheets()
    
    def OnFilterChanged(self, sender, args):
        """Handle filter text change"""
        self.FilterSheets()
    
    def FilterSheets(self):
        """Filter sheets based on view set and search text"""
        self.filtered_sheet_items.Clear()
        
        # Get view set filter
        selected_viewset = None
        viewset_sheet_ids = None
        
        if self.cmbViewSet.SelectedItem and self.cmbViewSet.SelectedItem.ToString() != "(All Sheets)":
            viewset_name = self.cmbViewSet.SelectedItem.ToString()
            for vs in self.viewsets:
                if vs.Name == viewset_name:
                    selected_viewset = vs
                    # Convert ViewSet.Views to a set of ElementIds (integer values)
                    viewset_sheet_ids = set()
                    for v in selected_viewset.Views:
                        # Handle both ElementId and View objects
                        if isinstance(v, ElementId):
                            viewset_sheet_ids.add(v.IntegerValue)
                        else:
                            # It's a View object, get its Id
                            viewset_sheet_ids.add(v.Id.IntegerValue)
                    break
        
        # Get search filter
        search_text = self.txtSheetFilter.Text.lower() if self.txtSheetFilter.Text else ""
        
        # Apply filters
        for item in self.sheet_items:
            # View set filter
            if viewset_sheet_ids is not None:
                if item.Sheet.Id.IntegerValue not in viewset_sheet_ids:
                    continue
            
            # Search filter
            if search_text:
                if search_text not in item.SheetNumber.lower() and \
                   search_text not in item.SheetName.lower():
                    continue
            
            self.filtered_sheet_items.Add(item)
        
        self.UpdateSheetCount()
    
    def UpdateSheetCount(self):
        """Update sheet count display"""
        selected = sum(1 for item in self.filtered_sheet_items if item.IsSelected)
        total = len(self.filtered_sheet_items)
        self.txtSheetCount.Text = "{} / {} sheets selected".format(selected, total)
    
    def OnSheetSelectionChanged(self, sender, args):
        """Handle sheet selection change"""
        self.UpdateSheetCount()
        self.UpdateNamingPreview()
    
    def OnSelectAll(self, sender, args):
        """Select all sheets"""
        for item in self.filtered_sheet_items:
            item.IsSelected = True
        self.UpdateSheetCount()
    
    def OnClearAll(self, sender, args):
        """Clear all selections"""
        for item in self.filtered_sheet_items:
            item.IsSelected = False
        self.UpdateSheetCount()
    
    def OnBrowsePDF(self, sender, args):
        """Browse for PDF folder"""
        dialog = FolderBrowserDialog()
        dialog.Description = "Select PDF Export Folder"
        dialog.SelectedPath = self.pdf_path
        
        if dialog.ShowDialog() == DialogResult.OK:
            self.pdf_path = dialog.SelectedPath
            self.txtPDFPath.Text = self.pdf_path
    
    def OnBrowseDWG(self, sender, args):
        """Browse for DWG folder"""
        dialog = FolderBrowserDialog()
        dialog.Description = "Select DWG Export Folder"
        dialog.SelectedPath = self.dwg_path
        
        if dialog.ShowDialog() == DialogResult.OK:
            self.dwg_path = dialog.SelectedPath
            self.txtDWGPath.Text = self.dwg_path
    
    def OnNamingChanged(self, sender, args):
        """Handle naming format change"""
        # Update selected formats
        if self.cmbPDFNaming.SelectedIndex >= 0:
            self.selected_pdf_naming_format = self.naming_formats[self.cmbPDFNaming.SelectedIndex]
        if self.cmbDWGNaming.SelectedIndex >= 0:
            self.selected_dwg_naming_format = self.naming_formats[self.cmbDWGNaming.SelectedIndex]
        
        self.UpdateNamingPreview()
    
    def UpdateNamingPreview(self):
        """Update naming preview"""
        # Find first selected sheet
        first_sheet = None
        for item in self.filtered_sheet_items:
            if item.IsSelected:
                first_sheet = item.Sheet
                break
        
        if not first_sheet:
            self.txtNamingPreview.Text = "Select a sheet to preview naming..."
            return
        
        # Generate preview using naming format templates
        pdf_name = self.GenerateFileName(first_sheet, self.selected_pdf_naming_format, 1) if self.selected_pdf_naming_format else ""
        dwg_name = self.GenerateFileName(first_sheet, self.selected_dwg_naming_format, 1) if self.selected_dwg_naming_format else ""
        
        # Replace .pdf with .dwg for DWG preview
        if dwg_name.lower().endswith('.pdf'):
            dwg_name = dwg_name[:-4] + '.dwg'
        
        preview = "PDF: {}\nDWG: {}".format(pdf_name, dwg_name)
        self.txtNamingPreview.Text = preview
    
    def GenerateFileName(self, sheet, naming_format, index=1):
        """Generate filename from template with enhanced parameter support"""
        if not naming_format:
            return sheet.SheetNumber + ".pdf"
        
        template = naming_format.template
        
        # Replace index first
        template = template.replace('{index}', str(index).zfill(4))
        
        # Basic sheet info
        template = template.replace('{number}', sheet.SheetNumber)
        template = template.replace('{name}', sheet.Name)
        template = template.replace('{name_dash}', sheet.Name.replace(' ', '-'))
        template = template.replace('{name_underline}', sheet.Name.replace(' ', '_'))
        
        # Current date
        template = template.replace('{current_date}', coreutils.current_date())
        
        # Sheet parameters - using regex to find custom parameters
        sheet_param_pattern = r'\{sheet_param:([^}]+)\}'
        for param_name in re.findall(sheet_param_pattern, template):
            try:
                param = sheet.LookupParameter(param_name)
                if param:
                    param_value = revit.query.get_param_value(param)
                    if param_value:
                        template = template.replace('{sheet_param:' + param_name + '}', str(param_value))
                    else:
                        template = template.replace('{sheet_param:' + param_name + '}', '')
                else:
                    template = template.replace('{sheet_param:' + param_name + '}', '')
            except:
                template = template.replace('{sheet_param:' + param_name + '}', '')
        
        # Titleblock parameters
        tblock_param_pattern = r'\{tblock_param:([^}]+)\}'
        for param_name in re.findall(tblock_param_pattern, template):
            try:
                # Get titleblock from sheet
                tblocks = FilteredElementCollector(doc, sheet.Id)\
                    .OfCategory(BuiltInCategory.OST_TitleBlocks)\
                    .ToElements()
                
                param_value = None
                if tblocks:
                    tblock = list(tblocks)[0]
                    param = tblock.LookupParameter(param_name)
                    if param:
                        param_value = revit.query.get_param_value(param)
                    else:
                        # Try type parameter
                        tblock_type = doc.GetElement(tblock.GetTypeId())
                        param = tblock_type.LookupParameter(param_name)
                        if param:
                            param_value = revit.query.get_param_value(param)
                
                if param_value:
                    template = template.replace('{tblock_param:' + param_name + '}', str(param_value))
                else:
                    template = template.replace('{tblock_param:' + param_name + '}', '')
            except:
                template = template.replace('{tblock_param:' + param_name + '}', '')
        
        # Project parameters
        proj_param_pattern = r'\{proj_param:([^}]+)\}'
        for param_name in re.findall(proj_param_pattern, template):
            try:
                proj_info = doc.ProjectInformation
                param = proj_info.LookupParameter(param_name)
                if param:
                    param_value = revit.query.get_param_value(param)
                    if param_value:
                        template = template.replace('{proj_param:' + param_name + '}', str(param_value))
                    else:
                        template = template.replace('{proj_param:' + param_name + '}', '')
                else:
                    template = template.replace('{proj_param:' + param_name + '}', '')
            except:
                template = template.replace('{proj_param:' + param_name + '}', '')
        
        # Global parameters
        glob_param_pattern = r'\{glob_param:([^}]+)\}'
        for param_name in re.findall(glob_param_pattern, template):
            try:
                glob_param = revit.query.get_global_parameter(param_name, doc=doc)
                if glob_param:
                    param_value = revit.query.get_param_value(glob_param)
                    if param_value:
                        template = template.replace('{glob_param:' + param_name + '}', str(param_value))
                    else:
                        template = template.replace('{glob_param:' + param_name + '}', '')
                else:
                    template = template.replace('{glob_param:' + param_name + '}', '')
            except:
                template = template.replace('{glob_param:' + param_name + '}', '')
        
        # Standard sheet parameters
        try:
            issue_date_param = sheet.LookupParameter("Sheet Issue Date")
            if issue_date_param:
                template = template.replace('{issue_date}', issue_date_param.AsString() or "")
            else:
                template = template.replace('{issue_date}', "")
        except:
            template = template.replace('{issue_date}', "")
        
        # Revision info - Get the current revision shown on sheet
        try:
            # Try to get the "Current Revision" parameter value directly (as shown on sheet)
            current_rev_param = sheet.LookupParameter("Current Revision")
            sheet_rev_date_param = sheet.LookupParameter("Sheet Issue Date")
            
            if current_rev_param and current_rev_param.HasValue:
                rev_value = current_rev_param.AsString()
                template = template.replace('{rev_number}', rev_value if rev_value else '')
            else:
                template = template.replace('{rev_number}', '')
            
            if sheet_rev_date_param and sheet_rev_date_param.HasValue:
                rev_date_value = sheet_rev_date_param.AsString()
                template = template.replace('{rev_date}', rev_date_value if rev_date_value else '')
            else:
                template = template.replace('{rev_date}', '')
            
            # For revision description, try to get from the actual revision on sheet
            sheet_rev_ids = sheet.GetAdditionalRevisionIds()
            
            if sheet_rev_ids and len(sheet_rev_ids) > 0:
                # Get the latest revision on the sheet
                all_revisions = FilteredElementCollector(doc)\
                    .OfCategory(BuiltInCategory.OST_Revisions)\
                    .WhereElementIsNotElementType()\
                    .ToElements()
                
                sheet_revisions = [rev for rev in all_revisions if rev.Id in sheet_rev_ids]
                
                if sheet_revisions:
                    sheet_revisions.sort(key=lambda r: r.SequenceNumber)
                    latest_rev = sheet_revisions[-1]
                    template = template.replace('{rev_desc}', latest_rev.Description if latest_rev.Description else '')
                else:
                    template = template.replace('{rev_desc}', '')
            else:
                template = template.replace('{rev_desc}', '')
                
        except Exception as e:
            template = template.replace('{rev_number}', '')
            template = template.replace('{rev_desc}', '')
            template = template.replace('{rev_date}', '')
        
        # Project info
        try:
            proj_info = doc.ProjectInformation
            
            # Project Name
            proj_name_param = proj_info.LookupParameter("Project Name")
            if proj_name_param:
                template = template.replace('{proj_name}', proj_name_param.AsString() or "")
            else:
                template = template.replace('{proj_name}', "")
            
            # Project Number
            proj_num_param = proj_info.LookupParameter("Project Number")
            if proj_num_param:
                template = template.replace('{proj_number}', proj_num_param.AsString() or "")
            else:
                template = template.replace('{proj_number}', "")
            
            # Building Name
            proj_bldg_param = proj_info.LookupParameter("Building Name")
            if proj_bldg_param:
                template = template.replace('{proj_building_name}', proj_bldg_param.AsString() or "")
            else:
                template = template.replace('{proj_building_name}', "")
            
            # Project Issue Date
            proj_issue_param = proj_info.LookupParameter("Project Issue Date")
            if proj_issue_param:
                template = template.replace('{proj_issue_date}', proj_issue_param.AsString() or "")
            else:
                template = template.replace('{proj_issue_date}', "")
            
            # Organization Name
            proj_org_param = proj_info.LookupParameter("Organization Name")
            if proj_org_param:
                template = template.replace('{proj_org_name}', proj_org_param.AsString() or "")
            else:
                template = template.replace('{proj_org_name}', "")
            
            # Project Status
            proj_status_param = proj_info.LookupParameter("Project Status")
            if proj_status_param:
                template = template.replace('{proj_status}', proj_status_param.AsString() or "")
            else:
                template = template.replace('{proj_status}', "")
                
        except:
            template = template.replace('{proj_name}', "")
            template = template.replace('{proj_number}', "")
            template = template.replace('{proj_building_name}', "")
            template = template.replace('{proj_issue_date}', "")
            template = template.replace('{proj_org_name}', "")
            template = template.replace('{proj_status}', "")
        
        # User and Revit info
        template = template.replace('{username}', HOST_APP.username)
        template = template.replace('{revit_version}', str(HOST_APP.version))
        
        # Clean up any remaining unreplaced tags
        template = re.sub(r'\{[^}]*\}', '', template)
        
        return template
    
    def OnExport(self, sender, args):
        """Handle export"""
        # Validate
        selected_sheets = [item for item in self.filtered_sheet_items if item.IsSelected]
        
        if not selected_sheets:
            self.txtStatus.Text = "❌ No sheets selected"
            return
        
        if not self.chkExportPDF.IsChecked and not self.chkExportDWG.IsChecked:
            self.txtStatus.Text = "❌ Select at least one export format"
            return
        
        # Update paths
        self.pdf_path = self.txtPDFPath.Text
        self.dwg_path = self.txtDWGPath.Text
        
        # Export
        self.txtStatus.Text = "⏳ Exporting..."
        output.print_md("---")
        output.print_md("## Starting Export")
        output.print_md("**Sheets**: {}".format(len(selected_sheets)))
        
        pdf_success = 0
        pdf_errors = 0
        dwg_success = 0
        dwg_errors = 0
        
        if self.chkExportPDF.IsChecked:
            output.print_md("### Exporting PDFs...")
            pdf_success, pdf_errors = self.ExportPDF(selected_sheets)
        
        if self.chkExportDWG.IsChecked:
            output.print_md("### Exporting DWGs...")
            dwg_success, dwg_errors = self.ExportDWG(selected_sheets)
        
        # Update status
        total_success = pdf_success + dwg_success
        total_errors = pdf_errors + dwg_errors
        
        status_msg = "✅ Complete: {} succeeded, {} failed".format(total_success, total_errors)
        self.txtStatus.Text = status_msg
        output.print_md("---")
        output.print_md("## " + status_msg)
        
        self.result = True
    
    def ExportPDF(self, selected_sheets):
        """Export sheets to PDF"""
        success = 0
        errors = 0
        
        # Create directory
        if not os.path.exists(self.pdf_path):
            try:
                os.makedirs(self.pdf_path)
            except Exception as e:
                output.print_md("✗ Failed to create PDF directory: {}".format(str(e)))
                return 0, len(selected_sheets)
        
        if self.chkPDFCombine.IsChecked:
            # Combined PDF
            try:
                opts = PDFExportOptions()
                opts.ExportQuality = PDFExportQualityType.DPI600
                opts.PaperFormat = ExportPaperFormat.Default
                opts.ZoomType = ZoomType.Zoom
                opts.ZoomPercentage = 100
                opts.HideCropBoundaries = True
                opts.HideReferencePlane = True
                opts.HideScopeBoxes = True
                opts.HideUnreferencedViewTags = True
                opts.MaskCoincidentLines = True
                opts.ViewLinksInBlue = False
                opts.ColorDepth = ColorDepthType.Color
                opts.StopOnError = False
                
                combined_name = "Combined_Sheets_{}".format(
                    System.DateTime.Now.ToString("yyyyMMdd_HHmmss")
                )
                
                opts.Combine = True
                opts.FileName = combined_name
                
                sheetId = List[ElementId](item.Sheet.Id for item in selected_sheets)
                
                result = self.doc.Export(self.pdf_path, sheetId, opts)
                
                if result:
                    output.print_md("✓ PDF: {}.pdf (combined {} sheets)".format(combined_name, len(selected_sheets)))
                    success = len(selected_sheets)
                else:
                    output.print_md("✗ PDF Combined: Export returned False")
                    errors = len(selected_sheets)
            
            except Exception as e:
                output.print_md("✗ PDF Combined: {}".format(str(e)))
                errors = len(selected_sheets)
        else:
            # Individual PDFs
            index = 1
            for item in selected_sheets:
                try:
                    opts = PDFExportOptions()
                    opts.ExportQuality = PDFExportQualityType.DPI600
                    opts.PaperFormat = ExportPaperFormat.Default
                    opts.ZoomType = ZoomType.Zoom
                    opts.ZoomPercentage = 100
                    opts.HideCropBoundaries = True
                    opts.HideReferencePlane = True
                    opts.HideScopeBoxes = True
                    opts.HideUnreferencedViewTags = True
                    opts.MaskCoincidentLines = True
                    opts.ViewLinksInBlue = False
                    opts.ColorDepth = ColorDepthType.Color
                    opts.StopOnError = False
                    
                    filename = self.GenerateFileName(item.Sheet, self.selected_pdf_naming_format, index)
                    
                    # Remove .pdf extension (Revit adds it)
                    if filename.lower().endswith('.pdf'):
                        filename = filename[:-4]
                    
                    opts.FileName = filename
                    
                    sheetId = List[ElementId]()
                    sheetId.Add(item.Sheet.Id)
                    
                    result = self.doc.Export(self.pdf_path, sheetId, opts)
                    
                    if result:
                        output.print_md("✓ PDF: {} - {}.pdf".format(item.SheetNumber, filename))
                        success += 1
                    else:
                        output.print_md("✗ PDF: {} - Export returned False".format(item.SheetNumber))
                        errors += 1
                    
                    index += 1
                    
                except Exception as e:
                    output.print_md("✗ PDF: {} - {}".format(item.SheetNumber, str(e)))
                    errors += 1
        
        return success, errors
    
    def ExportDWG(self, selected_sheets):
        """Export sheets to DWG"""
        success = 0
        errors = 0
        
        # Create directory
        if not os.path.exists(self.dwg_path):
            os.makedirs(self.dwg_path)
        
        # Get export setup
        setup_name = self.cmbDWGSetup.SelectedItem.ToString() if self.cmbDWGSetup.SelectedItem else "(Default)"
        use_custom_setup = setup_name != "(Default)" and setup_name in self.dwg_setups
        
        dwg_options = DWGExportOptions()
        
        if use_custom_setup:
            try:
                dwg_options = DWGExportOptions.GetPredefinedOptions(self.doc, setup_name)
                output.print_md("Using DWG export setup: {}".format(setup_name))
            except Exception as e:
                output.print_md("Warning: Could not load setup '{}', using defaults: {}".format(setup_name, str(e)))
                dwg_options = DWGExportOptions()
        
        # Set AutoCAD version
        try:
            version_map = {
                "AutoCAD 2018": ACADVersion.R2018,
                "AutoCAD 2013": ACADVersion.R2013,
                "AutoCAD 2010": ACADVersion.R2010,
                "AutoCAD 2007": ACADVersion.R2007
            }
            selected_version = self.cmbDWGVersion.SelectedItem.ToString()
            if selected_version in version_map:
                dwg_options.FileVersion = version_map[selected_version]
                output.print_md("AutoCAD version: {}".format(selected_version))
        except Exception as e:
            output.print_md("Note: Could not set AutoCAD version: {}".format(str(e)))
        
        # Export sheets
        index = 1
        for item in selected_sheets:
            try:
                sheet_ids = List[ElementId]()
                sheet_ids.Add(item.Sheet.Id)
                
                filename = self.GenerateFileName(item.Sheet, self.selected_dwg_naming_format, index)
                # Replace .pdf with .dwg
                if filename.lower().endswith('.pdf'):
                    filename = filename[:-4] + '.dwg'
                elif not filename.lower().endswith('.dwg'):
                    filename = filename + '.dwg'
                
                self.doc.Export(self.dwg_path, filename, sheet_ids, dwg_options)
                
                output.print_md("✓ DWG: {} - {}".format(item.SheetNumber, filename))
                success += 1
                index += 1
            except Exception as e:
                output.print_md("✗ DWG: {} - {}".format(item.SheetNumber, str(e)))
                errors += 1
        
        return success, errors
    
    def OnClose(self, sender, args):
        """Handle close"""
        self._window.Close()
    
    def ShowDialog(self):
        """Show dialog"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get XAML file path
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "ExportPDFDWG.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

output.print_md("**Found {} sheets**".format(len(all_sheets)))
output.print_md("**View Sets**: {}".format(len(view_sets)))
output.print_md("**DWG Export Setups**: {}".format(len(dwg_setups)))

# Show window
window = ExportPDFDWGWindow(xaml_path, all_sheets, view_sets, dwg_setups, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Export Completed Successfully")
else:
    output.print_md("### Export Cancelled or Closed")