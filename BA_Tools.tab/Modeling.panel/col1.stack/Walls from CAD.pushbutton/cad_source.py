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
    options = DB.Options()
    options.IncludeNonVisibleObjects = True
    walk(instance.get_Geometry(options))
    return lines

