"""Create constrained walls from a selected CAD layer in one BA Tools window."""
from pyrevit import revit,DB,forms,script
from wall_setup import WallSetup
import cad_source


try:
    doc=revit.doc
    view=doc.ActiveView
    if doc.IsFamilyDocument or not isinstance(view,DB.ViewPlan) or view.IsTemplate:
        forms.alert('Open a floor, structural or ceiling plan in a project first.',exitscript=True)
    selected=set(cad_source.eid(element) for element in revit.get_selection())
    WallSetup(doc,view,selected,__revit__.MainWindowHandle).show()
except Exception as error:
    script.get_logger().exception('Walls from CAD failed')
    forms.alert('Walls from CAD could not open.\n\n'+unicode(error))
