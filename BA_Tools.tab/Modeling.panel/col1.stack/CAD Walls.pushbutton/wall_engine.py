import os
import math
from pyrevit import DB
from pyrevit.revit.db.query import get_name
from pyrevit.revit.db.create import create_wall
import cad_source


TOL=1.0/304.8
EXTERIOR_FACE_LAYER='ERECTION_MARK'


def number(text,label,positive=False):
    try:
        value=float(text)
    except (ValueError,TypeError):
        raise ValueError(label+' must be a number in millimetres.')
    if math.isnan(value) or math.isinf(value) or (positive and value<=0):
        raise ValueError(label+' must be a finite '+('positive ' if positive else '')+'number.')
    return value


def cad_path(doc,instance):
    reference=doc.GetElement(instance.GetTypeId()).GetExternalFileReference()
    return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath())


def read_source(doc,instance,folder):
    rows=cad_source.read_dwg(cad_path(doc,instance),folder)
    geometry=cad_source.cad_geometry(doc,instance)
    transform=instance.GetTotalTransform()
    if abs(abs(transform.BasisZ.Normalize().Z)-1)>1e-6:
        raise ValueError('The CAD link is tilted. Use a planar CAD link.')
    raw={}
    actual={}
    for row in rows:
        if row[0]=='L':
            length=math.hypot(float(row[4])-float(row[2]),float(row[5])-float(row[3]))
            if length>0.000001:
                raw.setdefault(row[1],[]).append((length,row))
    for layer,line in geometry:
        if line.Length>TOL:
            actual.setdefault(layer,[]).append(line)
    layers=sorted(set(raw).intersection(actual),key=lambda name:(not any(s in name.lower() for s in ('grid','axis')), -max(item[0] for item in raw[name])))
    scales=[1.0/304.8,1.0/30.48,1000.0/304.8,1.0/12,1.0,1.000002000004]
    found=None
    for layer in layers[:25]:
        candidates=sorted(raw[layer],reverse=True)[:8]
        longest=max(actual[layer],key=lambda line:line.Length)
        possibilities=scales+[longest.Length/candidates[0][0]/transform.BasisX.GetLength()]
        for scale in possibilities:
            matches=0
            for length,row in candidates:
                a=transform.OfPoint(DB.XYZ(float(row[2])*scale,float(row[3])*scale,0))
                b=transform.OfPoint(DB.XYZ(float(row[4])*scale,float(row[5])*scale,0))
                best=min(min(a.DistanceTo(line.GetEndPoint(0))+b.DistanceTo(line.GetEndPoint(1)),a.DistanceTo(line.GetEndPoint(1))+b.DistanceTo(line.GetEndPoint(0))) for line in actual[layer])
                if best<TOL*2:
                    matches+=1
            if matches>=min(3,len(candidates)):
                found=scale
                break
        if found is not None:
            break
    if found is None:
        raise ValueError('Could not verify the saved DWG coordinates against the Revit link. Reload the CAD link and try again.')
    return {'rows':rows,'transform':transform,'scale':found,'layers':sorted(raw),'path':cad_path(doc,instance),'link_id':cad_source.eid(instance)}


