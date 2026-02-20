# -*- coding: utf-8 -*-
"""
Grid Annotation Manager - WPF Modern UI
Add grid bubble annotations and dimensions to Floor Plans and Structural Plans
"""
__title__ = 'Grid\nAnnotation'
__doc__ = 'Add grid bubbles and dimensions to Floor Plans and Structural Plans'

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

doc = revit.doc
output = script.get_output()


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_all_grids():
    """Get all grids in the project"""
    grids = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Grids)\
        .WhereElementIsNotElementType()\
        .ToElements()
    return list(grids)


def get_target_views(include_plans, include_structural_plans, active_only):
    """Get views to process based on selection - Floor Plans and Structural Plans only"""
    views = []

    if active_only:
        active_view = doc.ActiveView
        output.print_md("**Active View**: {} (Type: {})".format(active_view.Name, active_view.ViewType))
        
        # Only allow Floor Plans and Structural Plans
        if active_view.ViewType in [ViewType.FloorPlan, ViewType.EngineeringPlan]:
            views.append(active_view)
            output.print_md("✓ Active view is valid (Floor Plan or Structural Plan)")
        else:
            output.print_md("✗ Active view type not supported - must be Floor Plan or Structural Plan")
    else:
        all_views = FilteredElementCollector(doc)\
            .OfClass(View)\
            .WhereElementIsNotElementType()\
            .ToElements()

        for view in all_views:
            # Skip templates
            if view.IsTemplate:
                continue

            # Only process Floor Plans and Structural Plans
            if include_plans and view.ViewType == ViewType.FloorPlan:
                views.append(view)
            elif include_structural_plans and view.ViewType == ViewType.EngineeringPlan:
                views.append(view)

    return views


def classify_grids_for_view(grids, view):
    """Classify grids based on how they appear in a specific view"""
    vertical_grids = []
    horizontal_grids = []
    inclined_grids = []

    for grid in grids:
        try:
            curve = grid.Curve
            direction = curve.Direction

            # In plan views - use X/Y components
            angle_x = abs(direction.X)
            angle_y = abs(direction.Y)

            if angle_x > 0.97:  # Nearly horizontal (running east-west)
                horizontal_grids.append(grid)
            elif angle_y > 0.97:  # Nearly vertical (running north-south)
                vertical_grids.append(grid)
            else:  # Inclined
                inclined_grids.append(grid)
        except:
            pass

    return vertical_grids, horizontal_grids, inclined_grids


def add_grid_head(view, grid, end_point_index):
    """Add grid head (bubble) at specified end of grid"""
    try:
        if end_point_index == 0:
            datum_end = DatumEnds.End0
        else:
            datum_end = DatumEnds.End1
        
        grid.ShowBubbleInView(datum_end, view)
        return True
    except:
        return False


def create_dimension_string(view, grids, offset):
    """Create dimension string for grids"""
    try:
        if len(grids) < 2:
            return None

        visible_grids = []
        for grid in grids:
            try:
                ref = Reference(grid)
                visible_grids.append(grid)
            except:
                continue

        if len(visible_grids) < 2:
            return None

        refs = ReferenceArray()
        for grid in visible_grids:
            try:
                refs.Append(Reference(grid))
            except:
                continue

        if refs.Size < 2:
            return None

        first_curve = visible_grids[0].Curve
        last_curve = visible_grids[-1].Curve

        start_pt = first_curve.GetEndPoint(0)
        end_pt = last_curve.GetEndPoint(0)

        direction = first_curve.Direction
        perpendicular = XYZ(-direction.Y, direction.X, 0).Normalize()

        # Apply offset directly (user provides positive value to move away)
        offset_pt1 = start_pt + perpendicular * offset
        offset_pt2 = end_pt + perpendicular * offset

        dim_line = Line.CreateBound(offset_pt1, offset_pt2)
        dimension = doc.Create.NewDimension(view, dim_line, refs)
        return dimension
    except Exception as e:
        output.print_md("  Dimension error: {}".format(str(e)))
        return None


