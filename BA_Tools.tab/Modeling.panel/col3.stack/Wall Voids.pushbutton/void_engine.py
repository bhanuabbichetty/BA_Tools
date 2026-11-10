from pyrevit import DB
from System import Guid, String

SOURCE_FAMILY = 'NC-M-Wall Cut-out1'
SOURCE_FAMILIES = ('NC-M-Wall Cut-out1', 'NC-M-Wall Cut-out')
TARGET_FAMILY = 'NCP-Void(Instance)'
SCHEMA_ID = Guid('983d7d11-cfe4-4558-bd1c-e187ad3d8b67')
TOL = 2.0 / 304.8
SEARCH = 25.0 / 304.8


def number(element):
    return element.Id.Value


def dimension(element, name):
    ps = list(element.GetParameters(name))
    if len(ps) != 1 or ps[0].StorageType != DB.StorageType.Double:
        raise ValueError('Missing or ambiguous length parameter: ' + name)
    p = ps[0]
    if p.Definition.GetDataType() != DB.SpecTypeId.Length:
        raise ValueError('Parameter is not a length: ' + name)
    value = p.AsDouble()
    if value <= 0:
        raise ValueError('Dimension must be positive: ' + name)
    return value


def write_dimension(element, name, value):
    ps = list(element.GetParameters(name))
    if len(ps) != 1 or ps[0].IsReadOnly:
        raise ValueError('Target parameter is missing, ambiguous or read-only: ' + name)
    if ps[0].Definition.GetDataType() != DB.SpecTypeId.Length:
        raise ValueError('Target parameter is not a length: ' + name)
    ps[0].Set(value)
    element.Document.Regenerate()
    if abs(ps[0].AsDouble() - value) > 1e-8:
        raise ValueError('Failed to set exact dimension: ' + name)


def schema(create=False):
    s = DB.ExtensibleStorage.Schema.Lookup(SCHEMA_ID)
    if s is None and create:
        b = DB.ExtensibleStorage.SchemaBuilder(SCHEMA_ID)
        b.SetSchemaName('NCPLinkedWallVoidV1')
        b.SetReadAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)
        b.SetWriteAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)
        b.AddSimpleField('SourceKey', String)
        b.AddSimpleField('Fingerprint', String)
        s = b.Finish()
    return s


def tag_value(instance, field):
    s = schema()
    if s is None:
        return None
    ent = instance.GetEntity(s)
    return ent.Get[String](s.GetField(field)) if ent.IsValid() else None


def tag(instance, key, fingerprint):
    s = schema(True)
    ent = DB.ExtensibleStorage.Entity(s)
    ent.Set[String](s.GetField('SourceKey'), key)
    ent.Set[String](s.GetField('Fingerprint'), fingerprint)
    instance.SetEntity(ent)


def floor_sources(link, level_id):
    ld = link.GetLinkDocument()
    return [e for e in DB.FilteredElementCollector(ld).OfClass(DB.FamilyInstance)
            if e.Symbol.Family.Name == SOURCE_FAMILY and e.LevelId == level_id]


def uv(face, point):
    d = point - face.Origin
    return DB.UV(d.DotProduct(face.XVector), d.DotProduct(face.YVector))


def face_bounds_contain(face, points):
    bb = face.GetBoundingBox()
    for p in points:
        q = uv(face, p)
        if q.U < bb.Min.U - TOL or q.U > bb.Max.U + TOL or q.V < bb.Min.V - TOL or q.V > bb.Max.V + TOL:
            return False
    return True


