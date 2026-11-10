import os
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Data')
from System.IO import StreamReader
from System.Windows.Markup import XamlReader
from System.Windows import Visibility
from System.Windows.Controls import CheckBox
from System.Windows.Media import BrushConverter
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority
from System.Data import DataTable
from System import Action
from pyrevit import DB
import grid_link


class GridSetup(object):
    def __init__(self, doc, view, selected_ids=None, owner=None):
        self.doc, self.view = doc, view
        self.folder = os.path.dirname(__file__)
        self.specs, self.pending = None, []
        self.conflicts, self.skipped = [], []
        self._loading, self._busy = True, False
        self._geometry = {}
        with StreamReader(os.path.join(self.folder,'GridSetup.xaml')) as stream:
            self.window = XamlReader.Load(stream.BaseStream)
        with StreamReader(os.path.join(self.folder,'BAWindowStyles.xaml')) as stream:
            self.window.Resources.MergedDictionaries.Add(XamlReader.Load(stream.BaseStream))
        if owner:
            WindowInteropHelper(self.window).Owner = owner
        for name in ['Sources','SourceInfo','Naming','NamingHint','TargetPlan','CadPanel','Layers','Minimum','RevitHint','Summary','Preview','Status','Read','Create','CloseTop']:
            setattr(self,name,self.window.FindName(name))
        self.table = DataTable()
        for column in ['SourceName','RevitName','Status']:
            self.table.Columns.Add(column)
        self.Preview.ItemsSource = self.table.DefaultView
        links = list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance))
        links += [e for e in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance) if e.IsLinked]
        self.options = grid_link.source_options(doc,links)
        labels = sorted(self.options)
        for label in labels:
            self.Sources.Items.Add(label)
        conventions = ['Preserve source labels','Numbers without leading zeros','Numbers with at least two digits','Uppercase letters']
        for name in conventions:
            self.Naming.Items.Add(name)
        self.Naming.SelectedIndex = 0
        self.TargetPlan.Text = view.Name
        selected_ids = selected_ids or set()
        preferred = [label for label in labels if grid_link.eid(self.options[label]) in selected_ids]
        if labels:
            self.Sources.SelectedItem = preferred[0] if len(preferred)==1 else labels[0]
        self.Sources.SelectionChanged += self._source_changed
        self.Naming.SelectionChanged += self._naming_changed
        self.Minimum.TextChanged += self._invalidate
        self.Read.Click += self._read
        self.Create.Click += self._create
        self.CloseTop.Click += self._close
        self.window.FindName('HeaderDrag').MouseLeftButtonDown += self._drag
        self._loading = False
        self._source_changed(None,None)

    def _status(self, text, error=False):
        self.Status.Text = text
        self.Status.Foreground = BrushConverter().ConvertFromString('#FFA5A5' if error else '#A6CAFF')

    def _source(self):
        label = self.Sources.SelectedItem
        return self.options.get(str(label)) if label is not None else None

    def _is_cad(self):
        return isinstance(self._source(),DB.ImportInstance)

    def _invalidate(self, sender, event):
        if self._loading or self._busy:
            return
        self.specs, self.pending = None, []
        self.table.Rows.Clear()
        self.Create.IsEnabled = False
        self.Summary.Text = 'Read the linked file to preview its grids.'
        self._status('Settings changed. Click READ GRIDS to refresh the preview.')

    def _source_changed(self, sender, event):
        if self._loading or self._busy:
            return
        self._invalidate(None,None)
        self._loading = True
        try:
            self.Layers.Items.Clear()
            source = self._source()
            self.Read.IsEnabled = source is not None
            if source is None:
                self.SourceInfo.Text = 'No linked CAD or Revit files found.'
                self._status('Link a CAD or Revit file, close this window and open the tool again.',True)
                return
            cad = self._is_cad()
            self.CadPanel.Visibility = Visibility.Visible if cad else Visibility.Collapsed
            self.RevitHint.Visibility = Visibility.Collapsed if cad else Visibility.Visible
            self.SourceInfo.Text = str(self.Sources.SelectedItem).split(': ',1)[-1]
            if cad:
                key = grid_link.eid(source)
                if key not in self._geometry:
                    self._geometry[key] = grid_link.cad_geometry(self.doc,source)
                layers = sorted(set(layer for layer,line in self._geometry[key] if line.Length>grid_link.TOL))
                suggested = [layer for layer in layers if any(word in layer.lower() for word in ['grid','axis','axes']) and not any(word in layer.lower() for word in ['dim','text','bubble','head'])]
                layers.sort(key=lambda name:(name not in suggested,name.lower()))
                for layer in layers:
                    check = CheckBox()
                    check.Content = layer
                    check.ToolTip = layer
                    check.IsChecked = layer in suggested
                    check.Checked += self._invalidate
                    check.Unchecked += self._invalidate
                    self.Layers.Items.Add(check)
                self._status('Grid axis layers selected automatically. Review them, then read grids.' if suggested else 'Select the CAD grid axis layers, then read grids.')
            else:
                self._status('Revit link selected. Click READ GRIDS to preview names and locations.')
        except Exception as error:
            self.Read.IsEnabled = False
            self._status(str(error),True)
        finally:
            self._loading = False

    def _naming_changed(self, sender, event):
        if self._loading or self._busy:
            return
        convention = str(self.Naming.SelectedItem)
        hints = {'Preserve source labels':'Keep the source numbers, leading zeros and letters.','Numbers without leading zeros':'Numeric labels: 01 becomes 1. Letter labels stay unchanged.','Numbers with at least two digits':'Numeric labels: 1 becomes 01. Letter labels stay unchanged.','Uppercase letters':'Letter labels become uppercase. Numeric labels stay unchanged.'}
        self.NamingHint.Text = hints.get(convention,'')
        if self.specs is not None:
            try:
                self._refresh()
            except Exception as error:
                self.Create.IsEnabled = False
                self._status(str(error),True)

    def _refresh(self):
        naming = str(self.Naming.SelectedItem)
        self.pending,self.skipped,self.conflicts = grid_link.plan_changes(self.doc,self.specs,self.view.GenLevel.Elevation,naming)
        pending = set(item['name'] for item in self.pending)
        skipped = set(self.skipped)
        self.table.Rows.Clear()
        for spec in sorted(self.specs,key=lambda item:item['name']):
            name = grid_link.convert_name(spec['name'],naming)
            status = 'Ready to create' if name in pending else 'Already exists' if name in skipped else 'Conflict'
            self.table.Rows.Add(spec['name'],name,status)
        self.Summary.Text = '{0} source grids  |  {1} new  |  {2} existing  |  {3} conflicts'.format(len(self.specs),len(self.pending),len(self.skipped),len(self.conflicts))
        self.Create.IsEnabled = bool(self.pending) and not self.conflicts
        self.Create.Content = 'CREATE {0} GRIDS'.format(len(self.pending)) if self.pending else 'CREATE GRIDS'
        if self.conflicts:
            self._status('Resolve conflicts before creation:\n'+'\n'.join(self.conflicts),True)
        elif self.pending:
            self._status('Preview ready. Review the names, then click CREATE GRIDS.')
        else:
            self._status('All source grids already exist at matching positions. No duplicates will be created.')

    def _set_busy(self, busy):
        self._busy = busy
        for control in [self.Sources,self.Naming,self.CadPanel,self.Read,self.CloseTop]:
            control.IsEnabled = not busy
        self.Create.IsEnabled = False
        self.window.Dispatcher.Invoke(DispatcherPriority.Render,Action(lambda:None))

    def _read(self, sender, event):
        if self._busy:
            return
        source = self._source()
        if source is None:
            return
        self.specs = None
        try:
            if self._is_cad():
                layers = [str(check.Content) for check in self.Layers.Items if check.IsChecked]
                if not layers:
                    raise ValueError('Select at least one CAD grid axis layer.')
                try:
                    minimum = float(self.Minimum.Text)
                except ValueError:
                    raise ValueError('Minimum axis length must be a number in millimetres.')
                if minimum<=0:
                    raise ValueError('Minimum axis length must be greater than zero.')
                self._status('Reading CAD geometry and text labels. Please wait...')
                self._set_busy(True)
                reference = self.doc.GetElement(source.GetTypeId()).GetExternalFileReference()
                path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath())
                rows = grid_link.read_dwg(path,self.folder)
                self.specs = grid_link.cad_specs(self.doc,source,rows,layers,minimum/304.8)
            else:
                self._status('Reading grids from the Revit link...')
                self._set_busy(True)
                self.specs = grid_link.revit_specs(source)
            if not self.specs:
                raise ValueError('No grids were found in the selected source.')
            self._refresh()
        except Exception as error:
            self.specs = None
            self.table.Rows.Clear()
            self.Summary.Text = 'Grid preview could not be loaded.'
            self._status(str(error),True)
        finally:
            self._set_busy(False)
            self.Read.IsEnabled = self._source() is not None
            self.Create.IsEnabled = self.specs is not None and bool(self.pending) and not self.conflicts

    def _create(self, sender, event):
        if self._busy or self.specs is None:
            return
        try:
            self._refresh()
            if self.conflicts or not self.pending:
                return
            self._status('Creating grids...')
            self._set_busy(True)
            count = len(grid_link.create_grids(self.doc,self.view,self.pending))
            self._refresh()
            self._status('Created {0} grids. Undo this placement with Ctrl+Z.'.format(count))
        except Exception as error:
            self._status('Creation stopped: '+str(error),True)
        finally:
            self._set_busy(False)
            self.Create.IsEnabled = self.specs is not None and bool(self.pending) and not self.conflicts

    def _drag(self, sender, event):
        if not self._busy:
            self.window.DragMove()

    def _close(self, sender, event):
        if not self._busy:
            self.window.Close()

    def show(self):
        self.window.ShowDialog()
