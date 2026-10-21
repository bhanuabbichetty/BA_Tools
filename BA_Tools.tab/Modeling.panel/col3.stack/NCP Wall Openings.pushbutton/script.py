"""Select host walls and create face-hosted NCP-Void(Instance) openings from electrical and HVAC linked families."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from pyrevit import revit, DB, UI, forms, script
from void_engine import SOURCE_FAMILY, SOURCE_FAMILIES, TARGET_FAMILY, plan, execute
from Autodesk.Revit.Exceptions import OperationCanceledException


class WallFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, DB.Wall)
    def AllowReference(self, reference, point):
        return False


def choose(mapping, title):
    choice = forms.SelectFromList.show(sorted(mapping.keys()), title=title, multiselect=False, button_name='Select')
    if not choice:
        script.exit()
    return mapping[choice]


def report(title, rows, skipped, failed):
    output = script.get_output()
    output.print_md('## ' + title)
    if rows:
        output.print_table(table_data=[
            [r['link'],r['source'],r['wall'],r['length_mm'],r['height_mm'],r['depth_mm'],r['projection_mm']]
            for r in rows], columns=['Link','Linked source ID','Selected wall ID','Length mm','Height mm','Depth mm','Face projection mm'])
    if skipped or failed:
        output.print_table(table_data=list(skipped)+list(failed), columns=['Linked source ID','Reason'])


def main():
    doc = revit.doc
    if doc.IsFamilyDocument or doc.IsReadOnly:
        forms.alert('Open an editable wall project.', exitscript=True)
    walls = [doc.GetElement(i) for i in revit.uidoc.Selection.GetElementIds() if isinstance(doc.GetElement(i),DB.Wall)]
    if not walls:
        try:
            refs = revit.uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, WallFilter(), 'Select the host walls, then click Finish')
            walls = [doc.GetElement(r.ElementId) for r in refs]
        except OperationCanceledException:
            script.exit()
    if not walls:
        script.exit()
    unsupported = [w.Id.Value for w in walls if w.WallType.Kind != DB.WallKind.Basic]
    if unsupported:
        forms.alert('Select basic walls only. Unsupported wall IDs: '+', '.join(str(i) for i in unsupported), exitscript=True)
    links = {}
    for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = link.GetLinkDocument()
        if not ld or not ('-EL-' in ld.Title.upper() or 'ELECTRICAL' in ld.Title.upper() or 'HVAC' in ld.Title.upper()):
            continue
        if any(e.Symbol.Family.Name in SOURCE_FAMILIES for e in DB.FilteredElementCollector(ld).OfClass(DB.FamilyInstance)):
            links['{} [instance {}]'.format(link.Name,link.Id.Value)] = link
    if not links:
        forms.alert('No loaded electrical or HVAC link contains either supported wall cut-out family.', exitscript=True)
    selected_links = [links[k] for k in sorted(links)]
    types = dict((DB.Element.Name.GetValue(s),s) for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol) if s.Family.Name == TARGET_FAMILY)
    if not types:
        forms.alert('Load '+TARGET_FAMILY+' with instance Length, Height and Width parameters.', exitscript=True)
    base = types.get('MEP=130mm')
    if base is None:
        base = choose(types,'Select NCP-Void(Instance) type')
    if base.Family.FamilyPlacementType != DB.FamilyPlacementType.WorkPlaneBased:
        forms.alert('The target family must support face hosting.', exitscript=True)
    if any(list(base.GetParameters(name)) for name in ['Length','Height','Width']):
        forms.alert('Length, Height and Width must all be instance parameters in the loaded target family.', exitscript=True)
    ready, skipped = [], []
    for link in selected_links:
        link_ready, link_skipped = plan(doc,link,walls)
        ready.extend(link_ready)
        skipped.extend(link_skipped)
    tested, failures = execute(doc,base,ready,preview=True)
    report('Wall preview: {} successful, {} skipped, {} failed'.format(len(tested),len(skipped),len(failures)),tested,skipped,failures)
    if not tested:
        forms.alert('No new openings passed the selected-wall preview. No model changes were retained. See the report.', exitscript=True)
    good = set(r['key'] for r in tested)
    ready = [item for item in ready if item['key'] in good]
    message = ('Selected walls: {}\nMatching openings ready: {}\nSkipped or failed: {}\n\n'
               'All loaded EL and HVAC links are scanned.\nLength, Height and Width are copied to each instance without clearance.\n'
               'Openings are projected onto the intersected wall face; see the report for projection distances.\n'
               'Schedule Level follows the host wall. The preview was rolled back.\n\nCreate these openings?').format(len(walls),len(ready),len(skipped)+len(failures))
    if not forms.alert(message,yes=True,no=True):
        script.exit()
    created, failures = execute(doc,base,ready,preview=False)
    report('Created {} selected-wall voids; {} failed'.format(len(created),len(failures)),created,[],failures)
    forms.alert('Created {} wall openings. {} failed. See the report.\nUndo with Ctrl+Z.'.format(len(created),len(failures)))


try:
    main()
except OperationCanceledException:
    script.exit()
except Exception as error:
    forms.alert('Linked Wall Voids could not finish:\n'+str(error))