def geometry_origin(source, length, height):
    inverse = source.GetTransform().Inverse
    candidates = []
    def walk(objects, transform):
        for obj in objects:
            if isinstance(obj, DB.GeometryInstance):
                walk(obj.GetSymbolGeometry(), transform.Multiply(obj.Transform))
            elif isinstance(obj, DB.Solid) and obj.Volume > 1e-10:
                bb = obj.GetBoundingBox()
                bt = transform.Multiply(bb.Transform)
                points = [bt.OfPoint(DB.XYZ(x,y,z)) for x in [bb.Min.X,bb.Max.X] for y in [bb.Min.Y,bb.Max.Y] for z in [bb.Min.Z,bb.Max.Z]]
                xmin,xmax = min(p.X for p in points),max(p.X for p in points)
                zmin,zmax = min(p.Z for p in points),max(p.Z for p in points)
                score = abs(xmax-xmin-length)+abs(zmax-zmin-height)
                candidates.append((score,(xmin+xmax)/2,(zmin+zmax)/2))
    walk(source.get_Geometry(DB.Options()),inverse)
    if not candidates:
        raise ValueError('Source model geometry is unavailable; cannot verify placement origin')
    candidates.sort(key=lambda row:row[0])
    score,x,z = candidates[0]
    if score > 1.0/304.8:
        raise ValueError('Source solid footprint does not match LENGTH/HEIGHT; placement requires review')
    return DB.XYZ(x,0,z)


def source_data(link, source):
    if not isinstance(source.Location, DB.LocationPoint):
        raise ValueError('Source has no point location')
    tr = link.GetTotalTransform().Multiply(source.GetTransform())
    if abs(tr.BasisZ.DotProduct(DB.XYZ.BasisZ)) < 0.999 or abs(tr.BasisX.Z) > 0.001:
        raise ValueError('Tilted source is unsupported')
    length, height, depth = [dimension(source, n) for n in ['LENGTH', 'HEIGHT', 'DEPTH']]
    center = tr.OfPoint(geometry_origin(source, length, height))
    x = tr.BasisX.Normalize()
    z = DB.XYZ.BasisZ
    corners = [center + x.Multiply(a * length / 2) + z.Multiply(b * height / 2)
               for a in [-1, 1] for b in [-1, 1]]
    key = link.UniqueId + '|' + source.UniqueId
    fingerprint = '|'.join('{:.9f}'.format(v) for v in
                           [center.X, center.Y, center.Z, x.X, x.Y, tr.BasisY.X, tr.BasisY.Y, length, height, depth])
    return {'source': source, 'center': center, 'x': x, 'normal': tr.BasisY.Normalize(),
            'length': length, 'height': height, 'depth': depth, 'corners': corners,
            'key': key, 'fingerprint': fingerprint}


def overlaps_existing(item, wall, point, existing):
    x = item['x']
    normal = item.get('host_normal', item['normal'])
    wanted_mid = point-normal.Multiply(item['depth']/2)
    for inst in existing:
        if not inst.Host or inst.Host.Id != wall.Id:
            continue
        try:
            tr = inst.GetTransform()
            if abs(tr.BasisZ.DotProduct(normal)) < 0.999 or abs(tr.BasisX.DotProduct(x)) < 0.999:
                continue
            length = dimension(inst,'Length')
            height = dimension(inst,'Height')
            width = dimension(inst,'Width') if inst.LookupParameter('Width') else dimension(inst.Symbol,'Width')
            mid = tr.Origin+tr.BasisX.Multiply(length/2)+tr.BasisY.Multiply(height/2)-tr.BasisZ.Multiply(width/2)
            delta = mid-wanted_mid
            if abs(delta.DotProduct(normal))+item['depth']/2 <= width/2+TOL and abs(delta.DotProduct(x))+item['length']/2 <= length/2+TOL and abs(delta.Z)+item['height']/2 <= height/2+TOL:
                return number(inst)
        except Exception:
            continue
    return None