def derive(source,layer,width,keyway_mm=80.0):
    if keyway_mm<0:
        raise ValueError('Keyway gap cannot be negative.')
    if any(row[0]=='U' and row[1]==layer for row in source['rows']):
        raise ValueError('This layer contains curved edges. This command supports straight, orthogonal CAD wall outlines.')
    factor=source['scale']*source['transform'].BasisX.GetLength()
    tolerance=TOL/factor
    width_raw=width/factor
    segments=[]
    for row in source['rows']:
        if row[0]!='L' or row[1]!=layer:
            continue
        x1,y1,x2,y2=[float(value) for value in row[2:6]]
        if math.hypot(x2-x1,y2-y1)*factor<TOL:
            continue
        if abs(x2-x1)<tolerance:
            segments.append(('V',(x1+x2)/2,min(y1,y2),max(y1,y2)))
        elif abs(y2-y1)<tolerance:
            segments.append(('H',(y1+y2)/2,min(x1,x2),max(x1,x2)))
        else:
            raise ValueError('The layer contains diagonal edges. Select orthogonal wall outlines; rotated CAD links are supported.')
    if len(segments)>6000:
        raise ValueError('This layer has too many edges. Isolate the wall outlines onto a dedicated CAD layer.')
    groups=[]
    for index,a in enumerate(segments):
        for b in segments[index+1:]:
            if a[0]!=b[0] or abs(abs(a[1]-b[1])-width_raw)>tolerance:
                continue
            lo,hi=max(a[2],b[2]),min(a[3],b[3])
            if (hi-lo)*factor*304.8<=75:
                continue
            center=(a[1]+b[1])/2
            group=next((g for g in groups if g['direction']==a[0] and abs(g['center']-center)<tolerance),None)
            if group is None:
                group={'direction':a[0],'center':center,'intervals':[]}
                groups.append(group)
            group['intervals'].append((lo,hi))
    runs=[]
    def world(x,y):
        return source['transform'].OfPoint(DB.XYZ(x*source['scale'],y*source['scale'],0))
    for group in groups:
        merged=[]
        for lo,hi in sorted(group['intervals']):
            gap=(lo-merged[-1][1])*factor*304.8 if merged else 999999
            if merged and (gap<=1 or (keyway_mm>0 and abs(gap-keyway_mm)<=1)):
                merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
            else:
                merged.append((lo,hi))
        for lo,hi in merged:
            if (hi-lo)*factor<=width:
                continue
            c=group['center']
            a,b=(world(c,lo),world(c,hi)) if group['direction']=='V' else (world(lo,c),world(hi,c))
            raw_a,raw_b=( (c,lo),(c,hi) ) if group['direction']=='V' else ( (lo,c),(hi,c) )
            runs.append({'a':a,'b':b,'raw_a':raw_a,'raw_b':raw_b,'length':a.DistanceTo(b)})
    if not runs:
        raise ValueError('No paired wall faces match the selected wall type width ({0:.0f} mm). Check the CAD layer and wall type.'.format(width*304.8))
    return runs


def uses_erection_marks(width):
    return True


def marker_components(source):
    cached=source.get('_erection_components')
    if cached is not None:
        return cached
    factor=source['scale']*source['transform'].BasisX.GetLength()
    tolerance=1.0/304.8/factor
    segments=[]
    for row in source['rows']:
        if row[0]=='L' and row[1].split('$')[-1].strip().lower()==EXTERIOR_FACE_LAYER.lower():
            values=[float(value) for value in row[2:6]]
            a,b=(values[0],values[1]),(values[2],values[3])
            if math.hypot(a[0]-b[0],a[1]-b[1])>tolerance:
                segments.append((a,b))
    if len(segments)>10000:
        raise ValueError('ERECTION_MARK has too many segments. Keep only wall face markers on this layer.')
    components=[]
    remaining=set(range(len(segments)))
    while remaining:
        current=[remaining.pop()]
        vertices=list(segments[current[0]])
        while current:
            index=current.pop()
            a,b=segments[index]
            connected=[i for i in remaining if any(math.hypot(p[0]-q[0],p[1]-q[1])<=tolerance for p in (a,b) for q in segments[i])]
            for i in connected:
                remaining.remove(i)
                current.append(i)
                vertices.extend(segments[i])
        components.append(vertices)
    source['_erection_components']=components
    return components


