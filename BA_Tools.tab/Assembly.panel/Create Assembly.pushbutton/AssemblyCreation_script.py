# -*- coding: utf-8 -*-
"""
Assembly Creation from Walls
Create assemblies from walls with their hosted elements
"""
__title__ = 'Assembly\nCreation'
__doc__ = 'Create assemblies from walls with hosted elements'

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
from collections import defaultdict

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()


# ==============================================================================
# DATA CLASSES
# ==============================================================================

class CommentGroup:
    """Represents a group of walls with the same comment"""
    def __init__(self, comment, count):
        self.Comment = comment if comment else "<No Comment>"
        self.Count = count
        self._isSelected = False
    
    @property
    def IsSelected(self):
        return self._isSelected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value


class WallData:
    """Represents a wall with its properties"""
    def __init__(self, wall):
        self.Wall = wall
        self.WallId = str(wall.Id.IntegerValue)
        self._isSelected = False
        
        # Get wall comment
        comment_param = wall.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        self.Comment = comment_param.AsString() if comment_param and comment_param.AsString() else "<No Comment>"
        
        # Get wall type
        wall_type = doc.GetElement(wall.GetTypeId())
        self.WallType = wall_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if wall_type else "Unknown"
        
        # Get level
        level_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
        self.Level = level_param.AsValueString() if level_param else "Unknown"
        
        # Get length in meters
        length_param = wall.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
        if length_param:
            length_ft = length_param.AsDouble()
            self.Length = "{:.2f}".format(length_ft * 0.3048)
        else:
            self.Length = "0.00"
        
        # Count hosted elements
        self.HostedCount = self.CountHostedElements()
    
    @property
    def IsSelected(self):
        return self._isSelected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value
    
    def CountHostedElements(self):
        """Count elements hosted on this wall - using comprehensive detection"""
        count = 0
        try:
            wall_solid = None
            
            # Try to get solid geometry
            try:
                opt = Options()
                opt.ComputeReferences = True
                opt.DetailLevel = ViewDetailLevel.Fine
                geo = self.Wall.get_Geometry(opt)
                
                if geo:
                    for g in geo:
                        if isinstance(g, Solid) and g.Volume > 0:
                            wall_solid = g
                            break
            except:
                pass
            
            # Collect all non-type elements
            collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
            
            found_ids = set()
            
            for el in collector:
                if el.Id == self.Wall.Id:
                    continue
                
                el_id_int = el.Id.IntegerValue
                if el_id_int in found_ids:
                    continue
                
                # Method 1: Host-based
                try:
                    if hasattr(el, 'Host') and el.Host is not None and el.Host.Id == self.Wall.Id:
                        found_ids.add(el_id_int)
                        count += 1
                        continue
                except:
                    pass
                
                # Method 2: Face-based
                try:
                    if hasattr(el, 'HostFace') and el.HostFace is not None:
                        host_ref = el.HostFace
                        h_el = doc.GetElement(host_ref.ElementId)
                        if h_el and h_el.Id == self.Wall.Id:
                            found_ids.add(el_id_int)
                            count += 1
                            continue
                except:
                    pass
                
                # Method 3: Dependent elements
                try:
                    if el.Category:
                        cat_name = el.Category.Name
                        if cat_name in ["Doors", "Windows", "Generic Models", "Curtain Wall Mullions"]:
                            dependent_ids = self.Wall.GetDependentElements(None)
                            if el.Id in dependent_ids:
                                found_ids.add(el_id_int)
                                count += 1
                                continue
                except:
                    pass
                
                # Method 4: Geometry intersection (only if wall has solid)
                if wall_solid and el_id_int not in found_ids:
                    try:
                        el_opt = Options()
                        el_opt.ComputeReferences = True
                        el_opt.DetailLevel = ViewDetailLevel.Fine
                        el_geo = el.get_Geometry(el_opt)
                        
                        if el_geo:
                            for el_g in el_geo:
                                if isinstance(el_g, Solid) and el_g.Volume > 0:
                                    result = BooleanOperationsUtils.ExecuteBooleanOperation(
                                        wall_solid,
                                        el_g,
                                        BooleanOperationsType.Intersect
                                    )
                                    if result and result.Volume > 0:
                                        found_ids.add(el_id_int)
                                        count += 1
                                        break
                    except:
                        pass
        
        except:
            pass
        
        return count


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class AssemblyCreationWindow(Window):
    def __init__(self, xaml_path, script_dir):
        # Load XAML
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.script_dir = script_dir
        self.comment_groups = {}
        self.current_walls = []
        self.selected_comment = None
        
        # Get controls
        self.imgLogo = self._window.FindName("imgLogo")
        self.btnClose = self._window.FindName("btnClose")
        self.txtCommentFilter = self._window.FindName("txtCommentFilter")
        self.lstComments = self._window.FindName("lstComments")
        self.btnSelectAllComments = self._window.FindName("btnSelectAllComments")
        self.btnClearComments = self._window.FindName("btnClearComments")
        self.btnLoadWalls = self._window.FindName("btnLoadWalls")
        self.txtSelectedComment = self._window.FindName("txtSelectedComment")
        self.txtWallCount = self._window.FindName("txtWallCount")
        self.txtSelectedWallCount = self._window.FindName("txtSelectedWallCount")
        self.txtSearch = self._window.FindName("txtSearch")
        self.btnSelectAll = self._window.FindName("btnSelectAll")
        self.btnDeselectAll = self._window.FindName("btnDeselectAll")
        self.dgWalls = self._window.FindName("dgWalls")
        self.txtStatus = self._window.FindName("txtStatus")
        self.txtHostedInfo = self._window.FindName("txtHostedInfo")
        self.btnCreateAssemblies = self._window.FindName("btnCreateAssemblies")
        self.headerDragArea = self._window.FindName("headerDragArea")
        
        # Store original comment list
        self.all_comment_groups = []
        
        # Setup
        self.LoadLogo()
        self.LoadComments()
        self.SetupEventHandlers()
        self.headerDragArea.MouseLeftButtonDown += self.OnHeaderDrag

    def OnHeaderDrag(self, sender, args):
        """Allow window dragging from header"""
        self._window.DragMove()
        
        # Disable Create button initially
        self.btnCreateAssemblies.IsEnabled = False
    
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
    
    def LoadComments(self):
        """Load all unique wall comments"""
        self.txtStatus.Text = "Loading wall comments..."
        
        # Collect walls by comment
        walls_by_comment = defaultdict(list)
        
        collector = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Walls)\
            .WhereElementIsNotElementType()
        
        for wall in collector:
            try:
                # Get comment parameter
                comment_param = wall.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                comment = comment_param.AsString() if comment_param else ""
                
                if not comment:
                    comment = "<No Comment>"
                
                walls_by_comment[comment].append(wall)
            except:
                continue
        
        # Store for later use
        self.comment_groups = walls_by_comment
        
        # Create comment group list
        comment_list = []
        for comment, walls in sorted(walls_by_comment.items()):
            comment_list.append(CommentGroup(comment, len(walls)))
        
        self.all_comment_groups = comment_list
        self.lstComments.ItemsSource = comment_list
        
        self.txtStatus.Text = "Found {} unique comment values".format(len(comment_list))
    
    def RefreshCommentList(self):
        """Refresh comment list based on filter"""
        filter_text = self.txtCommentFilter.Text.lower() if self.txtCommentFilter.Text else ""
        
        if filter_text:
            filtered = [c for c in self.all_comment_groups 
                       if filter_text in c.Comment.lower()]
        else:
            filtered = self.all_comment_groups
        
        self.lstComments.ItemsSource = ObservableCollection[object](filtered)
    
    def LoadWallsForComment(self):
        """Load walls for selected comments (can be multiple)"""
        # Get selected comments
        selected_comments = []
        if self.lstComments.ItemsSource:
            for item in self.lstComments.ItemsSource:
                if item.IsSelected:
                    selected_comments.append(item.Comment)
        
        if not selected_comments:
            TaskDialog.Show("Error", "Please select at least one comment from the list")
            return
        
        self.txtStatus.Text = "Loading walls for {} comment(s)...".format(len(selected_comments))
        
        # Get walls for selected comments
        all_walls = []
        for comment in selected_comments:
            walls = self.comment_groups.get(comment, [])
            all_walls.extend(walls)
        
        # Create wall data objects
        self.current_walls = []
        for wall in all_walls:
            wall_data = WallData(wall)
            self.current_walls.append(wall_data)
        
        # Update grid
        self.RefreshWallsGrid()
        
        # Update UI
        if len(selected_comments) == 1:
            self.txtSelectedComment.Text = "Comment: {}".format(selected_comments[0])
        else:
            comment_names = ", ".join(selected_comments[:2])
            if len(selected_comments) > 2:
                comment_names += "..."
            self.txtSelectedComment.Text = "Comments: {}".format(comment_names)
        
        self.txtWallCount.Text = "{} walls loaded from {} comment(s)".format(
            len(self.current_walls), len(selected_comments))
        self.txtStatus.Text = "Walls loaded - Select walls to create assembly"
        
        # Enable create button if walls exist
        self.btnCreateAssemblies.IsEnabled = len(self.current_walls) > 0
    
    def RefreshWallsGrid(self):
        """Refresh the walls DataGrid"""
        search_text = self.txtSearch.Text.lower() if self.txtSearch.Text else ""
        
        if search_text:
            filtered = [w for w in self.current_walls 
                       if search_text in w.WallId.lower() 
                       or search_text in w.WallType.lower()
                       or search_text in w.Level.lower()]
        else:
            filtered = self.current_walls
        
        # Fix: Use proper ObservableCollection without type parameter
        from System.Collections.ObjectModel import ObservableCollection
        collection = ObservableCollection[object]()
        for wall in filtered:
            collection.Add(wall)
        
        self.dgWalls.ItemsSource = collection
        self.UpdateSelectionCount()
    
    def UpdateSelectionCount(self):
        """Update selected walls count"""
        if self.dgWalls.ItemsSource:
            selected = sum(1 for w in self.dgWalls.ItemsSource if w.IsSelected)
            self.txtSelectedWallCount.Text = "{} selected".format(selected)
        else:
            self.txtSelectedWallCount.Text = "0 selected"
    
    def get_solid(self, element):
        """Get solid geometry from element"""
        try:
            opt = Options()
            opt.ComputeReferences = True
            opt.DetailLevel = ViewDetailLevel.Fine
            geo = element.get_Geometry(opt)
            
            if geo:
                for g in geo:
                    if isinstance(g, Solid) and g.Volume > 0:
                        return g
        except:
            pass
        return None
    
    def GetHostedElements(self, wall):
        """Get all hosted and related elements for a wall - comprehensive method"""
        related = []
        related_ids = set()
        
        try:
            wall_solid = self.get_solid(wall)
            
            # Collect all non-type elements
            collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
            
            for el in collector:
                if el.Id == wall.Id:
                    continue
                
                # Skip if already found
                if el.Id.IntegerValue in related_ids:
                    continue
                
                # -----------------------------
                # 1️⃣ Host-based families (doors, windows, hosted fittings)
                # -----------------------------
                try:
                    if hasattr(el, 'Host') and el.Host is not None and el.Host.Id == wall.Id:
                        related.append(el.Id)
                        related_ids.add(el.Id.IntegerValue)
                        continue
                except:
                    pass
                
                # -----------------------------
                # 2️⃣ Face-based families
                # -----------------------------
                try:
                    if hasattr(el, 'HostFace') and el.HostFace is not None:
                        host_ref = el.HostFace
                        h_el = doc.GetElement(host_ref.ElementId)
                        if h_el and h_el.Id == wall.Id:
                            related.append(el.Id)
                            related_ids.add(el.Id.IntegerValue)
                            continue
                except:
                    pass
                
                # -----------------------------
                # 3️⃣ Elements cutting the wall
                # -----------------------------
                try:
                    cutters = wall.GetDependentElements(ElementCategoryFilter(BuiltInCategory.OST_GenericModel))
                    if cutters and el.Id in cutters:
                        related.append(el.Id)
                        related_ids.add(el.Id.IntegerValue)
                        continue
                except:
                    pass
                
                # -----------------------------
                # 4️⃣ Geometry intersection (if wall has solid)
                # -----------------------------
                if wall_solid:
                    try:
                        el_solid = self.get_solid(el)
                        if el_solid:
                            result = BooleanOperationsUtils.ExecuteBooleanOperation(
                                wall_solid,
                                el_solid,
                                BooleanOperationsType.Intersect
                            )
                            if result and result.Volume > 0:
                                related.append(el.Id)
                                related_ids.add(el.Id.IntegerValue)
                    except:
                        pass
        
        except Exception as e:
            output.print_md("Warning: Error finding hosted elements - {}".format(str(e)))
        
        return related
    
    def CreateAssemblies(self):
        """Create assemblies from selected walls - each wall gets assembly named from its comment"""
        # Get selected walls
        selected_walls_data = [w for w in self.dgWalls.ItemsSource if w.IsSelected]
        
        if not selected_walls_data:
            TaskDialog.Show("Error", "Please select walls to create assemblies")
            return
        
        # Confirm
        message = "Create {} assemblies?\n\n".format(len(selected_walls_data))
        message += "Each wall will create a separate assembly\n"
        message += "named after the wall's comment value.\n\n"
        message += "Walls Selected: {}\n".format(len(selected_walls_data))
        message += "Hosted elements will be included automatically.\n\n"
        message += "Continue?"
        
        result = TaskDialog.Show("Confirm", message, 
                                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        
        if result != TaskDialogResult.Yes:
            return
        
        self._window.Close()
        
        # Create assemblies
        output.print_md("# Assembly Creation")
        output.print_md("**Walls Selected**: {}".format(len(selected_walls_data)))
        output.print_md("**Each assembly named from wall's comment value**")
        output.print_md("---")
        
        created = 0
        failed = 0
        
        # Step 1: Create all assemblies first
        created_assemblies = []
        
        with Transaction(doc, "Create Assemblies") as t:
            t.Start()
            
            try:
                for wall_data in selected_walls_data:
                    wall = wall_data.Wall
                    wall_comment = wall_data.Comment
                    
                    try:
                        # Get hosted elements
                        hosted_ids = self.GetHostedElements(wall)
                        
                        # Create element set with wall and hosted elements
                        element_ids = System.Collections.Generic.List[ElementId]()
                        element_ids.Add(wall.Id)
                        
                        for hosted_id in hosted_ids:
                            if hosted_id not in element_ids:
                                element_ids.Add(hosted_id)
                        
                        output.print_md("### Assembly: **{}**".format(wall_comment))
                        output.print_md("- Wall ID: {}".format(wall.Id.IntegerValue))
                        output.print_md("- Total Elements: {}".format(element_ids.Count))
                        
                        # List hosted elements
                        if len(hosted_ids) > 0:
                            output.print_md("- Hosted Elements:")
                            for hosted_id in hosted_ids[:10]:  # Show first 10
                                hosted_elem = doc.GetElement(hosted_id)
                                if hosted_elem and hosted_elem.Category:
                                    output.print_md("  - {} (ID: {})".format(
                                        hosted_elem.Category.Name, 
                                        hosted_id.IntegerValue))
                            if len(hosted_ids) > 10:
                                output.print_md("  - ... and {} more".format(len(hosted_ids) - 10))
                        
                        # Create assembly instance
                        assembly = AssemblyInstance.Create(doc, element_ids, wall.Category.Id)
                        
                        if assembly:
                            # Store assembly and comment for renaming in next transaction
                            created_assemblies.append((assembly, wall_comment))
                            output.print_md("- ✅ **Created**")
                            created += 1
                        else:
                            output.print_md("- ❌ **Failed**: Could not create assembly")
                            failed += 1
                        
                        output.print_md("")
                            
                    except Exception as e:
                        output.print_md("- ❌ **Failed**: Wall {} - {}".format(
                            wall.Id.IntegerValue, str(e)))
                        output.print_md("")
                        failed += 1
                
                t.Commit()
                
            except Exception as e:
                t.RollBack()
                output.print_md("**Transaction failed**: {}".format(str(e)))
                failed = len(selected_walls_data)
                created_assemblies = []
        
        # Step 2: Rename assemblies in SEPARATE transaction (proven to work in RenameAssemblies tool)
        renamed = 0
        rename_failed = 0
        
        if len(created_assemblies) > 0:
            output.print_md("---")
            output.print_md("### Renaming Assemblies")
            output.print_md("---")
            
            with Transaction(doc, "Rename Assemblies") as t:
                t.Start()
                
                try:
                    for assembly, wall_comment in created_assemblies:
                        try:
                            # Rename using AssemblyTypeName property (proven method)
                            assembly.AssemblyTypeName = wall_comment
                            output.print_md("- ✅ **Renamed**: {}".format(wall_comment))
                            renamed += 1
                        except Exception as e:
                            output.print_md("- ⚠ **Rename Failed**: {} - {}".format(wall_comment, str(e)))
                            rename_failed += 1
                    
                    t.Commit()
                    
                except Exception as e:
                    t.RollBack()
                    output.print_md("**Renaming transaction failed**: {}".format(str(e)))
                    rename_failed = len(created_assemblies)
            
            output.print_md("")
        
        # Report
        output.print_md("---")
        output.print_md("### 📊 Summary")
        output.print_md("**Created**: {} assemblies".format(created))
        output.print_md("**Renamed**: {} assemblies".format(renamed))
        output.print_md("**Rename Failed**: {} assemblies".format(rename_failed))
        output.print_md("**Creation Failed**: {} assemblies".format(failed))
        
        if created > 0:
            if renamed == created:
                TaskDialog.Show("Complete", 
                    "Assembly creation complete!\n\n"
                    "Created: {} assemblies\n"
                    "All assemblies renamed successfully!\n\n"
                    "Each assembly is named from its wall's comment.".format(created))
            else:
                TaskDialog.Show("Partial Success", 
                    "Assembly creation complete!\n\n"
                    "Created: {} assemblies\n"
                    "Renamed: {} assemblies\n"
                    "Rename Failed: {}\n\n"
                    "You can use 'Rename Assemblies' tool to fix the names.".format(
                        created, renamed, rename_failed))
        else:
            TaskDialog.Show("Failed", 
                "Assembly creation failed!\n\n"
                "Failed: {}\n\n"
                "Check output window for details.".format(failed))
    
    # EVENT HANDLERS
    def SetupEventHandlers(self):
        """Setup all event handlers"""
        self.btnClose.Click += self.OnClose
        self.txtCommentFilter.TextChanged += self.OnCommentFilterChanged
        self.btnSelectAllComments.Click += self.OnSelectAllComments
        self.btnClearComments.Click += self.OnClearComments
        self.btnLoadWalls.Click += self.OnLoadWalls
        self.txtSearch.TextChanged += self.OnSearchChanged
        self.btnSelectAll.Click += self.OnSelectAll
        self.btnDeselectAll.Click += self.OnDeselectAll
        self.btnCreateAssemblies.Click += self.OnCreateAssemblies
        self.dgWalls.CellEditEnding += self.OnCellEditEnding
    
    def OnCellEditEnding(self, sender, args):
        """Update selection count when checkbox is edited"""
        # Use dispatcher to update after edit completes
        self._window.Dispatcher.BeginInvoke(
            System.Windows.Threading.DispatcherPriority.Background,
            System.Action(self.UpdateSelectionCount)
        )
    
    def OnClose(self, sender, args):
        """Close window"""
        self._window.Close()
    
    def OnCommentFilterChanged(self, sender, args):
        """Filter comment list"""
        self.RefreshCommentList()
    
    def OnSelectAllComments(self, sender, args):
        """Select all visible comments"""
        if self.lstComments.ItemsSource:
            for item in self.lstComments.ItemsSource:
                item.IsSelected = True
            self.lstComments.Items.Refresh()
    
    def OnClearComments(self, sender, args):
        """Clear all comment selections"""
        if self.lstComments.ItemsSource:
            for item in self.lstComments.ItemsSource:
                item.IsSelected = False
            self.lstComments.Items.Refresh()
    
    def OnLoadWalls(self, sender, args):
        """Load walls for selected comment"""
        self.LoadWallsForComment()
    
    def OnSearchChanged(self, sender, args):
        """Search text changed"""
        self.RefreshWallsGrid()
    
    def OnSelectAll(self, sender, args):
        """Select all visible walls"""
        if self.dgWalls.ItemsSource:
            for wall in self.dgWalls.ItemsSource:
                wall.IsSelected = True
            self.dgWalls.Items.Refresh()
            self.UpdateSelectionCount()
    
    def OnDeselectAll(self, sender, args):
        """Deselect all walls"""
        if self.dgWalls.ItemsSource:
            for wall in self.dgWalls.ItemsSource:
                wall.IsSelected = False
            self.dgWalls.Items.Refresh()
            self.UpdateSelectionCount()
    
    def OnCreateAssemblies(self, sender, args):
        """Create assemblies button clicked"""
        self.CreateAssemblies()
    
    def ShowDialog(self):
        """Show the window"""
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

# Get paths
script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, 'AssemblyCreation.xaml')

# Check XAML exists
if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\nExpected: {}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

# Show window
try:
    window = AssemblyCreationWindow(xaml_path, script_dir)
    window.ShowDialog()
except Exception as e:
    forms.alert("Error: {}".format(str(e)), title="Error")
    import traceback
    output.print_md("```\n{}\n```".format(traceback.format_exc()))