# Update the create_dimension_string function to include end-to-end dimension logic
def create_dimension_string(view, grids, offset):
    if len(grids) < 2:
        return False

    # Add end-to-end dimension logic
    first_grid = grids[0]
    last_grid = grids[-1]

    # Create a reference point for the first and last grid
    pt_start = first_grid.Curve.GetEndPoint(1)
    pt_end = last_grid.Curve.GetEndPoint(0)

    # Adjust points based on offset
    ref_start = pt_start + XYZ.BasisZ * offset
    ref_end = pt_end + XYZ.BasisZ * offset

    # Create a line between the adjusted reference points
    line = Line.CreateBound(ref_start, ref_end)

    # Add dimension to the view
    dim = view.NewDetailCurve(line)
    return True


# ==============================================================================
# WPF WINDOW CLASS
# ==============================================================================

class GridAnnotationWindow(Window):
    def __init__(self, xaml_path, document):
        stream = StreamReader(xaml_path)
        self._window = XamlReader.Load(stream.BaseStream)
        stream.Close()
        
        self.doc = document
        self.result = False
        
        # Get controls
        self.btnClose = self._window.FindName("btnClose")
        self.chkVerticalTop = self._window.FindName("chkVerticalTop")
        self.chkVerticalBottom = self._window.FindName("chkVerticalBottom")
        self.chkHorizontalLeft = self._window.FindName("chkHorizontalLeft")
        self.chkHorizontalRight = self._window.FindName("chkHorizontalRight")
        self.chkInclinedTop = self._window.FindName("chkInclinedTop")
        self.chkInclinedBottom = self._window.FindName("chkInclinedBottom")
        self.chkIncludeDimensions = self._window.FindName("chkIncludeDimensions")
        self.chkEndToEndDimensions = self._window.FindName("chkEndToEndDimensions")
        self.chkAllPlanViews = self._window.FindName("chkAllPlanViews")
        self.chkAllStructuralPlanViews = self._window.FindName("chkAllStructuralPlanViews")
        self.chkActiveViewOnly = self._window.FindName("chkActiveViewOnly")
        self.txtStatus = self._window.FindName("txtStatus")
        self.btnAnnotateAll = self._window.FindName("btnAnnotateAll")
        
        self.SetupEventHandlers()
    
    def SetupEventHandlers(self):
        self.btnClose.Click += self.OnClose
        self.btnAnnotateAll.Click += self.OnAnnotate
        self.chkActiveViewOnly.Checked += self.OnActiveViewOnlyChanged
        self.chkActiveViewOnly.Unchecked += self.OnActiveViewOnlyChanged
        self.chkAllPlanViews.Checked += self.OnPlanViewsChanged
        self.chkAllStructuralPlanViews.Checked += self.OnPlanViewsChanged
        # Wire drag handler for borderless window
        header_border = self._window.FindName("headerDragArea")
        if header_border:
            header_border.MouseLeftButtonDown += self.OnHeaderDrag
    
    def OnHeaderDrag(self, sender, args):
        """Allow dragging the borderless window by its title bar"""
        try:
            self._window.DragMove()
        except:
            pass
    
    def OnClose(self, sender, args):
        self._window.DialogResult = False
        self._window.Close()
    
    def OnActiveViewOnlyChanged(self, sender, args):
        """Handle Active View Only checkbox changes - make it mutually exclusive"""
        is_active_only = self.chkActiveViewOnly.IsChecked
        
        if is_active_only:
            # When Active View Only is checked, uncheck and disable other options
            self.chkAllPlanViews.IsChecked = False
            self.chkAllStructuralPlanViews.IsChecked = False
            self.chkAllPlanViews.IsEnabled = False
            self.chkAllStructuralPlanViews.IsEnabled = False
        else:
            # Re-enable other options when Active View Only is unchecked
            self.chkAllPlanViews.IsEnabled = True
            self.chkAllStructuralPlanViews.IsEnabled = True
    
    def OnPlanViewsChanged(self, sender, args):
        """Handle Plan Views checkboxes - uncheck Active View Only if either is checked"""
        if self.chkAllPlanViews.IsChecked or self.chkAllStructuralPlanViews.IsChecked:
            self.chkActiveViewOnly.IsChecked = False
    
    def OnAnnotate(self, sender, args):
        """Process annotation based on current settings"""
        # Get settings
        vertical_top = self.chkVerticalTop.IsChecked
        vertical_bottom = self.chkVerticalBottom.IsChecked
        horizontal_left = self.chkHorizontalLeft.IsChecked
        horizontal_right = self.chkHorizontalRight.IsChecked
        inclined_top = self.chkInclinedTop.IsChecked
        inclined_bottom = self.chkInclinedBottom.IsChecked
        include_dimensions = self.chkIncludeDimensions.IsChecked
        include_end_to_end = self.chkEndToEndDimensions.IsChecked

        # Use fixed offset values
        first_offset = -10.0  # Grid-to-grid dimensions (10 ft away)
        second_offset = -20.0  # End-to-end dimensions (20 ft away)

        # Check if any option is selected
        if not any([vertical_top, vertical_bottom, horizontal_left, horizontal_right,
                   inclined_top, inclined_bottom, include_dimensions, include_end_to_end]):
            forms.alert("Please select at least one option", title="Validation Error")
            return

        # Get target views - FIXED LOGIC
        is_active_only = self.chkActiveViewOnly.IsChecked
        
        if is_active_only:
            # ONLY process the active view
            views = get_target_views(False, False, True)
            output.print_md("**Mode**: Active View Only")
        else:
            # Process based on checkboxes
            include_plans = self.chkAllPlanViews.IsChecked
            include_structural = self.chkAllStructuralPlanViews.IsChecked
            
            if not include_plans and not include_structural:
                forms.alert("Please select at least one view type or enable Active View Only", title="Validation Error")
                return
            
            views = get_target_views(include_plans, include_structural, False)
            output.print_md("**Mode**: Multiple Views")
            output.print_md("  Floor Plans: {}".format("Yes" if include_plans else "No"))
            output.print_md("  Structural Plans: {}".format("Yes" if include_structural else "No"))
        
        if not views:
            forms.alert("No valid views found matching criteria.\n\nActive view must be a Floor Plan or Structural Plan.", title="No Views Found")
            return
        
        # Confirm
        confirm_msg = "Process {} view(s)?".format(len(views))
        if not forms.alert(confirm_msg, yes=True, no=True, title="Confirm"):
            return
        
        # Update UI
        self.btnAnnotateAll.IsEnabled = False
        self.btnAnnotateAll.Content = "PROCESSING..."
        
        # Get all grids
        all_grids = get_all_grids()
        
        if not all_grids:
            forms.alert("No grids found in project", title="Error")
            self.btnAnnotateAll.IsEnabled = True
            self.btnAnnotateAll.Content = "ANNOTATE"
            return
        
        output.print_md("### Grid Annotation")
        output.print_md("**Grids**: {}".format(len(all_grids)))
        output.print_md("**Views**: {}".format(len(views)))
        
        views_processed = 0
        bubbles_added = 0
        dimensions_added = 0
        errors = 0
        
        with revit.Transaction("Add Grid Annotations"):
            for view in views:
                try:
                    output.print_md("**{}**: {}".format(view.Name, view.ViewType))
                    
                    vertical_grids, horizontal_grids, inclined_grids = classify_grids_for_view(all_grids, view)
                    vertical_grids.sort(key=lambda g: g.Curve.GetEndPoint(0).X)
                    horizontal_grids.sort(key=lambda g: g.Curve.GetEndPoint(0).Y)
                    inclined_grids.sort(key=lambda g: g.Curve.GetEndPoint(0).Y)
                    
                    view_bubbles = 0
                    view_dimensions = 0
                    
                    # Add bubbles for vertical grids
                    if (vertical_top or vertical_bottom) and vertical_grids:
                        for grid in vertical_grids:
                            if vertical_top and add_grid_head(view, grid, 1):
                                view_bubbles += 1
                            if vertical_bottom and add_grid_head(view, grid, 0):
                                view_bubbles += 1
                    
                    # Add bubbles for horizontal grids
                    if (horizontal_left or horizontal_right) and horizontal_grids:
                        for grid in horizontal_grids:
                            if horizontal_left and add_grid_head(view, grid, 0):
                                view_bubbles += 1
                            if horizontal_right and add_grid_head(view, grid, 1):
                                view_bubbles += 1
                    
                    # Add bubbles for inclined grids
                    if (inclined_top or inclined_bottom) and inclined_grids:
                        for grid in inclined_grids:
                            pt0 = grid.Curve.GetEndPoint(0)
                            pt1 = grid.Curve.GetEndPoint(1)
                            top_end = 0 if pt0.Y > pt1.Y else 1
                            bottom_end = 1 if pt0.Y > pt1.Y else 0
                            
                            if inclined_top and add_grid_head(view, grid, top_end):
                                view_bubbles += 1
                            if inclined_bottom and add_grid_head(view, grid, bottom_end):
                                view_bubbles += 1
                    
                    # Add dimensions
                    if include_dimensions:
                        if len(vertical_grids) >= 2:
                            if create_dimension_string(view, vertical_grids, first_offset):
                                view_dimensions += 1
                        if len(horizontal_grids) >= 2:
                            if create_dimension_string(view, horizontal_grids, first_offset):
                                view_dimensions += 1
                    
                    # Add end-to-end dimensions
                    if include_end_to_end:
                        if len(vertical_grids) >= 2:
                            if create_end_to_end_dimension(view, vertical_grids, second_offset):
                                view_dimensions += 1
                        if len(horizontal_grids) >= 2:
                            if create_end_to_end_dimension(view, horizontal_grids, second_offset):
                                view_dimensions += 1
                    
                    bubbles_added += view_bubbles
                    dimensions_added += view_dimensions
                    views_processed += 1
                    
                    output.print_md("  ✓ {} bubbles, {} dims".format(view_bubbles, view_dimensions))
                    
                except Exception as e:
                    output.print_md("  ✗ Error: {}".format(str(e)))
                    errors += 1
        
        summary = "Complete!\n\nViews: {}\nBubbles: {}\nDimensions: {}".format(
            views_processed, bubbles_added, dimensions_added)
        
        forms.alert(summary, title="Grid Annotation Complete")
        
        output.print_md("### ✅ Complete")
        output.print_md("**Views**: {}".format(views_processed))
        output.print_md("**Bubbles**: {}".format(bubbles_added))
        output.print_md("**Dimensions**: {}".format(dimensions_added))
        
        self.result = True
        self._window.Close()
    
    def ShowDialog(self):
        return self._window.ShowDialog()


# ==============================================================================
# MAIN
# ==============================================================================

script_dir = os.path.dirname(__file__)
xaml_path = os.path.join(script_dir, "GridAnnotation.xaml")

if not os.path.exists(xaml_path):
    forms.alert(
        "XAML file not found!\n\n{}".format(xaml_path),
        title="File Not Found",
        exitscript=True
    )

grids = get_all_grids()
output.print_md("**Found {} grids**".format(len(grids)))

window = GridAnnotationWindow(xaml_path, doc)
window.ShowDialog()

if window.result:
    output.print_md("### ✅ Grid Annotation Completed")
else:
    output.print_md("### Cancelled")
