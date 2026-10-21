# -*- coding: utf-8 -*-
"""
Revision Manager - Modern XAML UI
Set selected revisions on selected sheets with advanced filtering
"""
__title__ = 'Revision\nManager'
__doc__ = 'Assign revisions to sheets with modern XAML interface'

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms
from System.Windows import Window
from System.Collections.Generic import List as DotNetList
import wpf
import os
import sys

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# Get script directory
PATH_SCRIPT = os.path.dirname(__file__)


# ==============================================================================
# DATA COLLECTION FUNCTIONS
# ==============================================================================

def get_all_revisions():
    """Get all revisions in the project"""
    all_revisions = FilteredElementCollector(doc)\
        .OfClass(Revision)\
        .ToElements()
    
    revisions_sorted = sorted(all_revisions, key=lambda r: r.SequenceNumber)
    return revisions_sorted


def get_all_sheets():
    """Get all sheets in the project"""
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    sheets_sorted = sorted(sheets, key=lambda s: s.SheetNumber)
    return sheets_sorted


# ==============================================================================
# REVISION REPORT WINDOW CLASS
# ==============================================================================

class RevisionReportWindow(Window):
    def __init__(self, document):
        """Initialize the Revision Report window"""
        self.doc = document
        self.all_data = []
        self.filtered_data = []
        
        # Load XAML
        xaml_file = os.path.join(PATH_SCRIPT, 'RevisionReportUI.xaml')
        wpf.LoadComponent(self, xaml_file)
        
        # Load logo
        self.load_logo()
        
        # Collect and display data
        self.collect_report_data()
        self.update_display()
    
    def load_logo(self):
        """Load BA logo image"""
        try:
            logo_path = os.path.join(PATH_SCRIPT, 'ba_logo.png')
            if os.path.exists(logo_path):
                from System.Windows.Media.Imaging import BitmapImage
                from System import Uri
                self.ba_logo.Source = BitmapImage(Uri(logo_path))
        except Exception as e:
            print("Logo not found: {}".format(str(e)))
    
    def collect_report_data(self):
        """Collect all sheets and their revisions"""
        # Get all sheets
        sheets = FilteredElementCollector(self.doc)\
            .OfCategory(BuiltInCategory.OST_Sheets)\
            .WhereElementIsNotElementType()\
            .ToElements()
        
        sheets_sorted = sorted(sheets, key=lambda s: s.SheetNumber)
        
        # Collect data
        self.all_data = []
        for sheet in sheets_sorted:
            try:
                # Get revisions on this sheet
                rev_ids = list(sheet.GetAdditionalRevisionIds())
                revisions = [self.doc.GetElement(rev_id) for rev_id in rev_ids]
                revisions = [r for r in revisions if r is not None]
                
                # Sort by sequence number
                revisions_sorted = sorted(revisions, key=lambda r: r.SequenceNumber)
                
                # Create revision list string
                if revisions_sorted:
                    rev_list = ", ".join([
                        "Rev {} - {}".format(
                            r.SequenceNumber,
                            r.Description or "(No Description)"
                        ) 
                        for r in revisions_sorted
                    ])
                else:
                    rev_list = "No revisions"
                
                # Create data row
                row_data = {
                    'SheetNumber': sheet.SheetNumber,
                    'SheetName': sheet.Name,
                    'RevisionCount': len(revisions_sorted),
                    'Revisions': rev_list,
                    'Sheet': sheet
                }
                
                self.all_data.append(row_data)
                
            except Exception as e:
                print("Error processing sheet {}: {}".format(sheet.SheetNumber, str(e)))
        
        self.filtered_data = list(self.all_data)
        
        # Update statistics
        total_revisions = sum(row['RevisionCount'] for row in self.all_data)
        self.txt_total_sheets.Text = "Total Sheets: {}".format(len(self.all_data))
        self.txt_total_revisions.Text = "Total Assignments: {}".format(total_revisions)
    
    def update_display(self):
        """Update the data grid with filtered data"""
        from System.Collections.ObjectModel import ObservableCollection
        
        # Create observable collection
        collection = ObservableCollection[object]()
        for row in self.filtered_data:
            # Create anonymous object for binding
            item = type('ReportRow', (), row)()
            collection.Add(item)
        
        self.data_grid_report.ItemsSource = collection
        self.txt_filtered_count.Text = "Showing: {} sheets".format(len(self.filtered_data))
    
    def OnFilterChanged(self, sender, args):
        """Handle filter radio button change"""
        if not hasattr(self, 'all_data'):
            return
        
        if self.radio_all_sheets.IsChecked:
            self.filtered_data = list(self.all_data)
        elif self.radio_with_revisions.IsChecked:
            self.filtered_data = [row for row in self.all_data if row['RevisionCount'] > 0]
        elif self.radio_no_revisions.IsChecked:
            self.filtered_data = [row for row in self.all_data if row['RevisionCount'] == 0]
        
        # Apply search filter
        self.apply_search_filter()
        self.update_display()
    
    def OnSearchChanged(self, sender, args):
        """Handle search text change"""
        self.apply_search_filter()
        self.update_display()
    
    def apply_search_filter(self):
        """Apply search filter to current filtered data"""
        search_text = self.txt_search.Text.lower() if self.txt_search.Text else ""
        
        if not search_text:
            return
        
        # Get base filter
        if self.radio_all_sheets.IsChecked:
            base_data = list(self.all_data)
        elif self.radio_with_revisions.IsChecked:
            base_data = [row for row in self.all_data if row['RevisionCount'] > 0]
        else:
            base_data = [row for row in self.all_data if row['RevisionCount'] == 0]
        
        # Apply search
        self.filtered_data = [
            row for row in base_data
            if search_text in row['SheetNumber'].lower() or 
               search_text in row['SheetName'].lower() or
               search_text in row['Revisions'].lower()
        ]
    
    def RefreshData(self, sender, args):
        """Refresh the report data"""
        self.collect_report_data()
        self.OnFilterChanged(None, None)
    
    def ExportToCSV(self, sender, args):
        """Export report to CSV file"""
        try:
            from System.Windows.Forms import SaveFileDialog, DialogResult
            
            dialog = SaveFileDialog()
            dialog.Filter = "CSV Files (*.csv)|*.csv"
            dialog.FileName = "RevisionReport.csv"
            dialog.Title = "Export Revision Report"
            
            if dialog.ShowDialog() == DialogResult.OK:
                filepath = dialog.FileName
                
                with open(filepath, 'w') as f:
                    f.write("Sheet Number,Sheet Name,Revision Count,Revisions\n")
                    
                    for row in self.filtered_data:
                        f.write('"{}", "{}", {}, "{}"\n'.format(
                            row['SheetNumber'],
                            row['SheetName'],
                            row['RevisionCount'],
                            row['Revisions']
                        ))
                
                forms.alert("Report exported successfully!", title="Export Complete")
                
        except Exception as e:
            forms.alert("Export failed: {}".format(str(e)), title="Export Error")
    
    def CloseWindow(self, sender, args):
        """Close the window"""
        self.Close()