def prepare_exterior_faces(source,runs,layer,width):
    for run in runs:
        for key in ('location_a','location_b','exterior_normal','exterior_face_a','exterior_face_b','marker_count'):
            run.pop(key,None)
    if not uses_erection_marks(width):
        return
    factor=source['scale']*source['transform'].BasisX.GetLength()
    tolerance=3.0/304.8/factor
    half=width/factor/2.0
    components=marker_components(source)
    if not components:
        raise ValueError('No ERECTION_MARK symbols found. Add a line or triangle touching the intended exterior face.')
    def world(point):
        return source['transform'].OfPoint(DB.XYZ(point[0]*source['scale'],point[1]*source['scale'],0))
    errors=[]
    for index,run in enumerate(runs,1):
        ax,ay=run['raw_a']
        bx,by=run['raw_b']
        length=math.hypot(bx-ax,by-ay)
        dx,dy=(bx-ax)/length,(by-ay)/length
        nx,ny=-dy,dx
        sides=set()
        count=0
        for vertices in components:
            values=[((x-ax)*dx+(y-ay)*dy,(x-ax)*nx+(y-ay)*ny) for x,y in vertices]
            for side in (-1,1):
                face=side*half
                contact=any(-tolerance<=along<=length+tolerance and abs(offset-face)<=tolerance for along,offset in values)
                outside=all(side*offset>=half-tolerance for along,offset in values)
                extends=any(side*offset>half+tolerance for along,offset in values)
                if contact and outside and extends:
                    sides.add(side)
                    count+=1
            center=[value for value in values if abs(value[1])<=tolerance and -tolerance<=value[0]<=length+tolerance]
            if center and len(vertices)==2:
                offsets=[value[1] for value in values]
                side=1 if max(offsets)>half-tolerance and min(offsets)>=-tolerance else -1 if min(offsets)<-half+tolerance and max(offsets)<=tolerance else 0
                if side and all(-tolerance<=along<=length+tolerance for along,offset in values):
                    sides.add(side)
                    count+=1
        if len(sides)!=1:
            errors.append('run {0} at ({1:.0f}, {2:.0f}) mm: {3}'.format(index,(ax+bx)/2*source['scale']*304.8,(ay+by)/2*source['scale']*304.8,'missing face mark' if not sides else 'opposite-side marks'))
            continue
        side=next(iter(sides))
        offset=side*half
        run['exterior_face_a']=world((ax+nx*offset,ay+ny*offset))
        run['exterior_face_b']=world((bx+nx*offset,by+ny*offset))
        normal=source['transform'].OfVector(DB.XYZ(nx*side,ny*side,0))
        run['exterior_normal']=normal.Normalize()
        run['marker_count']=count
    if errors:
        raise ValueError(layer+': ERECTION_MARK - '+'; '.join(errors[:8]))


def exterior_matches(doc,wall,run):
    expected=run.get('exterior_normal')
    if expected is None:
        return True
    if wall.Orientation.DotProduct(expected)<0.999:
        return False
    if wall.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()!=int(DB.WallLocationLine.FinishFaceExterior):
        return False
    point=run['exterior_face_a']
    references=DB.HostObjectUtils.GetSideFaces(wall,DB.ShellLayerType.Exterior)
    for reference in references:
        face=wall.GetGeometryObjectFromReference(reference)
        if isinstance(face,DB.PlanarFace) and abs(face.FaceNormal.DotProduct(expected))>0.999 and abs(face.Origin.Subtract(point).DotProduct(expected))<=TOL:
            return True
    return False


