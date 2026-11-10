import re
from pyrevit import DB
from pyrevit.revit.db.query import get_name
import wall_engine


class PlannedType(object):
    def __init__(self,width,name):
        self.Width=width/304.8
        self.Name=name
        self.Id=DB.ElementId.InvalidElementId


def thickness(layer):
    if 'wall' not in layer.lower():
        return None
    values=set(float(value) for value in re.findall(r'(\d+(?:\.\d+)?)\s*mm\b',layer,re.I))
    if len(values)!=1:
        return None
    value=next(iter(values))
    return value if 20<=value<=2000 else None


def resolve_type(doc,width):
    types=[t for t in DB.FilteredElementCollector(doc).OfClass(DB.WallType) if t.Kind==DB.WallKind.Basic]
    matches=[t for t in types if abs(t.Width*304.8-width)<0.5]
    desired='NCP Wall - {0:g}mm'.format(width)
    if matches:
        return sorted(matches,key=lambda t:(get_name(t)!=desired,'ncp' not in get_name(t).lower(),get_name(t)))[0]
    names=set(get_name(t) for t in types)
    name=desired
    suffix=2
    while name in names:
        name=desired+' ('+str(suffix)+')'
        suffix+=1
    return PlannedType(width,name)


def type_name(wall_type):
    return wall_type.Name if isinstance(wall_type,PlannedType) else get_name(wall_type)


def make_type(doc,planned):
    resolved=resolve_type(doc,planned.Width*304.8)
    if not isinstance(resolved,PlannedType):
        return resolved
    templates=[t for t in DB.FilteredElementCollector(doc).OfClass(DB.WallType) if t.Kind==DB.WallKind.Basic and t.GetCompoundStructure() and t.GetCompoundStructure().LayerCount==1]
    if not templates:
        raise ValueError('No single-layer basic wall type is available to copy. Load the required wall types first.')
    template=sorted(templates,key=lambda t:('ncp' not in get_name(t).lower(),'concrete' not in get_name(t).lower(),get_name(t)))[0]
    created=template.Duplicate(resolved.Name)
    structure=created.GetCompoundStructure()
    structure.SetLayerWidth(0,resolved.Width)
    created.SetCompoundStructure(structure)
    return created


def plan_batch(doc,source,layer,base,top,top_mm,keyway_mm,allow_types=True):
    width=thickness(layer)
    if width is None:
        raise ValueError('Layer name must contain one wall thickness, for example NCP_Wall-250mm.')
    wall_type=resolve_type(doc,width)
    if isinstance(wall_type,PlannedType) and not allow_types:
        raise ValueError('No {0:g} mm wall type exists. Enable creation of missing wall types or load one.'.format(width))
    runs=wall_engine.derive(source,layer,width/304.8,keyway_mm)
    wall_engine.prepare_exterior_faces(source,runs,layer,width/304.8)
    records=wall_engine.classify(doc,runs,wall_type,base,top,16.0/304.8,top_mm/304.8)
    return {'layer':layer,'width':width,'type':wall_type,'top_mm':top_mm,'records':records}


def cross_conflicts(batches):
    all_records=[]
    for batch in batches:
        for item in batch['records']:
            if item['status']=='Existing':
                continue
            a,b=item['a'],item['b']
            u=b.Subtract(a).Normalize()
            for other_layer,other in all_records:
                if other_layer==batch['layer']:
                    continue
                p,q=other['a'],other['b']
                v=q.Subtract(p).Normalize()
                if abs(u.DotProduct(v))<0.999999 or p.Subtract(a).CrossProduct(u).GetLength()>wall_engine.TOL:
                    continue
                lo,hi=sorted([p.Subtract(a).DotProduct(u),q.Subtract(a).DotProduct(u)])
                if min(hi,item['length'])-max(lo,0)>wall_engine.TOL:
                    item['status']='Conflict'
                    other['status']='Conflict'
            all_records.append((batch['layer'],item))


def create_all(doc,source,batches,base,top,unjoin,allow_types):
    if any(item['status']=='Conflict' for batch in batches for item in batch['records']):
        raise ValueError('Resolve the preview conflicts first.')
    active=[b for b in batches if any(item['status']=='New' for item in b['records'])]
    if not active:
        return []
    group=DB.TransactionGroup(doc,'Walls from CAD - multiple layers')
    group.Start()
    ids=[]
    try:
        missing=[b for b in active if isinstance(b['type'],PlannedType)]
        if missing:
            if not allow_types:
                raise ValueError('Creation of missing wall types is disabled.')
            transaction=DB.Transaction(doc,'Create matching CAD wall types')
            transaction.Start()
            try:
                for batch in missing:
                    batch['type']=make_type(doc,batch['type'])
                transaction.Commit()
            except:
                if transaction.GetStatus()==DB.TransactionStatus.Started:
                    transaction.RollBack()
                raise
        for batch in active:
            fresh=wall_engine.classify(doc,batch['records'],batch['type'],base,top,16.0/304.8,batch['top_mm']/304.8)
            if any(item['status']=='Conflict' for item in fresh):
                raise ValueError('Conflicting walls found in '+batch['layer'])
            ids.extend(wall_engine.create(doc,source,batch['layer'],fresh,batch['type'],base,top,16.0/304.8,batch['top_mm']/304.8,unjoin))
        group.Assimilate()
    except:
        if group.GetStatus()==DB.TransactionStatus.Started:
            group.RollBack()
        raise
    return ids
