# -*- coding: utf-8 -*-
"""
Set Comment Values - WPF Modern UI
Select category, level, filter by type, and assign comment values
"""
__title__ = 'Set Comment\nValues'
__doc__ = 'Assign comment values to filtered elements by type and level'

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
from System.Windows import Window, Visibility
from System.IO import StreamReader

doc = revit.doc
output = script.get_output()


# ==============================================================================
# DATA COLLECTION FUNCTIONS
# ==============================================================================

def get_all_levels():
    """Get all levels sorted by elevation"""
    levels = FilteredElementCollector(doc)\
        .OfClass(Level)\
        .WhereElementIsNotElementType()\
        .ToElements()
    return sorted(levels, key=lambda l: l.Elevation)


def get_elements_by_category_and_level(category, level):
    """Get elements filtered by category and level"""
    all_elements = FilteredElementCollector(doc)\
        .OfCategory(category)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    filtered = []
    for elem in all_elements:
        elem_level_id = None
        
        # Try multiple level parameters in order of priority
        try:
            level_param = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
            if level_param and level_param.HasValue:
                elem_level_id = level_param.AsElementId()
        except:
            pass
        
        if not elem_level_id or elem_level_id == ElementId.InvalidElementId:
            try:
                level_param = elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
                if level_param and level_param.HasValue:
                    elem_level_id = level_param.AsElementId()
            except:
                pass
        
        if not elem_level_id or elem_level_id == ElementId.InvalidElementId:
            try:
                level_param = elem.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
                if level_param and level_param.HasValue:
                    elem_level_id = level_param.AsElementId()
            except:
                pass
        
        # For walls, check base constraint
        if not elem_level_id or elem_level_id == ElementId.InvalidElementId:
            try:
                if hasattr(elem, 'WallType'):
                    level_param = elem.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
                    if level_param and level_param.HasValue:
                        elem_level_id = level_param.AsElementId()
            except:
                pass
        
        if elem_level_id and elem_level_id == level.Id:
            filtered.append(elem)
    
    return filtered


def group_by_type(elements):
    """Group elements by their type"""
    type_dict = {}
    for elem in elements:
        type_id = elem.GetTypeId()
        if type_id == ElementId.InvalidElementId:
            continue
        elem_type = doc.GetElement(type_id)
        if elem_type:
            type_param = elem_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            if type_param:
                type_name = type_param.AsString()
                if type_name not in type_dict:
                    type_dict[type_name] = []
                type_dict[type_name].append(elem)
    return type_dict


