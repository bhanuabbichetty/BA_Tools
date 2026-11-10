import os
import re
import math
import codecs
import shutil
import tempfile
import time
from pyrevit import DB


TOL = 1.0 / 304.8


def eid(element):
    return element.Id.Value if hasattr(element.Id, 'Value') else element.Id.IntegerValue


def clean_label(value):
    value = value.replace('\\P', ' ').replace('\\~', ' ')
    value = re.sub(r'\\[A-Za-z]+[^;]*;', '', value)
    value = value.replace('{', '').replace('}', '').strip()
    if re.match(r"^[A-Za-z0-9]+(?:[.\-/'\u2032][A-Za-z0-9]+)*['\u2032]?$", value) and len(value) <= 24:
        return value
    return None


def read_rows(path):
    with codecs.open(path, 'r', 'utf-8-sig') as stream:
        rows = [line.rstrip('\r\n').split('\t') for line in stream]
    if not rows or rows[-1] != ['DONE']:
        raise ValueError('AutoCAD did not finish reading this DWG. No grids were placed.')
    return rows[:-1]


def read_dwg(path, folder):
    from System.Diagnostics import Process, ProcessStartInfo, ProcessWindowStyle
    roots = [os.path.join(os.environ.get('ProgramW6432', r'C:\Program Files'), 'Autodesk'),
             os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Autodesk')]
    engines = []
    for root in set(roots):
        if os.path.isdir(root):
            for name in os.listdir(root):
                exe = os.path.join(root, name, 'accoreconsole.exe')
                if name.startswith('AutoCAD ') and os.path.isfile(exe):
                    engines.append(exe)
    if not engines:
        raise ValueError('CAD labels require an installed AutoCAD Core Console. Revit links can be read directly.')
    if not os.path.isfile(path):
        raise ValueError('The linked DWG is not available locally: ' + path)
    temp = tempfile.mkdtemp(prefix='pyrevit-grid-link-')
    try:
        copy = os.path.join(temp, 'source.dwg')
        output = os.path.join(temp, 'grids.tsv')
        commands = os.path.join(temp, 'read.scr')
        shutil.copy2(path, copy)
        with codecs.open(os.path.join(folder, 'read_grids.lsp'), 'r', 'utf-8') as stream:
            lisp = stream.read().replace('\r', ' ').replace('\n', ' ')
        with codecs.open(commands, 'w', 'utf-8') as stream:
            stream.write('(setenv "GRID_READER_OUTPUT" "' + output.replace('\\', '/') + '")\n')
            stream.write(lisp + '\n(c:GRREAD)\n_QUIT\n')
        info = ProcessStartInfo()
        info.FileName = sorted(engines, reverse=True)[0]
        info.Arguments = '/i "{0}" /s "{1}" /l en-US'.format(copy, commands)
        info.WorkingDirectory = temp
        info.UseShellExecute = False
        info.CreateNoWindow = True
        info.WindowStyle = ProcessWindowStyle.Hidden
        info.RedirectStandardOutput = True
        info.RedirectStandardError = True
        process = Process.Start(info)
        process.BeginOutputReadLine()
        process.BeginErrorReadLine()
        complete = False
        deadline = time.time()+120.0
        while time.time()<deadline:
            if os.path.isfile(output):
                try:
                    with codecs.open(output,'r','utf-8-sig') as stream:
                        complete = stream.read().rstrip().endswith('DONE')
                except (IOError,UnicodeError):
                    complete = False
            if complete or process.WaitForExit(200):
                break
        if not process.HasExited:
            process.Kill()
            process.WaitForExit(5000)
        process.Dispose()
        if not complete:
            raise ValueError('AutoCAD did not complete the drawing read within 120 seconds. No grids were placed.')
        return read_rows(output)
    finally:
        try:
            shutil.rmtree(temp)
        except OSError:
            pass


def cad_geometry(doc, instance):
    lines = []
    def walk(geometry):
        for item in geometry:
            if isinstance(item, DB.GeometryInstance):
                walk(item.GetInstanceGeometry())
            else:
                style = doc.GetElement(item.GraphicsStyleId)
                layer = style.GraphicsStyleCategory.Name if style else ''
                if isinstance(item, DB.Line):
                    lines.append((layer, item))
                elif isinstance(item, DB.PolyLine):
                    points = list(item.GetCoordinates())
                    for first, last in zip(points[:-1], points[1:]):
                        if first.DistanceTo(last) > TOL:
                            lines.append((layer, DB.Line.CreateBound(first, last)))
    walk(instance.get_Geometry(DB.Options()))
    return lines


def same_axis(first, second):
    if isinstance(first, DB.Line) and isinstance(second, DB.Line):
        if abs(first.Direction.DotProduct(second.Direction)) < 0.999999:
            return False
        delta = second.GetEndPoint(0).Subtract(first.GetEndPoint(0))
        return delta.CrossProduct(first.Direction).GetLength() < TOL
    if isinstance(first, DB.Arc) and isinstance(second, DB.Arc):
        return abs(first.Radius - second.Radius) < TOL and first.Center.DistanceTo(second.Center) < TOL
    return False


def flat_point(point, z):
    return DB.XYZ(point.X, point.Y, z)


def flat_curve(curve, z):
    if abs(curve.GetEndPoint(0).Z - curve.GetEndPoint(1).Z) > TOL:
        raise ValueError('A source grid is tilted out of the plan plane.')
    first, last = [flat_point(curve.GetEndPoint(i), z) for i in (0, 1)]
    if isinstance(curve, DB.Line):
        return DB.Line.CreateBound(first, last)
    if isinstance(curve, DB.Arc):
        return DB.Arc.Create(first, last, flat_point(curve.Evaluate(0.5, True), z))
    raise ValueError('Only straight and circular grid curves are supported.')


def cad_specs(doc, instance, rows, layers, minimum=1000.0 / 304.8):
    geometry = [(layer, line) for layer, line in cad_geometry(doc, instance) if layer in layers and line.Length >= minimum]
    raw = [r for r in rows if r[0] == 'L' and r[1] in layers]
    if not geometry or not raw:
        raise ValueError('No usable grid axes were found on the selected CAD layers.')
    longest_raw = max(math.hypot(float(r[4])-float(r[2]), float(r[5])-float(r[3])) for r in raw)
    transform = instance.GetTotalTransform()
    scale = max(line.Length for layer, line in geometry) / longest_raw / transform.BasisX.GetLength()
    def world(x, y):
        return transform.OfPoint(DB.XYZ(float(x)*scale, float(y)*scale, 0.0))
    label_rows = [r for r in rows if r[0] == 'T' and clean_label(r[4])]
    circles = []
    for row in rows:
        if row[0] == 'C':
            center = world(row[2], row[3])
            radius = float(row[4])*scale*transform.BasisX.GetLength()
            candidates = [(world(t[2], t[3]).DistanceTo(center), clean_label(t[4])) for t in label_rows]
            candidates.sort()
            if candidates and candidates[0][0] < radius*1.5:
                circles.append((candidates[0][1], center, radius))
    if not circles:
        raise ValueError('No text-labelled circular CAD grid bubbles were found. Labels must be TEXT/MTEXT/attributes, not exploded outlines.')
    axes = []
    for row in raw:
        first, last = world(row[2], row[3]), world(row[4], row[5])
        if first.DistanceTo(last) < minimum:
            continue
        line = DB.Line.CreateBound(first, last)
        matches = [g for layer, g in geometry if same_axis(line, g) and abs(line.Length-g.Length) < TOL*2]
        if not matches:
            raise ValueError('The CAD coordinate mapping could not be verified against the linked geometry. Check the link units and reload the DWG.')
        if any(same_axis(line, old) for old in axes):
            continue
        axes.append(matches[0])
    proposals = []
    for index, axis in enumerate(axes):
        for name, center, radius in circles:
            distance = min(center.DistanceTo(axis.GetEndPoint(i)) for i in (0, 1))
            if distance < max(radius*5, minimum):
                proposals.append((distance, index, name, center, radius))
    proposals.sort(key=lambda value: value[0])
    used_axes, used_names, matched = set(), set(), []
    for distance, index, name, center, radius in proposals:
        if index not in used_axes and name not in used_names:
            used_axes.add(index)
            used_names.add(name)
            matched.append({'name':name, 'curve':axes[index], 'bubble':center, 'radius':radius})
    if len(matched) != len(axes):
        raise ValueError('Matched labels to {0} of {1} axes. Select only the grid axis layers, or repair missing/duplicate CAD labels. No grids were placed.'.format(len(matched), len(axes)))
    return matched


def revit_specs(instance):
    linked = instance.GetLinkDocument()
    if not linked:
        raise ValueError('Load the selected Revit link first.')
    transform = instance.GetTotalTransform()
    specs, grouped = [], set()
    for grid in DB.FilteredElementCollector(linked).OfClass(DB.Grid):
        multi = DB.MultiSegmentGrid.GetMultiSegementGridId(grid)
        key = multi.Value if hasattr(multi, 'Value') else multi.IntegerValue
        if key != -1:
            if key in grouped:
                continue
            grouped.add(key)
            parent = linked.GetElement(multi)
            segments = [linked.GetElement(i) for i in parent.GetGridIds()]
            specs.append({'name':parent.Text, 'segments':[g.Curve.CreateTransformed(transform) for g in segments]})
        else:
            specs.append({'name':grid.Name, 'curve':grid.Curve.CreateTransformed(transform), 'bubble':None})
    return specs


def convert_name(name, convention):
    if convention == 'Uppercase letters':
        return name.upper()
    if name.isdigit():
        if convention == 'Numbers without leading zeros':
            return str(int(name))
        if convention == 'Numbers with at least two digits':
            return '%02d' % int(name)
    return name


def plan_changes(doc, specs, z, convention='Preserve source labels'):
    existing = []
    handled = set()
    for grid in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
        multi = DB.MultiSegmentGrid.GetMultiSegementGridId(grid)
        key = multi.Value if hasattr(multi,'Value') else multi.IntegerValue
        if key == -1:
            existing.append({'name':grid.Name,'curves':[flat_curve(grid.Curve,z)]})
        elif key not in handled:
            handled.add(key)
            parent = doc.GetElement(multi)
            existing.append({'name':parent.Text,'curves':[flat_curve(doc.GetElement(i).Curve,z) for i in parent.GetGridIds()]})
    names = dict((g['name'].lower(), g) for g in existing)
    pending, skipped, conflicts, seen = [], [], [], set()
    for source in specs:
        item = dict(source)
        name = convert_name(item['name'], convention)
        if name.lower() in seen:
            raise ValueError('Naming conversion produces duplicate grid name: ' + name)
        seen.add(name.lower())
        item['name'] = name
        curves = [flat_curve(c, z) for c in item.get('segments', [item.get('curve')])]
        item['curves'] = curves
        equal = [g for g in existing if any(same_axis(old,c) for old in g['curves'] for c in curves)]
        named = names.get(name.lower())
        if named:
            if len(named['curves'])==len(curves) and all(any(same_axis(old,c) for old in named['curves']) for c in curves):
                skipped.append(name)
            else:
                conflicts.append(name + ': name already exists at a different location')
        elif equal:
            conflicts.append(name + ': axis already exists as ' + equal[0]['name'])
        else:
            pending.append(item)
    return pending, skipped, conflicts


def create_grids(doc, view, pending):
    created = []
    grid_type = next(iter(DB.FilteredElementCollector(doc).OfClass(DB.GridType)))
    plane = None
    transaction = DB.Transaction(doc, 'Grids from Link')
    transaction.Start()
    try:
        for item in pending:
            curves = item['curves']
            if len(curves) > 1:
                if plane is None:
                    plane = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, curves[0].GetEndPoint(0)))
                loop = DB.CurveLoop()
                remaining = list(curves)
                starter = None
                for candidate in curves:
                    for side in (0,1):
                        endpoint = candidate.GetEndPoint(side)
                        neighbours = sum(1 for other in curves if any(other.GetEndPoint(k).DistanceTo(endpoint)<TOL for k in (0,1)))
                        if neighbours == 1:
                            starter = candidate if side==0 else candidate.CreateReversed()
                            original = candidate
                            break
                    if starter is not None:
                        break
                if starter is None:
                    raise ValueError('Could not find an open end of multi-segment grid: '+item['name'])
                remaining.remove(original)
                loop.Append(starter)
                end = starter.GetEndPoint(1)
                while remaining:
                    found = None
                    for curve in remaining:
                        if curve.GetEndPoint(0).DistanceTo(end) < TOL:
                            found = curve
                            break
                        if curve.GetEndPoint(1).DistanceTo(end) < TOL:
                            found = curve.CreateReversed()
                            break
                    if found is None:
                        raise ValueError('Disconnected multi-segment grid: ' + item['name'])
                    remaining = [c for c in remaining if not (c.GetEndPoint(0).DistanceTo(found.GetEndPoint(0)) < TOL and c.GetEndPoint(1).DistanceTo(found.GetEndPoint(1)) < TOL) and not (c.GetEndPoint(1).DistanceTo(found.GetEndPoint(0)) < TOL and c.GetEndPoint(0).DistanceTo(found.GetEndPoint(1)) < TOL)]
                    loop.Append(found)
                    end = found.GetEndPoint(1)
                parent = doc.GetElement(DB.MultiSegmentGrid.Create(doc, grid_type.Id, loop, plane.Id))
                parent.Text = item['name']
                created.append(eid(parent))
            else:
                source_curve = curves[0]
                bubble = item.get('bubble')
                if bubble and isinstance(source_curve, DB.Line):
                    points = [source_curve.GetEndPoint(i) for i in (0,1)]
                    near = 0 if bubble.DistanceTo(points[0]) < bubble.DistanceTo(points[1]) else 1
                    inward = points[1-near].Subtract(points[near]).Normalize()
                    projection = points[near].Add(inward.Multiply(bubble.Subtract(points[near]).DotProduct(inward)))
                    points[near] = projection.Add(inward.Multiply(item.get('radius',0.0)))
                    source_curve = DB.Line.CreateBound(points[0],points[1])
                grid = DB.Grid.Create(doc, source_curve)
                grid.Name = item['name']
                created.append(eid(grid))
                doc.Regenerate()
                curve = grid.GetCurvesInView(DB.DatumExtentType.Model, view)[0]
                first, last = [curve.GetEndPoint(i) for i in (0, 1)]
                bubble = item.get('bubble')
                if bubble:
                    head = DB.DatumEnds.End0 if flat_point(bubble,first.Z).DistanceTo(first) < flat_point(bubble,last.Z).DistanceTo(last) else DB.DatumEnds.End1
                else:
                    head = DB.DatumEnds.End0 if (first.Y>last.Y if abs(first.Y-last.Y)>abs(first.X-last.X) else first.X<last.X) else DB.DatumEnds.End1
                tail = DB.DatumEnds.End1 if head==DB.DatumEnds.End0 else DB.DatumEnds.End0
                grid.ShowBubbleInView(head, view)
                grid.HideBubbleInView(tail, view)
                if bubble and isinstance(curve, DB.Line):
                    vertical = abs(curve.Direction.Y)>0.999999
                    horizontal = abs(curve.Direction.X)>0.999999
                    anchor = first if head==DB.DatumEnds.End0 else last
                    offset = bubble.X-anchor.X if vertical else bubble.Y-anchor.Y
                    if (vertical or horizontal) and abs(offset)>0.4:
                        leader = grid.AddLeader(head, view)
                        gap = leader.Elbow.DistanceTo(leader.End)
                        elbow = leader.Elbow
                        leader.Elbow = DB.XYZ(bubble.X+gap,elbow.Y,elbow.Z) if vertical else DB.XYZ(elbow.X,bubble.Y+gap,elbow.Z)
                        grid.SetLeader(head, view, leader)
        transaction.Commit()
    except:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        raise
    return created


def source_options(doc, links):
    from pyrevit.revit.db.query import get_name
    options = {}
    for link in links:
        is_revit = isinstance(link, DB.RevitLinkInstance)
        element = link if is_revit else doc.GetElement(link.GetTypeId())
        name = get_name(element)
        label = '{0}: {1} [ID {2}]'.format('Revit' if is_revit else 'CAD', name, eid(link))
        options[label] = link
    return options
