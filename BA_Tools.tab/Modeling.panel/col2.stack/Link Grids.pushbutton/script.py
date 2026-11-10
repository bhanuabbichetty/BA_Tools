"""Place named grids from a selected CAD or Revit link, with duplicate checks."""
from pyrevit import revit, DB, forms, script
import grid_link
from grid_setup import GridSetup


try:
    doc = revit.doc
    view = doc.ActiveView
    if not isinstance(view, DB.ViewPlan) or view.IsTemplate or doc.IsFamilyDocument:
        forms.alert('Open a floor, ceiling, or structural plan in a project first.', exitscript=True)
    selected = set(grid_link.eid(element) for element in revit.get_selection())
    GridSetup(doc,view,selected,__revit__.MainWindowHandle).show()
except Exception as error:
    script.get_logger().exception('Grids from Link failed')
    forms.alert('Grids from Link could not open.\n\n'+str(error))