def get_current_comment(elem):
    """Get current comment value from element"""
    comment_param = elem.LookupParameter("Comments")
    if comment_param and comment_param.HasValue:
        comment_value = comment_param.AsString()
        return comment_value if comment_value else ""
    return ""


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class SetCommentWindow(Window):
    def __init__(self, xaml_path, document):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Data
        self.doc = document
        self.selected_category = None
        self.selected_level = None
        self.selected_type = None
        self.filtered_elements = []
        self.type_dict = {}
        self.result = False
        
        # Category mapping
        self.category_map = {
            'Walls': BuiltInCategory.OST_Walls,
            'Doors': BuiltInCategory.OST_Doors,
            'Windows': BuiltInCategory.OST_Windows,
            'Structural Framing': BuiltInCategory.OST_StructuralFraming,
            'Structural Columns': BuiltInCategory.OST_StructuralColumns,
            'Floors': BuiltInCategory.OST_Floors,
            'Furniture': BuiltInCategory.OST_Furniture,
            'Generic Models': BuiltInCategory.OST_GenericModel,
        }
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.cmbCategory = self._window.FindName("cmbCategory")
        self.cmbLevel = self._window.FindName("cmbLevel")
        self.cmbType = self._window.FindName("cmbType")
        self.txtElementCount = self._window.FindName("txtElementCount")
        self.txtElementInfo = self._window.FindName("txtElementInfo")
        self.headerDragArea = self._window.FindName("headerDragArea")

        # Method controls
        self.cmbMethod = self._window.FindName("cmbMethod")
        self.inputContainer = self._window.FindName("inputContainer")
        
        # Input panels
        self.panelSingleValue = self._window.FindName("panelSingleValue")
        self.panelSequential = self._window.FindName("panelSequential")
        self.panelSequentialPrefix = self._window.FindName("panelSequentialPrefix")
        self.panelCSV = self._window.FindName("panelCSV")
        self.panelMarkOrder = self._window.FindName("panelMarkOrder")
        
        # Input fields
        self.txtSingleValue = self._window.FindName("txtSingleValue")
        self.txtSeqStart = self._window.FindName("txtSeqStart")
        self.txtSeqStep = self._window.FindName("txtSeqStep")
        self.txtPrefixSeqStart = self._window.FindName("txtPrefixSeqStart")
        self.txtPrefixSeqStep = self._window.FindName("txtPrefixSeqStep")
        self.txtPrefix = self._window.FindName("txtPrefix")
        self.txtCSV = self._window.FindName("txtCSV")
        self.txtMarkPrefix = self._window.FindName("txtMarkPrefix")
        
        # Preview and actions
        self.txtPreview = self._window.FindName("txtPreview")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnPreview = self._window.FindName("btnPreview")
        self.btnApply = self._window.FindName("btnApply")
        
        # Initialize
        self.InitializeData()
        self.SetupEventHandlers()
    
    def InitializeData(self):
        """Initialize dropdowns"""
        # Categories
        for cat_name in sorted(self.category_map.keys()):
            self.cmbCategory.Items.Add(cat_name)
        
        # Levels
        self.levels = get_all_levels()
        for level in self.levels:
            display = "{} (Elev: {:.2f})".format(level.Name, level.Elevation)
            self.cmbLevel.Items.Add(display)
        
        # Methods
        self.cmbMethod.Items.Add("Single Value")
        self.cmbMethod.Items.Add("Sequential Numbers")
        self.cmbMethod.Items.Add("Sequential with Prefix")
        self.cmbMethod.Items.Add("Comma-Separated")
        self.cmbMethod.Items.Add("Based on Mark Order")
        self.cmbMethod.SelectedIndex = 0
    
    def SetupEventHandlers(self):
        """Setup event handlers"""
        self.btnClose.Click += self.OnClose
        self.cmbCategory.SelectionChanged += self.OnCategoryChanged
        self.cmbLevel.SelectionChanged += self.OnLevelChanged
        self.cmbType.SelectionChanged += self.OnTypeChanged
        self.cmbMethod.SelectionChanged += self.OnMethodChanged
        self.btnPreview.Click += self.OnGeneratePreview
        self.btnApply.Click += self.OnApplyComments
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
            
    def OnClose(self, sender, args):
        """Close window"""
        self._window.DialogResult = False
        self._window.Close()
    
    def OnCategoryChanged(self, sender, args):
        """When category changes"""
        if self.cmbCategory.SelectedIndex < 0:
            return
        
        self.cmbLevel.IsEnabled = True
        self.cmbType.IsEnabled = False
        self.cmbType.Items.Clear()
        self.filtered_elements = []
        self.UpdateElementInfo()
        self.btnPreview.IsEnabled = False
        self.btnApply.IsEnabled = False
    
    def OnLevelChanged(self, sender, args):
        """When level changes"""
        if self.cmbCategory.SelectedIndex < 0 or self.cmbLevel.SelectedIndex < 0:
            return
        
        cat_name = self.cmbCategory.SelectedItem.ToString()
        self.selected_category = self.category_map[cat_name]
        self.selected_level = self.levels[self.cmbLevel.SelectedIndex]
        
        # Get elements
        elements = get_elements_by_category_and_level(self.selected_category, self.selected_level)
        
        if not elements:
            forms.alert(
                "No {} found on {}".format(cat_name, self.selected_level.Name),
                title="No Elements"
            )
            return
        
        # Group by type
        self.type_dict = group_by_type(elements)
        
        if not self.type_dict:
            return
        
        # Populate type combo
        self.cmbType.Items.Clear()
        for type_name in sorted(self.type_dict.keys()):
            count = len(self.type_dict[type_name])
            self.cmbType.Items.Add("{} ({})".format(type_name, count))
        
        self.cmbType.IsEnabled = True
        self.UpdateElementInfo()
    
    def OnTypeChanged(self, sender, args):
        """When type changes"""
        if self.cmbType.SelectedIndex < 0:
            return
        
        selected = self.cmbType.SelectedItem.ToString()
        type_name = selected.split(' (')[0]
        self.selected_type = type_name
        self.filtered_elements = self.type_dict[type_name]
        
        self.UpdateElementInfo()
        self.btnPreview.IsEnabled = True
        self.btnApply.IsEnabled = True
        self.txtStatus.Text = "Ready to assign comments to {} elements".format(len(self.filtered_elements))
    
    def UpdateElementInfo(self):
        """Update element info display"""
        if not self.filtered_elements:
            self.txtElementInfo.Text = "Select category > level > type"
            self.txtElementCount.Text = "0 elements"
            return
        
        count = len(self.filtered_elements)
        self.txtElementCount.Text = "{} element{}".format(count, "s" if count != 1 else "")
        
        info = "FOUND {} ELEMENTS\n{}\n\n".format(count, "=" * 60)
        for i, elem in enumerate(self.filtered_elements[:20], 1):
            comment = get_current_comment(elem)
            info += "{}. ID: {} | Comment: {}\n".format(
                i, elem.Id, comment if comment else "(empty)"
            )
        
        if len(self.filtered_elements) > 20:
            info += "\n... {} more elements".format(len(self.filtered_elements) - 20)
        
        self.txtElementInfo.Text = info
    
    def OnMethodChanged(self, sender, args):
        """When method changes"""
        method = self.cmbMethod.SelectedItem.ToString()
        
        # Hide all panels
        self.panelSingleValue.Visibility = Visibility.Collapsed
        self.panelSequential.Visibility = Visibility.Collapsed
        self.panelSequentialPrefix.Visibility = Visibility.Collapsed
        self.panelCSV.Visibility = Visibility.Collapsed
        self.panelMarkOrder.Visibility = Visibility.Collapsed
        
        # Show relevant panel
        if method == "Single Value":
            self.panelSingleValue.Visibility = Visibility.Visible
        elif method == "Sequential Numbers":
            self.panelSequential.Visibility = Visibility.Visible
        elif method == "Sequential with Prefix":
            self.panelSequentialPrefix.Visibility = Visibility.Visible
        elif method == "Comma-Separated":
            self.panelCSV.Visibility = Visibility.Visible
        elif method == "Based on Mark Order":
            self.panelMarkOrder.Visibility = Visibility.Visible
    
    def GetNewComments(self):
        """Generate new comment values based on selected method"""
        method = self.cmbMethod.SelectedItem.ToString()
        count = len(self.filtered_elements)
        
        if method == "Single Value":
            value = self.txtSingleValue.Text.strip()
            if not value:
                forms.alert("Please enter a value", title="Validation Error")
                return None
            return [value] * count
        
        elif method == "Sequential Numbers":
            try:
                start = int(self.txtSeqStart.Text)
                step = int(self.txtSeqStep.Text)
                return [str(start + i * step) for i in range(count)]
            except:
                forms.alert("Invalid number format", title="Validation Error")
                return None
        
        elif method == "Sequential with Prefix":
            try:
                prefix = self.txtPrefix.Text.strip()
                start = int(self.txtPrefixSeqStart.Text)
                step = int(self.txtPrefixSeqStep.Text)
                return ["{}-{}".format(prefix, start + i * step) for i in range(count)]
            except:
                forms.alert("Invalid input", title="Validation Error")
                return None
        
        elif method == "Comma-Separated":
            text = self.txtCSV.Text.strip()
            if not text:
                forms.alert("Please enter values", title="Validation Error")
                return None
            
            values = [v.strip() for v in text.replace('\n', ',').split(',') if v.strip()]
            if len(values) != count:
                forms.alert(
                    "Value mismatch: {} values provided, {} elements selected".format(
                        len(values), count
                    ),
                    title="Validation Error"
                )
                return None
            return values
        
        elif method == "Based on Mark Order":
            prefix = self.txtMarkPrefix.Text.strip()
            
            marked_elements = []
            for elem in self.filtered_elements:
                mark_param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                if mark_param and mark_param.HasValue:
                    mark = mark_param.AsString()
                    if mark:
                        marked_elements.append((mark, elem))
            
            if not marked_elements:
                forms.alert("No elements have Mark values", title="Validation Error")
                return None
            
            # Natural sort by Mark
            def alphanum_key(s):
                parts = re.split(r'(\d+)', s)
                return tuple(int(p) if p.isdigit() else p.lower() for p in parts)
            
            marked_elements.sort(key=lambda x: alphanum_key(x[0]))
            
            elem_to_comment = {}
            for mark, elem in marked_elements:
                match = re.search(r'(\d+)(?!.*\d)', mark)  # last number
                if match:
                    num_int = int(match.group(1))
                    num_padded = str(num_int).zfill(3)
                    elem_to_comment[elem.Id] = "{}-{}".format(prefix, num_padded)
                else:
                    elem_to_comment[elem.Id] = prefix
            
            return [elem_to_comment.get(elem.Id, "") for elem in self.filtered_elements]
        
        return None
    
    def OnGeneratePreview(self, sender, args):
        """Generate preview of comment assignments"""
        if not self.filtered_elements:
            return
        
        new_comments = self.GetNewComments()
        if not new_comments:
            return
        
        preview = "PREVIEW: {} ELEMENTS\n{}\n\n".format(
            len(self.filtered_elements), "=" * 60
        )
        
        for i, (elem, new_comment) in enumerate(zip(self.filtered_elements[:15], new_comments[:15]), 1):
            old = get_current_comment(elem)
            preview += "{}. ID: {} | {} -> {}\n".format(
                i, elem.Id, old if old else "(empty)", new_comment
            )
        
        if len(self.filtered_elements) > 15:
            preview += "\n... {} more elements".format(len(self.filtered_elements) - 15)
        
        self.txtPreview.Text = preview
    
    def OnApplyComments(self, sender, args):
        """Apply comment values to elements"""
        if not self.filtered_elements:
            return
        
        new_comments = self.GetNewComments()
        if not new_comments:
            return
        
        # Confirm
        if not forms.alert(
            "Apply comment values to {} element(s)?".format(len(self.filtered_elements)),
            yes=True, no=True, title="Confirm"
        ):
            return
        
        # Update UI
        self.btnApply.IsEnabled = False
        self.btnApply.Content = "APPLYING..."
        self.txtStatus.Text = "Applying comments..."
        
        success = 0
        errors = 0
        
        # Apply comments
        with revit.Transaction("Set Comment Values"):
            for elem, comment in zip(self.filtered_elements, new_comments):
                try:
                    param = elem.LookupParameter("Comments")
                    if param and not param.IsReadOnly:
                        param.Set(comment)
                        success += 1
                        output.print_md("✓ ID: {} → {}".format(elem.Id, comment))
                    else:
                        errors += 1
                        output.print_md("✗ ID: {} - Parameter read-only or not found".format(elem.Id))
                except Exception as e:
                    errors += 1
                    output.print_md("✗ ID: {} - {}".format(elem.Id, str(e)))
        
        # Summary
        summary = "Comment values applied!\n\n"
        summary += "Success: {}\n".format(success)
        summary += "Errors: {}\n\n".format(errors)
        summary += "Check output window for details."
        
        forms.alert(summary, title="Complete")
        
        output.print_md("### ✅ Comment Values Applied")
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
xaml_path = os.path.join(script_dir, "SetCommentValues.xaml")

# Check if XAML file exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected location:\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
window = SetCommentWindow(xaml_path, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Comments Applied Successfully")
else:
    output.print_md("### Operation Cancelled or Closed")
