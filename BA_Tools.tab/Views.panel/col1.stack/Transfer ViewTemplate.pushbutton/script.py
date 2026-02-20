# -*- coding: utf-8 -*-
"""
Transfer View Templates
Transfer view templates between open projects with override option
"""
__title__ = 'Transfer\nTemplates'
__doc__ = 'Transfer view templates between projects'

import clr
import os
from collections import defaultdict

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

class ViewTemplateItem:
    """Represents a view template"""
    def __init__(self, name, view_template):
        self.Name = name
        self.ViewTemplate = view_template
        self._isSelected = False
    
    @property
    def IsSelected(self):
        return self._isSelected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class TransferViewTemplatesWindow(Window):
    def __init__(self, xaml_path, script_dir):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.doc_from = None
        self.doc_to = None
        self.all_templates = []
        
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
        self.txtTemplateCount = self._window.FindName("txtTemplateCount")
        self.txtSelectedCount = self._window.FindName("txtSelectedCount")
        self.txtFilter = self._window.FindName("txtFilter")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnSelectNone = self._window.FindName("btnSelectNone")
        self.lstTemplates = self._window.FindName("lstTemplates")
        
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
    
    def LoadViewTemplates(self):
        """Load view templates from source project"""
        if not self.doc_from:
            return
        
        self.txtStatus.Text = "Loading view templates..."
        
        # Get all view templates from source project
        view_templates = [v for v in FilteredElementCollector(self.doc_from).OfClass(View).ToElements() 
                         if v.IsTemplate]
        
        # Create template items
        template_list = []
        for vt in sorted(view_templates, key=lambda x: x.Name):
            item = ViewTemplateItem(vt.Name, vt)
            template_list.append(item)
        
        self.all_templates = template_list
        self.RefreshTemplateList()
        
        self.txtTemplateCount.Text = "Found {} view templates".format(len(template_list))
        self.UpdateSelectedCount()
        self.txtStatus.Text = "View templates loaded - Select templates to transfer"
    
    def RefreshTemplateList(self):
        """Refresh template list based on filter"""
        filter_text = self.txtFilter.Text.lower() if self.txtFilter.Text else ""
        
        if filter_text:
            filtered = [t for t in self.all_templates 
                       if filter_text in t.Name.lower()]
        else:
            filtered = self.all_templates
        
        collection = ObservableCollection[object]()
        for template in filtered:
            collection.Add(template)
        
        self.lstTemplates.ItemsSource = collection
    
    def UpdateSelectedCount(self):
        """Update selected template count"""
        if self.lstTemplates.ItemsSource:
            selected = sum(1 for t in self.lstTemplates.ItemsSource if t.IsSelected)
            self.txtSelectedCount.Text = "{} templates selected".format(selected)
            
            # Enable/disable transfer button
            self.btnTransfer.IsEnabled = selected > 0 and self.doc_from and self.doc_to
    
    def RemoveSameNameTemplates(self, selected_template_names):
        """Remove view templates with same names and track where they were used"""
        dict_used_templates = defaultdict(list)
        
        # Get view templates in destination
        view_templates_to = [v for v in FilteredElementCollector(self.doc_to).OfClass(View).ToElements() 
                            if v.IsTemplate]
        views_to = [v for v in FilteredElementCollector(self.doc_to).OfClass(View).ToElements() 
                   if not v.IsTemplate]
        
        # Find where templates are used
        for vt in view_templates_to:
            if vt.Name not in selected_template_names:
                continue
            
            # Find views using this template
            for v in views_to:
                vt_id = v.ViewTemplateId
                if vt_id and vt_id != ElementId(-1):
                    vt_name = self.doc_to.GetElement(vt_id).Name
                    if vt_name in selected_template_names:
                        dict_used_templates[vt_name].append(v.Id)
        
        # Delete templates with same names
        for vt in view_templates_to:
            if vt.Name in selected_template_names:
                if vt.Name not in dict_used_templates:
                    dict_used_templates[vt.Name] = []
                self.doc_to.Delete(vt.Id)
        
        return dict_used_templates
    
    def ReassignViewTemplates(self, dict_deleted_templates):
        """Reassign view templates to views that had them before"""
        for vt_name, view_ids in dict_deleted_templates.items():
            # Find new template with same name
            view_templates_to = [v for v in FilteredElementCollector(self.doc_to).OfClass(View).ToElements() 
                                if v.IsTemplate]
            new_vt = [v for v in view_templates_to if v.Name == vt_name]
            
            if new_vt:
                new_vt = new_vt[0]
                
                # Assign to views
                for view_id in view_ids:
                    view = self.doc_to.GetElement(view_id)
                    if view:
                        view.ViewTemplateId = new_vt.Id
    
    def TransferViewTemplates(self):
        """Transfer selected view templates"""
        # Get selected templates
        selected_templates = [t for t in self.lstTemplates.ItemsSource if t.IsSelected]
        
        if not selected_templates:
            TaskDialog.Show("Error", "Please select view templates to transfer")
            return
        
        # Get selected template IDs and names
        selected_ids = [t.ViewTemplate.Id for t in selected_templates]
        selected_names = [t.ViewTemplate.Name for t in selected_templates]
        
        # Confirm
        message = "Transfer {} view template(s)?\n\n".format(len(selected_templates))
        message += "From: {}\n".format(self.doc_from.Title)
        message += "To: {}\n\n".format(self.doc_to.Title)
        
        if self.chkOverride.IsChecked:
            message += "Override: Yes (existing templates will be replaced)\n\n"
        else:
            message += "Override: No (duplicates will be numbered)\n\n"
        
        message += "Continue?"
        
        result = TaskDialog.Show("Confirm", message, 
                                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result != TaskDialogResult.Yes:
            return
        
        self._window.Close()
        
        # Start transfer
        output.print_md("# Transfer View Templates")
        output.print_md("**From**: {}".format(self.doc_from.Title))
        output.print_md("**To**: {}".format(self.doc_to.Title))
        output.print_md("**Override**: {}".format("Yes" if self.chkOverride.IsChecked else "No"))
        output.print_md("---")
        
        transferred = 0
        updated = 0
        failed = 0
        
        with TransactionGroup(self.doc_to, "Transfer View Templates") as tg:
            tg.Start()
            
            try:
                # Step 1: Remove existing templates if override enabled
                dict_deleted_templates = {}
                if self.chkOverride.IsChecked:
                    with Transaction(self.doc_to, "Remove Existing Templates") as t:
                        t.Start()
                        try:
                            dict_deleted_templates = self.RemoveSameNameTemplates(selected_names)
                            t.Commit()
                            output.print_md("### Removed existing templates")
                            for name in dict_deleted_templates.keys():
                                views_count = len(dict_deleted_templates[name])
                                output.print_md("- {} (used in {} views)".format(name, views_count))
                            output.print_md("")
                        except Exception as e:
                            t.RollBack()
                            output.print_md("**Error removing templates**: {}".format(str(e)))
                            output.print_md("")
                
                # Step 2: Copy view templates
                with Transaction(self.doc_to, "Copy View Templates") as t:
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
                        output.print_md("### Copied view templates")
                    except Exception as e:
                        t.RollBack()
                        output.print_md("**Error copying templates**: {}".format(str(e)))
                        failed = len(selected_templates)
                
                # Step 3: Reassign templates if override enabled
                if self.chkOverride.IsChecked and dict_deleted_templates:
                    with Transaction(self.doc_to, "Reassign View Templates") as t:
                        t.Start()
                        try:
                            self.ReassignViewTemplates(dict_deleted_templates)
                            t.Commit()
                            output.print_md("")
                            output.print_md("### Reassigned templates to views")
                        except Exception as e:
                            t.RollBack()
                            output.print_md("**Error reassigning templates**: {}".format(str(e)))
                
                tg.Assimilate()
                
                # Report individual templates
                output.print_md("")
                output.print_md("### Templates Transferred")
                output.print_md("---")
                
                for template in selected_templates:
                    if template.Name in dict_deleted_templates:
                        output.print_md("- ✅ **Updated**: {}".format(template.Name))
                        updated += 1
                    else:
                        output.print_md("- ✅ **Added**: {}".format(template.Name))
                        transferred += 1
                
            except Exception as e:
                tg.RollBack()
                output.print_md("**Transaction group failed**: {}".format(str(e)))
                failed = len(selected_templates)
        
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
                "View template transfer complete!\n\n"
                "Added New: {}\n"
                "Updated: {}\n"
                "Failed: {}".format(transferred, updated, failed))
        else:
            TaskDialog.Show("Failed",
                "View template transfer failed!\n\n"
                "Check output for details.")
    
    # EVENT HANDLERS
    def SetupEventHandlers(self):
        """Setup all event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbCopyFrom.SelectionChanged += self.OnCopyFromChanged
        self.cmbCopyTo.SelectionChanged += self.OnCopyToChanged
        self.txtFilter.TextChanged += self.OnFilterChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnSelectNone.Click += self.OnSelectNone
        self.btnTransfer.Click += self.OnTransfer
        self.lstTemplates.SelectionChanged += self.OnTemplateSelectionChanged
    
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
            
            # Load templates
            self.LoadViewTemplates()
    
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
    
    def OnFilterChanged(self, sender, args):
        self.RefreshTemplateList()
    
    def OnSelectAll(self, sender, args):
        if self.lstTemplates.ItemsSource:
            for item in self.lstTemplates.ItemsSource:
                item.IsSelected = True
            self.lstTemplates.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnSelectNone(self, sender, args):
        if self.lstTemplates.ItemsSource:
            for item in self.lstTemplates.ItemsSource:
                item.IsSelected = False
            self.lstTemplates.Items.Refresh()
            self.UpdateSelectedCount()
    
    def OnTransfer(self, sender, args):
        self.TransferViewTemplates()
    
    def OnTemplateSelectionChanged(self, sender, args):
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
xaml_path = os.path.join(script_dir, 'TransferViewTemplates.xaml')

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
    window = TransferViewTemplatesWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)), title="Error")
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
