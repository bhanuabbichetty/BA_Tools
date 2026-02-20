# -*- coding: utf-8 -*-
"""
Transfer Filters
Transfer view filters between open projects with override option
"""
__title__ = 'Transfer\nFilters'
__doc__ = 'Transfer filters between projects'

import clr
import os

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import script, forms
import System
from System.Windows.Markup import XamlReader
from System.Windows import Window
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection
from System.Collections.Generic import List

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
output = script.get_output()


# ==============================================================================
# DATA CLASS
# ==============================================================================

class FilterItem:
    """Represents a parameter filter"""
    def __init__(self, name, param_filter):
        self.Name = name
        self.Filter = param_filter
        self._isSelected = False
        
        # Get rule count
        self.RuleCount = 0
        try:
            filter_rules = param_filter.GetFilters()
            self.RuleCount = filter_rules.Count if filter_rules else 0
        except:
            pass
    
    @property
    def IsSelected(self):
        return self._isSelected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class TransferFiltersWindow(Window):
    def __init__(self, xaml_path, script_dir):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.doc_from = None
        self.doc_to = None
        self.all_filters = []
        
        # Get open projects (exclude families and linked docs)
        self.open_projects = {d.Title: d for d in app.Documents 
                             if not d.IsFamilyDocument and not d.IsLinked}
        
        # Get controls
        self.imgLogo = self._window.FindName("imgLogo")
        self.btnClose = self._window.FindName("btnClose")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Left panel
        self.cmbCopyFrom = self._window.FindName("cmbCopyFrom")
        self.cmbCopyTo = self._window.FindName("cmbCopyTo")
        self.chkOverride = self._window.FindName("chkOverride")
        
        # Right panel
        self.txtFilterCount = self._window.FindName("txtFilterCount")
        self.txtSelectedCount = self._window.FindName("txtSelectedCount")
        self.txtSearch = self._window.FindName("txtSearch")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnSelectNone = self._window.FindName("btnSelectNone")
        self.lstFilters = self._window.FindName("lstFilters")
        
        # Footer
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnTransfer = self._window.FindName("btnTransfer")
        
        # Setup
        self.LoadLogo()
        self.LoadProjects()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
    
    def LoadLogo(self):
        """Load BA logo"""
        try:
            import System.Windows.Media.Imaging as Imaging
            
            logo_path = os.path.join(self.script_dir, "BA_logo.png")
            if not os.path.exists(logo_path):
                logo_path = os.path.join(self.script_dir, "icon.png")
            
            if os.path.exists(logo_path):
                bitmap = Imaging.BitmapImage()
                bitmap.BeginInit()
                bitmap.UriSource = System.Uri(logo_path)
                bitmap.CacheOption = Imaging.BitmapCacheOption.OnLoad
                bitmap.EndInit()
                self.imgLogo.Source = bitmap
        except:
            pass
    
    def LoadProjects(self):
        """Load open projects into ComboBoxes"""
        if len(self.open_projects) < 2:
            self.txtStatus.Text = "Error: Need at least 2 open projects"
            return
        
        # Populate ComboBoxes
        for project_name in sorted(self.open_projects.keys()):
            self.cmbCopyFrom.Items.Add(project_name)
            self.cmbCopyTo.Items.Add(project_name)
        
        self.txtStatus.Text = "Ready - Select source and destination projects"
    
    def LoadFilters(self):
        """Load filters from source project"""
        if not self.doc_from:
            return
        
        self.txtStatus.Text = "Loading filters..."
        
        # Get all parameter filters from source project
        filters = FilteredElementCollector(self.doc_from)\
            .OfClass(ParameterFilterElement)\
            .ToElements()
        
        # Create filter items
        filter_list = []
        for f in sorted(filters, key=lambda x: x.Name):
            item = FilterItem(f.Name, f)
            filter_list.append(item)
        
        self.all_filters = filter_list
        self.RefreshFilterList()
        
        self.txtFilterCount.Text = "Found {} filters".format(len(filter_list))
        self.UpdateSelectedCount()
        self.txtStatus.Text = "Filters loaded - Select filters to transfer"
    
    def RefreshFilterList(self):
        """Refresh filter list based on search"""
        search_text = self.txtSearch.Text.lower() if self.txtSearch.Text else ""
        
        if search_text:
            filtered = [f for f in self.all_filters 
                       if search_text in f.Name.lower()]
        else:
            filtered = self.all_filters
        
        collection = ObservableCollection[object]()
        for filter_item in filtered:
            collection.Add(filter_item)
        
        self.lstFilters.ItemsSource = collection
    
    def UpdateSelectedCount(self):
        """Update selected filter count"""
        if self.lstFilters.ItemsSource:
            selected = sum(1 for f in self.lstFilters.ItemsSource if f.IsSelected)
            self.txtSelectedCount.Text = "{} filters selected".format(selected)
            
            # Enable/disable transfer button
            self.btnTransfer.IsEnabled = selected > 0 and self.doc_from and self.doc_to
    
    def RemoveSameNameFilters(self, selected_filter_names):
        """Remove filters with same names from destination"""
        # Get filters in destination
        filters_to = FilteredElementCollector(self.doc_to)\
            .OfClass(ParameterFilterElement)\
            .ToElements()
        
        removed_count = 0
        
        # Delete filters with same names
        for f in filters_to:
            if f.Name in selected_filter_names:
                try:
                    self.doc_to.Delete(f.Id)
                    removed_count += 1
                except:
                    pass
        
        return removed_count
    
    def TransferFilters(self):
        """Transfer selected filters"""
        # Get selected filters
        selected_filters = [f for f in self.lstFilters.ItemsSource if f.IsSelected]
        
        if not selected_filters:
            TaskDialog.Show("Error", "Please select filters to transfer")
            return
        
        # Get selected filter IDs and names
        selected_ids = [f.Filter.Id for f in selected_filters]
        selected_names = [f.Filter.Name for f in selected_filters]
        
        # Confirm
        message = "Transfer {} filter(s)?\n\n".format(len(selected_filters))
        message += "From: {}\n".format(self.doc_from.Title)
        message += "To: {}\n\n".format(self.doc_to.Title)
        
        if self.chkOverride.IsChecked:
            message += "Override: Yes (existing filters will be replaced)\n\n"
        else:
            message += "Override: No (duplicates will be numbered)\n\n"
        
        message += "Continue?"
        
        result = TaskDialog.Show("Confirm", message, 
                                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result != TaskDialogResult.Yes:
            return
        
        self._window.Close()
        
        # Start transfer
        output.print_md("# Transfer Filters")
        output.print_md("**From**: {}".format(self.doc_from.Title))
        output.print_md("**To**: {}".format(self.doc_to.Title))
        output.print_md("**Override**: {}".format("Yes" if self.chkOverride.IsChecked else "No"))
        output.print_md("---")
        
        transferred = 0
        updated = 0
        failed = 0
        
        with TransactionGroup(self.doc_to, "Transfer Filters") as tg:
            tg.Start()
            
            try:
                # Step 1: Remove existing filters if override enabled
                removed_count = 0
                if self.chkOverride.IsChecked:
                    with Transaction(self.doc_to, "Remove Existing Filters") as t:
                        t.Start()
                        try:
                            removed_count = self.RemoveSameNameFilters(selected_names)
                            t.Commit()
                            
                            if removed_count > 0:
                                output.print_md("### Removed existing filters")
                                output.print_md("- Removed {} filter(s) with matching names".format(removed_count))
                                output.print_md("")
                                
                        except Exception as e:
                            t.RollBack()
                            output.print_md("**Error removing filters**: {}".format(str(e)))
                            output.print_md("")
                
                # Step 2: Copy filters
                with Transaction(self.doc_to, "Copy Filters") as t:
                    t.Start()
                    try:
                        list_ids = List[ElementId](selected_ids)
                        copy_opts = CopyPasteOptions()
                        
                        ElementTransformUtils.CopyElements(
                            self.doc_from,
                            list_ids,
                            self.doc_to,
                            Transform.Identity,
                            copy_opts
                        )
                        
                        t.Commit()
                        output.print_md("### Copied filters")
                        
                    except Exception as e:
                        t.RollBack()
                        output.print_md("**Error copying filters**: {}".format(str(e)))
                        failed = len(selected_filters)
                
                tg.Assimilate()
                
                # Report individual filters
                output.print_md("")
                output.print_md("### Filters Transferred")
                output.print_md("---")
                
                for filter_item in selected_filters:
                    if self.chkOverride.IsChecked and filter_item.Name in selected_names:
                        output.print_md("- ✅ **Updated**: {} ({} rules)".format(
                            filter_item.Name, filter_item.RuleCount))
                        updated += 1
                    else:
                        output.print_md("- ✅ **Added**: {} ({} rules)".format(
                            filter_item.Name, filter_item.RuleCount))
                        transferred += 1
                
            except Exception as e:
                tg.RollBack()
                output.print_md("**Transaction group failed**: {}".format(str(e)))
                failed = len(selected_filters)
        
        # Summary
        output.print_md("")
        output.print_md("---")
        output.print_md("### 📊 Summary")
        output.print_md("**Added New**: {}".format(transferred))
        output.print_md("**Updated**: {}".format(updated))
        output.print_md("**Failed**: {}".format(failed))
        
        # Show dialog
        total = transferred + updated
        if total > 0:
            TaskDialog.Show("Complete",
                "Filter transfer complete!\n\n"
                "Added New: {}\n"
                "Updated: {}\n"
                "Failed: {}".format(transferred, updated, failed))
        else:
            TaskDialog.Show("Failed",
                "Filter transfer failed!\n\n"
                "Check output for details.")
    
    # EVENT HANDLERS
    def SetupEventHandlers(self):
        """Setup all event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbCopyFrom.SelectionChanged += self.OnCopyFromChanged
        self.cmbCopyTo.SelectionChanged += self.OnCopyToChanged
        self.txtSearch.TextChanged += self.OnSearchChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnSelectNone.Click += self.OnSelectNone
        self.btnTransfer.Click += self.OnTransfer
        self.lstFilters.PreviewMouseLeftButtonUp += self.OnFilterClicked
    
    def OnClose(self, sender, args):
        self._window.Close()
    
    def OnCopyFromChanged(self, sender, args):
        if self.cmbCopyFrom.SelectedItem:
            project_name = self.cmbCopyFrom.SelectedItem
            self.doc_from = self.open_projects[project_name]
            
            # Check if same project selected
            if self.doc_to and self.doc_from.Title == self.doc_to.Title:
                self.txtStatus.Text = "Error: Cannot transfer to same project"
                self.btnTransfer.IsEnabled = False
                return
            
            # Load filters
            self.LoadFilters()
    
    def OnCopyToChanged(self, sender, args):
        if self.cmbCopyTo.SelectedItem:
            project_name = self.cmbCopyTo.SelectedItem
            self.doc_to = self.open_projects[project_name]
            
            # Check if same project selected
            if self.doc_from and self.doc_from.Title == self.doc_to.Title:
                self.txtStatus.Text = "Error: Cannot transfer to same project"
                self.btnTransfer.IsEnabled = False
            else:
                self.txtStatus.Text = "Ready to transfer"
                self.UpdateSelectedCount()
    
    def OnSearchChanged(self, sender, args):
        self.RefreshFilterList()
    
    def OnSelectAll(self, sender, args):
        if self.lstFilters.ItemsSource:
            for item in self.lstFilters.ItemsSource:
                item.IsSelected = True
            self.lstFilters.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnSelectNone(self, sender, args):
        if self.lstFilters.ItemsSource:
            for item in self.lstFilters.ItemsSource:
                item.IsSelected = False
            self.lstFilters.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnTransfer(self, sender, args):
        self.TransferFilters()
    
    def OnFilterClicked(self, sender, args):
        """Called on any mouse-up in the filters list.
        TwoWay binding has already written the new IsSelected value by this point,
        so scheduling UpdateSelectedCount via the dispatcher picks up the correct state."""
        self._window.Dispatcher.BeginInvoke(
            System.Windows.Threading.DispatcherPriority.Background,
            System.Action(self.UpdateSelectedCount)
        )
    
    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get paths
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, 'TransferFilters.xaml')

# Check XAML exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected: {}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Check if at least 2 projects are open
open_projects = [d for d in app.Documents if not d.IsFamilyDocument and not d.IsLinked]
if len(open_projects) < 2:
    forms.alert(
        "This tool requires at least 2 projects to be open.\n\n"
        "Currently open: {} project(s)".format(len(open_projects)),
        title="Not Enough Projects",
        exitscript=True
    )

# Show window
try:
    window = TransferFiltersWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)), title="Error")
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