def plan(doc, link, walls):
    walls = list(walls)
    if not walls or any(not isinstance(w, DB.Wall) for w in walls):
        raise ValueError('Select host walls before running this button')
    existing = [e for e in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance)
                if e.Symbol.Family.Name in [TARGET_FAMILY, 'NCP-Void']]
    tracked = {}
    for e in existing:
        key = tag_value(e, 'SourceKey')
        if key:
            tracked.setdefault(key, []).append(e)
    faces = {}
    for wall in walls:
        if wall.WallType.Kind != DB.WallKind.Basic:
            continue
        rows = []
        for side in [DB.ShellLayerType.Interior, DB.ShellLayerType.Exterior]:
            try:
                refs = DB.HostObjectUtils.GetSideFaces(wall, side)
            except Exception:
                continue
            for ref in refs:
                face = wall.GetGeometryObjectFromReference(ref)
                if isinstance(face, DB.PlanarFace) and abs(face.FaceNormal.Z) < 0.001:
                    rows.append((ref, face))
        faces[wall.Id.Value] = rows
    ready, skipped = [], []
    sources = [e for e in DB.FilteredElementCollector(link.GetLinkDocument()).OfClass(DB.FamilyInstance)
               if e.Symbol.Family.Name in SOURCE_FAMILIES]
    label = link.GetLinkDocument().Title
    for source in sources:
        try:
            original = source_data(link, source)
            volume_points = original['corners']+[p-original['normal'].Multiply(original['depth']) for p in original['corners']]
            lo = DB.XYZ(min(p.X for p in volume_points), min(p.Y for p in volume_points), min(p.Z for p in volume_points))
            hi = DB.XYZ(max(p.X for p in volume_points), max(p.Y for p in volume_points), max(p.Z for p in volume_points))
            for wall in walls:
                bb = wall.get_BoundingBox(None)
                if not bb or lo.X > bb.Max.X+TOL or hi.X < bb.Min.X-TOL or lo.Y > bb.Max.Y+TOL or hi.Y < bb.Min.Y-TOL or lo.Z > bb.Max.Z+TOL or hi.Z < bb.Min.Z-TOL:
                    continue
                item = dict(original)
                item['key'] = original['key']+'|'+wall.UniqueId
                item['link_name'] = label
                item['link_id'] = link.Id.Value
                old = [e for key in [item['key'], original['key']] for e in tracked.get(key,[]) if e.Host and e.Host.Id == wall.Id]
                if old:
                    same = tag_value(old[0],'Fingerprint') == item['fingerprint']
                    reason = 'Already created: {}'.format(number(old[0])) if same else 'Source changed; review existing void {} manually'.format(number(old[0]))
                    skipped.append((number(source),label+'; wall {}: '.format(number(wall))+reason))
                    continue
                matches = []
                for ref, face in faces.get(wall.Id.Value,[]):
                    dot = face.FaceNormal.DotProduct(item['normal'])
                    if abs(dot) < 0.95:
                        continue
                    front = item['center'] if dot > 0 else item['center']-item['normal'].Multiply(item['depth'])
                    distance = (front-face.Origin).DotProduct(face.FaceNormal)
                    projected = front-face.FaceNormal.Multiply(distance)
                    corners = [projected+item['x'].Multiply(a*item['length']/2)+DB.XYZ.BasisZ.Multiply(b*item['height']/2) for a in [-1,1] for b in [-1,1]]
                    uvs = [uv(face,p) for p in corners]
                    fb = face.GetBoundingBox()
                    if min(p.U for p in uvs)>fb.Max.U+TOL or max(p.U for p in uvs)<fb.Min.U-TOL or min(p.V for p in uvs)>fb.Max.V+TOL or max(p.V for p in uvs)<fb.Min.V-TOL:
                        continue
                    reaches = distance >= -TOL and distance < item['depth']-TOL
                    matches.append((0 if reaches else 1,abs(distance),0 if dot>0 else 1,ref,face,projected,front))
                if not matches:
                    skipped.append((number(source),label+'; wall {}: no parallel hosting face intersects the opening footprint'.format(number(wall))))
                    continue
                matches.sort(key=lambda m:(m[0],m[1],m[2]))
                _,distance,_,ref,face,projected,front = matches[0]
                item.update({'wall':wall,'reference':ref,'point':projected,'face_point':projected,'linked_plane_offset_mm':distance*304.8,'host_normal':face.FaceNormal})
                covered = overlaps_existing(item,wall,projected,existing)
                if covered:
                    skipped.append((number(source),label+'; wall {}: fully covered by existing void {}'.format(number(wall),covered)))
                    continue
                ready.append(item)
        except Exception as ex:
            skipped.append((number(source),label+': '+str(ex)))
    return ready, skipped


