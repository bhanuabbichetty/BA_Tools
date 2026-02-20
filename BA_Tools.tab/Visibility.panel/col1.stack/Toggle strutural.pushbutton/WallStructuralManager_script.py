"""Wall Structural Manager - Fixed for pyRevit"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from System.Windows.Markup import XamlReader
from System.IO import StreamReader
from System.Collections.ObjectModel import ObservableCollection
import System
import os

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

class WallData(object):
    """Simple wall data class"""
    
    def __init__(self, element, id, structural, wall_type, level, length):
        self.Element = element
        self.Id = str(id)
        self.Structural = "YES" if structural else "NO"
        self.IsStructural = structural
        self.WallType = wall_type
        self.Level = level
        self.Length = "{:.2f}".format(length * 0.3048)
        self.IsSelected = False

class WallStructuralWindow:
    
    def __init__(self):
        self.walls_data = []
        self.LoadXaml()
        self.LoadWalls()
        self.SetupEvents()
        self.UpdateStats()
        
    def LoadXaml(self):
        script_dir = os.path.dirname(__file__)
        xaml_file = os.path.join(script_dir, 'WallStructuralManager.xaml')
        
        if not os.path.exists(xaml_file):
            TaskDialog.Show("Error", "XAML file not found at: " + xaml_file)
            return
        
        # Use StreamReader for proper XAML loading
        stream = StreamReader(xaml_file)
        self.ui = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        # Get controls
        self.stats_text = self.ui.FindName("StatsText")
        self.filter_combo = self.ui.FindName("FilterCombo")
        self.search_box = self.ui.FindName("SearchBox")
        self.walls_grid = self.ui.FindName("WallsGrid")
        self.select_all_btn = self.ui.FindName("SelectAllBtn")
        self.deselect_all_btn = self.ui.FindName("DeselectAllBtn")
        self.make_structural_btn = self.ui.FindName("MakeStructuralBtn")
        self.make_non_structural_btn = self.ui.FindName("MakeNonStructuralBtn")
        self.close_btn = self.ui.FindName("CloseBtn")
        
        # Setup filter combo
        self.filter_combo.Items.Add("All Walls")
        self.filter_combo.Items.Add("Structural Only")
        self.filter_combo.Items.Add("Non-Structural Only")
        self.filter_combo.SelectedIndex = 0
        
    def LoadWalls(self):
        collector = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Walls)\
            .WhereElementIsNotElementType()
        
        for wall in collector:
            try:
                struct_param = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
                if not struct_param:
                    continue
                    
                is_structural = struct_param.AsInteger() == 1
                
                wall_type = doc.GetElement(wall.GetTypeId())
                type_name = wall_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if wall_type else "Unknown"
                
                level_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
                level_name = level_param.AsValueString() if level_param else "Unknown"
                
                length_param = wall.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
                length = length_param.AsDouble() if length_param else 0
                
                wall_data = WallData(wall, wall.Id.IntegerValue, is_structural, type_name, level_name, length)
                self.walls_data.append(wall_data)
            except:
                continue
        
        self.RefreshGrid()
        
    def RefreshGrid(self):
        filter_idx = self.filter_combo.SelectedIndex
        search_text = self.search_box.Text.lower() if self.search_box.Text else ""
        
        filtered = []
        for wall_data in self.walls_data:
            if filter_idx == 1 and not wall_data.IsStructural:
                continue
            elif filter_idx == 2 and wall_data.IsStructural:
                continue
            
            if search_text:
                searchable = "{} {} {}".format(wall_data.Id, wall_data.WallType, wall_data.Level).lower()
                if search_text not in searchable:
                    continue
            
            filtered.append(wall_data)
        
        self.walls_grid.ItemsSource = ObservableCollection[WallData](filtered)
        self.UpdateStats()
        
    def UpdateStats(self):
        total = len(self.walls_data)
        structural = sum(1 for w in self.walls_data if w.IsStructural)
        non_structural = total - structural
        
        selected = 0
        if self.walls_grid.ItemsSource:
            selected = sum(1 for item in self.walls_grid.ItemsSource if item.IsSelected)
        
        stats = "Total: {}  |  Structural: {} ({:.1f}%)  |  Non-Structural: {} ({:.1f}%)  |  Selected: {}".format(
            total,
            structural, (structural * 100.0 / total) if total > 0 else 0,
            non_structural, (non_structural * 100.0 / total) if total > 0 else 0,
            selected
        )
        self.stats_text.Text = stats
        
    def SetupEvents(self):
        self.filter_combo.SelectionChanged += self.OnFilterChanged
        self.search_box.TextChanged += self.OnSearchChanged
        self.select_all_btn.Click += self.OnSelectAll
        self.deselect_all_btn.Click += self.OnDeselectAll
        self.make_structural_btn.Click += self.OnMakeStructural
        self.make_non_structural_btn.Click += self.OnMakeNonStructural
        self.close_btn.Click += self.OnClose
        # Wire drag handler for borderless window
        header_border = self.ui.FindName("headerDragArea")
        if header_border:
            header_border.MouseLeftButtonDown += self.OnHeaderDrag
    
    def OnHeaderDrag(self, sender, args):
        """Allow dragging the borderless window by its title bar"""
        try:
            self.ui.DragMove()
        except:
            pass
        
    def OnFilterChanged(self, sender, args):
        self.RefreshGrid()
        
    def OnSearchChanged(self, sender, args):
        self.RefreshGrid()
        
    def OnSelectAll(self, sender, args):
        if self.walls_grid.ItemsSource:
            for item in self.walls_grid.ItemsSource:
                item.IsSelected = True
        self.walls_grid.Items.Refresh()
        self.UpdateStats()
        
    def OnDeselectAll(self, sender, args):
        if self.walls_grid.ItemsSource:
            for item in self.walls_grid.ItemsSource:
                item.IsSelected = False
        self.walls_grid.Items.Refresh()
        self.UpdateStats()
        
    def GetSelectedWalls(self):
        selected = []
        if self.walls_grid.ItemsSource:
            for item in self.walls_grid.ItemsSource:
                if item.IsSelected:
                    selected.append(item.Element)
        return selected
        
    def OnMakeStructural(self, sender, args):
        selected = self.GetSelectedWalls()
        if not selected:
            TaskDialog.Show("Error", "Please select walls to modify")
            return
        
        result = TaskDialog.Show("Confirm", 
            "Make {} wall(s) STRUCTURAL?".format(len(selected)),
            TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result == TaskDialogResult.Yes:
            self.ToggleStructural(selected, True)
            
    def OnMakeNonStructural(self, sender, args):
        selected = self.GetSelectedWalls()
        if not selected:
            TaskDialog.Show("Error", "Please select walls to modify")
            return
        
        result = TaskDialog.Show("Confirm",
            "Make {} wall(s) NON-STRUCTURAL?".format(len(selected)),
            TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result == TaskDialogResult.Yes:
            self.ToggleStructural(selected, False)
            
    def ToggleStructural(self, walls, make_structural):
        t = Transaction(doc, "Toggle Wall Structural Status")
        t.Start()
        
        success = 0
        errors = 0
        
        try:
            for wall in walls:
                try:
                    param = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
                    if param and not param.IsReadOnly:
                        param.Set(1 if make_structural else 0)
                        success += 1
                    else:
                        errors += 1
                except:
                    errors += 1
            
            t.Commit()
            
            # Reload data
            self.walls_data = []
            self.LoadWalls()
            
            status = "STRUCTURAL" if make_structural else "NON-STRUCTURAL"
            TaskDialog.Show("Complete",
                "Successfully modified {} wall(s) to {}\n{} wall(s) failed".format(success, status, errors))
                
        except Exception as e:
            t.RollBack()
            TaskDialog.Show("Error", "Transaction failed: " + str(e))
            
    def OnClose(self, sender, args):
        self.ui.Close()
        
    def Show(self):
        self.ui.ShowDialog()

# Main
if __name__ == '__main__':
    try:
        window = WallStructuralWindow()
        window.Show()
    except Exception as e:
        TaskDialog.Show("Error", str(e))
        import traceback
        print(traceback.format_exc())