# ==============================================================================
# REVISION MANAGER WINDOW CLASS
# ==============================================================================

class RevisionManagerWindow(Window):
    def __init__(self, revisions, sheets, document):
        """Initialize the Revision Manager window"""
        self.revisions = revisions
        self.sheets = sheets
        self.all_sheets = sheets
        self.doc = document
        self.result = None
        
        # Load XAML
        xaml_file = os.path.join(PATH_SCRIPT, 'RevisionManagerUI.xaml')
        wpf.LoadComponent(self, xaml_file)
        
        # Populate lists
        self.populate_revisions()
        self.populate_sheets()
        
        # Update counters
        self.update_revision_count()
        self.update_sheet_count()
        self.update_preview()
    
    def CloseWindow(self, sender, args):
        """Close the window"""
        self.Close()
    
    def ShowReport(self, sender, args):
        """Open the revision report window"""
        report_window = RevisionReportWindow(self.doc)
        report_window.ShowDialog()
    
    def populate_revisions(self):
        """Populate the revision list"""
        self.list_revisions.Items.Clear()
        
        for rev in self.revisions:
            if self.radio_unissued_only.IsChecked and rev.Issued:
                continue
            
            issued_text = "" if not rev.Issued else " [ISSUED]"
            display_text = "Rev {} - {}{}".format(
                rev.SequenceNumber,
                rev.Description or "(No Description)",
                issued_text
            )
            self.list_revisions.Items.Add(display_text)
    
    def populate_sheets(self):
        """Populate the sheet list"""
        self.list_sheets.Items.Clear()
        
        filter_text = self.txt_sheet_filter.Text.lower() if self.txt_sheet_filter.Text else ""
        
        self.sheets = []
        for sheet in self.all_sheets:
            display_text = "{} - {}".format(sheet.SheetNumber, sheet.Name)
            
            if not filter_text or filter_text in display_text.lower():
                self.list_sheets.Items.Add(display_text)
                self.sheets.append(sheet)
        
        self.update_sheet_count()
    
    def OnRevisionFilterChanged(self, sender, args):
        """Handle revision filter change"""
        self.populate_revisions()
        self.update_revision_count()
    
    def OnSheetFilterChanged(self, sender, args):
        """Handle sheet filter text change"""
        self.populate_sheets()
    
    def SelectAllRevisions(self, sender, args):
        """Select all revisions in the list"""
        for i in range(self.list_revisions.Items.Count):
            self.list_revisions.SelectedItems.Add(self.list_revisions.Items[i])
        self.update_revision_count()
        self.update_preview()
    
    def ClearAllRevisions(self, sender, args):
        """Clear all revision selections"""
        self.list_revisions.SelectedItems.Clear()
        self.update_revision_count()
        self.update_preview()
    
    def SelectAllSheets(self, sender, args):
        """Select all sheets in the list"""
        for i in range(self.list_sheets.Items.Count):
            self.list_sheets.SelectedItems.Add(self.list_sheets.Items[i])
        self.update_sheet_count()
        self.update_preview()
    
    def ClearAllSheets(self, sender, args):
        """Clear all sheet selections"""
        self.list_sheets.SelectedItems.Clear()
        self.update_sheet_count()
        self.update_preview()
    
    def SelectFiltered(self, sender, args):
        """Select all filtered sheets"""
        self.SelectAllSheets(sender, args)
    
    def UpdateRevisionCount(self, sender, args):
        """Update revision count (event handler)"""
        self.update_revision_count()
        self.update_preview()
    
    def update_revision_count(self):
        """Update the revision counter label"""
        count = self.list_revisions.SelectedItems.Count
        self.txt_revision_count.Text = "Selected: {} revisions".format(count)
    
    def UpdateSheetCount(self, sender, args):
        """Update sheet count (event handler)"""
        self.update_sheet_count()
        self.update_preview()
    
    def update_sheet_count(self):
        """Update the sheet counter label"""
        selected = self.list_sheets.SelectedItems.Count
        total = self.list_sheets.Items.Count
        self.txt_sheet_count.Text = "Selected: {} / {}".format(selected, total)
    
    def update_preview(self):
        """Update the preview text"""
        rev_count = self.list_revisions.SelectedItems.Count
        sheet_count = self.list_sheets.SelectedItems.Count
        
        if rev_count == 0 or sheet_count == 0:
            self.txt_status.Text = "Select revisions and sheets to see preview..."
            return
        
        preview_text = "Ready to apply {} revision(s) to {} sheet(s)\n\n".format(
            rev_count,
            sheet_count
        )
        
        preview_text += "Revisions:\n"
        for i in range(min(rev_count, 3)):
            preview_text += "  • {}\n".format(self.list_revisions.SelectedItems[i])
        if rev_count > 3:
            preview_text += "  ... and {} more\n".format(rev_count - 3)
        
        preview_text += "\nSheets:\n"
        for i in range(min(sheet_count, 3)):
            preview_text += "  • {}\n".format(self.list_sheets.SelectedItems[i])
        if sheet_count > 3:
            preview_text += "  ... and {} more".format(sheet_count - 3)
        
        self.txt_status.Text = preview_text
    
    def ApplyRevisions(self, sender, args):
        """Apply selected revisions to selected sheets"""
        selected_rev_indices = []
        for item in self.list_revisions.SelectedItems:
            selected_rev_indices.append(self.list_revisions.Items.IndexOf(item))
        
        if len(selected_rev_indices) == 0:
            forms.alert("Please select at least one revision", title="Validation Error")
            return
        
        selected_sheet_indices = []
        for item in self.list_sheets.SelectedItems:
            selected_sheet_indices.append(self.list_sheets.Items.IndexOf(item))
        
        if len(selected_sheet_indices) == 0:
            forms.alert("Please select at least one sheet", title="Validation Error")
            return
        
        display_revisions = []
        for rev in self.revisions:
            if self.radio_unissued_only.IsChecked and rev.Issued:
                continue
            display_revisions.append(rev)
        
        selected_revisions = [display_revisions[i] for i in selected_rev_indices]
        selected_sheets = [self.sheets[i] for i in selected_sheet_indices]
        
        confirm_msg = "Apply {} revision(s) to {} sheet(s)?\n\nContinue?".format(
            len(selected_revisions),
            len(selected_sheets)
        )
        
        if not forms.alert(confirm_msg, yes=True, no=True):
            return
        
        self.btn_apply.IsEnabled = False
        self.btn_apply.Content = "APPLYING..."
        
        success_count = 0
        error_count = 0
        
        t = Transaction(doc, "Apply Revisions to Sheets")
        t.Start()
        
        try:
            for sheet in selected_sheets:
                try:
                    existing_rev_ids = list(sheet.GetAdditionalRevisionIds())
                    
                    for rev in selected_revisions:
                        if rev.Id not in existing_rev_ids:
                            existing_rev_ids.append(rev.Id)
                    
                    dotnet_list = DotNetList[ElementId]()
                    for rev_id in existing_rev_ids:
                        dotnet_list.Add(rev_id)
                    
                    sheet.SetAdditionalRevisionIds(dotnet_list)
                    success_count += 1
                    
                except Exception as e:
                    error_count += 1
                    output.print_md("✗ {} - {}: {}".format(
                        sheet.SheetNumber,
                        sheet.Name,
                        str(e)
                    ))
            
            t.Commit()
            
        except Exception as ex:
            t.RollBack()
            output.print_md("ERROR: Transaction failed - {}".format(str(ex)))
            error_count += len(selected_sheets)
        
        msg = "Revision assignment complete!\n\n"
        msg += "Success: {}\n".format(success_count)
        msg += "Errors: {}".format(error_count)
        
        forms.alert(msg, title="Complete")
        
        self.result = True
        self.btn_apply.IsEnabled = True
        self.btn_apply.Content = "Apply Revisions"
    
    def RemoveRevisions(self, sender, args):
        """Remove selected revisions from selected sheets"""
        selected_rev_indices = []
        for item in self.list_revisions.SelectedItems:
            selected_rev_indices.append(self.list_revisions.Items.IndexOf(item))
        
        if len(selected_rev_indices) == 0:
            forms.alert("Please select at least one revision to remove", title="Validation Error")
            return
        
        selected_sheet_indices = []
        for item in self.list_sheets.SelectedItems:
            selected_sheet_indices.append(self.list_sheets.Items.IndexOf(item))
        
        if len(selected_sheet_indices) == 0:
            forms.alert("Please select at least one sheet", title="Validation Error")
            return
        
        display_revisions = []
        for rev in self.revisions:
            if self.radio_unissued_only.IsChecked and rev.Issued:
                continue
            display_revisions.append(rev)
        
        selected_revisions = [display_revisions[i] for i in selected_rev_indices]
        selected_sheets = [self.sheets[i] for i in selected_sheet_indices]
        
        confirm_msg = "Remove {} revision(s) from {} sheet(s)?\n\nThis will only remove the selected revisions.\nContinue?".format(
            len(selected_revisions),
            len(selected_sheets)
        )
        
        if not forms.alert(confirm_msg, yes=True, no=True):
            return
        
        self.btn_remove.IsEnabled = False
        self.btn_remove.Content = "REMOVING..."
        
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        revisions_to_remove = [rev.Id for rev in selected_revisions]
        
        t = Transaction(doc, "Remove Revisions from Sheets")
        t.Start()
        
        try:
            for sheet in selected_sheets:
                try:
                    existing_rev_ids = list(sheet.GetAdditionalRevisionIds())
                    original_count = len(existing_rev_ids)
                    
                    existing_rev_ids = [rid for rid in existing_rev_ids if rid not in revisions_to_remove]
                    
                    removed_count = original_count - len(existing_rev_ids)
                    
                    if removed_count == 0:
                        skipped_count += 1
                    else:
                        dotnet_list = DotNetList[ElementId]()
                        for rev_id in existing_rev_ids:
                            dotnet_list.Add(rev_id)
                        
                        sheet.SetAdditionalRevisionIds(dotnet_list)
                        success_count += 1
                    
                except Exception as e:
                    error_count += 1
                    output.print_md("✗ {} - {}: {}".format(
                        sheet.SheetNumber,
                        sheet.Name,
                        str(e)
                    ))
            
            t.Commit()
            
        except Exception as ex:
            t.RollBack()
            output.print_md("ERROR: Transaction failed - {}".format(str(ex)))
            error_count += len(selected_sheets)
        
        msg = "Revision removal complete!\n\n"
        msg += "Removed: {}\n".format(success_count)
        msg += "Skipped: {}\n".format(skipped_count)
        msg += "Errors: {}".format(error_count)
        
        forms.alert(msg, title="Complete")
        
        self.result = True
        self.btn_remove.IsEnabled = True
        self.btn_remove.Content = "Remove Revisions"


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

all_revisions = get_all_revisions()
all_sheets = get_all_sheets()

if not all_revisions:
    forms.alert('No revisions found in the project', exitscript=True)

if not all_sheets:
    forms.alert('No sheets found in the project', exitscript=True)

output.print_md("**Found {} revisions**".format(len(all_revisions)))
output.print_md("**Found {} sheets**".format(len(all_sheets)))

window = RevisionManagerWindow(all_revisions, all_sheets, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Operation Completed Successfully")
else:
    output.print_md("### Operation Cancelled")