def create_one(doc, base, item, schedule_level=None):
    wall = item['wall']
    volume = wall.get_Parameter(DB.BuiltInParameter.HOST_VOLUME_COMPUTED)
    if volume is None:
        raise ValueError('Wall volume cannot be verified')
    before = volume.AsDouble()
    symbol = base
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()
    inst = doc.Create.NewFamilyInstance(item['reference'], item.get('face_point', item['point']), item['x'], symbol)
    write_dimension(inst, 'Length', item['length'])
    write_dimension(inst, 'Height', item['height'])
    write_dimension(inst, 'Width', item['depth'])
    doc.Regenerate()
    tr = inst.GetTransform()
    corner = item['point'] - tr.BasisX.Multiply(item['length'] / 2) - tr.BasisY.Multiply(item['height'] / 2)
    DB.ElementTransformUtils.MoveElement(doc, inst.Id, corner - tr.Origin)
    if schedule_level is None:
        schedule_level = doc.GetElement(wall.LevelId)
    if schedule_level:
        p = inst.get_Parameter(DB.BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM)
        if p and not p.IsReadOnly:
            p.Set(schedule_level.Id)
    doc.Regenerate()
    if volume.AsDouble() >= before - 1e-8:
        if DB.InstanceVoidCutUtils.IsVoidInstanceCuttingElement(inst) and DB.InstanceVoidCutUtils.CanBeCutWithVoid(wall):
            if not DB.InstanceVoidCutUtils.InstanceVoidCutExists(wall, inst):
                DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, inst)
                doc.Regenerate()
    removed = before - volume.AsDouble()
    if removed <= 1e-8:
        raise ValueError('No wall material was cut; creation rolled back')
    tr = inst.GetTransform()
    actual_center = tr.Origin + tr.BasisX.Multiply(item['length'] / 2) + tr.BasisY.Multiply(item['height'] / 2)
    if actual_center.DistanceTo(item['point']) > 1e-6:
        raise ValueError('Placement centre verification failed')
    for name, expected in [('Length', item['length']), ('Height', item['height'])]:
        if abs(dimension(inst, name) - expected) > 1e-8:
            raise ValueError('Dimension verification failed: ' + name)
    if abs(dimension(inst, 'Width') - item['depth']) > 1e-8:
        raise ValueError('Depth verification failed')
    tag(inst, item['key'], item['fingerprint'])
    return inst, removed


def execute(doc, base, ready, schedule_level=None, preview=True):
    created, failed = [], []
    transaction = DB.Transaction(doc, 'Linked Wall Voids - preview' if preview else 'Linked Wall Voids')
    transaction.Start()
    try:
        for item in ready:
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                inst, removed = create_one(doc, base, item, schedule_level)
                created.append({'source': number(item['source']), 'void': number(inst), 'wall': number(item['wall']), 'removed_ft3': removed, 'length_mm': round(item['length']*304.8,3), 'height_mm': round(item['height']*304.8,3), 'depth_mm': round(item['depth']*304.8,3), 'projection_mm': round(item.get('linked_plane_offset_mm',0),3), 'key': item['key'], 'link': item.get('link_name',''), 'link_id': item.get('link_id',0)})
                st.Commit()
            except Exception as ex:
                st.RollBack()
                failed.append((number(item['source']), item.get('link_name','')+'; wall {}: '.format(number(item['wall']))+str(ex)))
        if preview:
            transaction.RollBack()
        elif transaction.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Revit did not commit the transaction')
    except Exception:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        raise
    return created, failed