def classify(doc,runs,wall_type,base,top,base_offset,top_offset):
    z0,z1=base.Elevation+base_offset,top.Elevation+top_offset
    if z1-z0<=TOL:
        raise ValueError('The top level and offset must be above the wall base.')
    existing=list(DB.FilteredElementCollector(doc).OfClass(DB.Wall))
    records=[]
    for run in runs:
        item=dict(run)
        a,b=DB.XYZ(run['a'].X,run['a'].Y,z0),DB.XYZ(run['b'].X,run['b'].Y,z0)
        direction=b.Subtract(a).Normalize()
        target_a=run.get('location_a',a)
        target_b=run.get('location_b',b)
        axes=[(DB.XYZ(target_a.X,target_a.Y,z0),DB.XYZ(target_b.X,target_b.Y,z0))]
        if target_a.DistanceTo(a)>TOL:
            axes.append((a,b))
        status='New'
        found=[]
        for wall in existing:
            curve=wall.Location.Curve if isinstance(wall.Location,DB.LocationCurve) else None
            if not isinstance(curve,DB.Line) or abs(curve.Direction.DotProduct(direction))<0.999999:
                continue
            p,q=curve.GetEndPoint(0),curve.GetEndPoint(1)
            p,q=DB.XYZ(p.X,p.Y,z0),DB.XYZ(q.X,q.Y,z0)
            axis=next((start for start,end in axes if p.Subtract(start).CrossProduct(direction).GetLength()<=TOL),None)
            if axis is None:
                continue
            lo,hi=sorted([p.Subtract(axis).DotProduct(direction),q.Subtract(axis).DotProduct(direction)])
            if min(hi,run['length'])-max(lo,0)<=TOL:
                continue
            box=wall.get_BoundingBox(None)
            if not box or min(box.Max.Z,z1)-max(box.Min.Z,z0)<=TOL:
                continue
            matching=(exterior_matches(doc,wall,run) and wall.GetTypeId()==wall_type.Id and wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()==base.Id and wall.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()==top.Id and abs(wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()-base_offset)<TOL and abs(wall.get_Parameter(DB.BuiltInParameter.WALL_TOP_OFFSET).AsDouble()-top_offset)<TOL)
            found.append((lo,hi,matching))
        if found:
            matching_intervals=sorted((lo,hi) for lo,hi,matching in found if matching)
            end=0.0
            for lo,hi in matching_intervals:
                if lo>end+TOL:
                    break
                end=max(end,hi)
            status='Existing' if end>=run['length']-TOL and all(matching for lo,hi,matching in found) else 'Conflict'
        item['status']=status
        records.append(item)
    return records


def create(doc,source,layer,records,wall_type,base,top,base_offset,top_offset,unjoin):
    if any(item['status']=='Conflict' for item in records):
        raise ValueError('Resolve overlapping wall conflicts before creating walls.')
    pending=[item for item in records if item['status']=='New']
    if not pending:
        return []
    prepare_exterior_faces(source,pending,layer,wall_type.Width)
    ids=[]
    transaction=DB.Transaction(doc,'Walls from CAD')
    transaction.Start()
    try:
        for item in pending:
            a,b=item['a'],item['b']
            exterior_normal=item.get('exterior_normal')
            wall=create_wall((a.X,a.Y,base.Elevation),(b.X,b.Y,base.Elevation),wall_type,level=base,top_level=top,base_offset=base_offset,doc=doc)
            if exterior_normal is not None:
                doc.Regenerate()
                if wall.Orientation.DotProduct(exterior_normal)<0:
                    wall.Flip()
                location_line=wall.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
                if location_line is None or location_line.IsReadOnly:
                    raise ValueError('Could not set Finish Face: Exterior.')
                location_line.Set(int(DB.WallLocationLine.FinishFaceExterior))
                doc.Regenerate()
                if not exterior_matches(doc,wall,item):
                    raise ValueError('The created exterior face does not align with the marked CAD face. Placement rolled back.')
            wall.get_Parameter(DB.BuiltInParameter.WALL_TOP_OFFSET).Set(top_offset)
            wall.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set('agent:cad-walls:{0}:{1}:{2:.0f}mm'.format(source['link_id'],layer,wall_type.Width*304.8))
            if unjoin:
                DB.WallUtils.DisallowWallJoinAtEnd(wall,0)
                DB.WallUtils.DisallowWallJoinAtEnd(wall,1)
            ids.append(cad_source.eid(wall))
        doc.Regenerate()
        transaction.Commit()
    except:
        if transaction.GetStatus()==DB.TransactionStatus.Started:
            transaction.RollBack()
        raise
    return ids
