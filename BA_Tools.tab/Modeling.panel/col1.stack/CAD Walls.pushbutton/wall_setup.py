import os
import json
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Data')
from System.IO import StreamReader
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority
from System.Data import DataTable
from System import Action,Boolean
from pyrevit import DB
from pyrevit.revit.db.query import get_name
import cad_source
import wall_engine
import wall_multi


class WallSetup(object):
    def __init__(self,doc,view,selected=None,owner=None):
        self.doc,self.view=doc,view
        self.folder=os.path.dirname(__file__)
        self.source,self.batches=None,[]
        self._loading,self._busy,self._updating=True,False,False
        self._errors=[]
        self.saved={}
        try:
            with open(os.path.join(self.folder,'wall_settings.json')) as stream:
                self.saved=json.load(stream)
        except (IOError,ValueError):
            pass
        with StreamReader(os.path.join(self.folder,'WallSetup.xaml')) as stream:
            self.window=XamlReader.Load(stream.BaseStream)
        with StreamReader(os.path.join(self.folder,'BAWindowStyles.xaml')) as stream:
            self.window.Resources.MergedDictionaries.Add(XamlReader.Load(stream.BaseStream))
        if owner:
            WindowInteropHelper(self.window).Owner=owner
        for name in ['Sources','BaseLevel','TopLevel','Unjoin','CreateTypes','Keyway','Mapping','Summary','Preview','Status','Read','Create','CloseTop']:
            setattr(self,name,self.window.FindName(name))
        self.mapping=DataTable()
        self.mapping.Columns.Add('Use',Boolean)
        for column in ['Layer','Width','Type','TopOffset','Status']:
            self.mapping.Columns.Add(column)
        self.Mapping.ItemsSource=self.mapping.DefaultView
        self.preview=DataTable()
        for column in ['Layer','Length','Status','Face']:
            self.preview.Columns.Add(column)
        self.Preview.ItemsSource=self.preview.DefaultView
        self.links={}
        for link in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
            if link.IsLinked:
                self.links['{0} [ID {1}]'.format(get_name(doc.GetElement(link.GetTypeId())),cad_source.eid(link))]=link
        for label in sorted(self.links):
            self.Sources.Items.Add(label)
        preferred=[label for label in self.links if cad_source.eid(self.links[label]) in (selected or set())]
        if self.links:
            self.Sources.SelectedItem=preferred[0] if len(preferred)==1 else sorted(self.links)[0]
        levels=sorted(list(DB.FilteredElementCollector(doc).OfClass(DB.Level)),key=lambda level:level.Elevation)
        self.levels=dict((level.Name,level) for level in levels)
        for level in levels:
            self.BaseLevel.Items.Add(level.Name)
            self.TopLevel.Items.Add(level.Name)
        base='GF S.S.L.' if 'GF S.S.L.' in self.levels else view.GenLevel.Name
        above=[level.Name for level in levels if level.Elevation>self.levels[base].Elevation]
        self.BaseLevel.SelectedItem=base
        self.TopLevel.SelectedItem='FIRST S.S.L.' if 'FIRST S.S.L.' in above else above[0] if above else base
        self.mapping.ColumnChanged+=self._row_changed
        self.Sources.SelectionChanged+=self._source_changed
        for control in [self.BaseLevel,self.TopLevel]:
            control.SelectionChanged+=self._changed
        self.Keyway.TextChanged+=self._changed
        for control in [self.Unjoin,self.CreateTypes]:
            control.Checked+=self._changed
            control.Unchecked+=self._changed
        self.Read.Click+=self._read
        self.Create.Click+=self._create
        self.CloseTop.Click+=self._close
        self.window.FindName('HeaderDrag').MouseLeftButtonDown+=self._drag
        self._loading=False
        self._source_changed(None,None)

    def _status(self,text,error=False):
        self.Status.Text=text
        self.Status.Foreground=BrushConverter().ConvertFromString('#FFA5A5' if error else '#59BAFF')

    def _link(self):
        return self.links.get(unicode(self.Sources.SelectedItem))

    def _source_changed(self,sender,event):
        if self._loading or self._busy:
            return
        self.source,self.batches=None,[]
        self._loading=True
        self.mapping.Rows.Clear()
        self.preview.Rows.Clear()
        self._loading=False
        self.Create.IsEnabled=False
        self.Read.IsEnabled=self._link() is not None
        self.Summary.Text='Read the CAD drawing to build the layer plan.'
        self._status('Ready. READ CAD detects wall layers and thicknesses.' if self._link() else 'Link a CAD file, then reopen this tool.',self._link() is None)

    def _row_changed(self,sender,event):
        if not self._loading and not self._busy and not self._updating and event.Column.ColumnName in ['Use','TopOffset']:
            self._refresh()

    def _changed(self,sender,event):
        if not self._loading and not self._busy:
            self._refresh()

    def _refresh(self):
        self.Create.IsEnabled=False
        if self.source is None:
            return
        self._updating=True
        self.batches,self._errors=[],[]
        self.preview.Rows.Clear()
        try:
            base=self.levels[unicode(self.BaseLevel.SelectedItem)]
            top=self.levels[unicode(self.TopLevel.SelectedItem)]
            keyway=wall_engine.number(self.Keyway.Text,'Keyway gap')
            if keyway<0:
                raise ValueError('Keyway gap cannot be negative.')
            for row in self.mapping.Rows:
                if not bool(row['Use']):
                    row['Status']='Excluded'
                    continue
                layer=unicode(row['Layer'])
                try:
                    top_mm=wall_engine.number(unicode(row['TopOffset']),'Top offset')
                    batch=wall_multi.plan_batch(self.doc,self.source,layer,base,top,top_mm,keyway,bool(self.CreateTypes.IsChecked))
                    row['Type']=wall_multi.type_name(batch['type'])+(' (new)' if isinstance(batch['type'],wall_multi.PlannedType) else '')
                    self.batches.append(batch)
                except Exception as error:
                    row['Status']='Needs attention'
                    self._errors.append(layer+': '+unicode(error))
            wall_multi.cross_conflicts(self.batches)
            for batch in self.batches:
                row=next(r for r in self.mapping.Rows if unicode(r['Layer'])==batch['layer'])
                new=sum(r['status']=='New' for r in batch['records'])
                old=sum(r['status']=='Existing' for r in batch['records'])
                conflict=sum(r['status']=='Conflict' for r in batch['records'])
                row['Status']='{0} new / {1} existing'.format(new,old) if not conflict else '{0} conflicts'.format(conflict)
                for item in batch['records']:
                    self.preview.Rows.Add(batch['layer'],'{0:,.0f}'.format(item['length']*304.8),{'New':'Ready to create','Existing':'Already exists','Conflict':'Overlap / face conflict'}[item['status']], 'Marked exterior' if 'exterior_normal' in item else 'Original method')
            new=sum(item['status']=='New' for batch in self.batches for item in batch['records'])
            old=sum(item['status']=='Existing' for batch in self.batches for item in batch['records'])
            conflict=sum(item['status']=='Conflict' for batch in self.batches for item in batch['records'])
            self.Summary.Text='{0} layers / {1} new walls / {2} existing / {3} conflicts / {4} layer errors'.format(len(self.batches),new,old,conflict,len(self._errors))
            self.Create.Content='CREATE {0} WALLS'.format(new) if new else 'CREATE WALLS'
            self.Create.IsEnabled=new>0 and not conflict and not self._errors
            if self._errors:
                self._status(self._errors[0]+'\nCorrect the settings or uncheck that layer.',True)
            elif conflict:
                self._status('Resolve existing wall overlaps or exterior-face conflicts before creation. Existing walls will not be flipped automatically.',True)
            elif new:
                marked_faces=any(wall_engine.uses_erection_marks(batch['width']/304.8) for batch in self.batches)
                self._status('Preview ready. ERECTION_MARK faces verified for all selected wall layers. Base offset: +16 mm.' if marked_faces else 'Preview ready. Base offset is fixed at +16 mm. Review each layer top offset.')
            elif self.batches:
                self._status('All selected walls already exist. No duplicates will be created.')
            else:
                self._status('Select at least one wall layer.')
        except Exception as error:
            self._errors=[unicode(error)]
            self._status(unicode(error),True)
        finally:
            self._updating=False

    def _busy_state(self,busy):
        self._busy=busy
        for control in [self.Sources,self.BaseLevel,self.TopLevel,self.Keyway,self.Unjoin,self.CreateTypes,self.Mapping,self.Read,self.CloseTop]:
            control.IsEnabled=not busy
        self.Create.IsEnabled=False
        self.window.Dispatcher.Invoke(DispatcherPriority.Render,Action(lambda:None))

    def _read(self,sender,event):
        if self._busy or not self._link():
            return
        try:
            self._status('Reading saved CAD drawing...')
            self._busy_state(True)
            self.source=wall_engine.read_source(self.doc,self._link(),self.folder)
            self._loading=True
            previous=dict((unicode(r['Layer']),{'top':unicode(r['TopOffset']),'use':bool(r['Use'])}) for r in self.mapping.Rows)
            self.mapping.Rows.Clear()
            for layer in self.source['layers']:
                width=wall_multi.thickness(layer)
                if width is None:
                    continue
                setting=previous.get(layer,self.saved.get(layer,{'top':'0','use':True}))
                wall_type=wall_multi.resolve_type(self.doc,width)
                self.mapping.Rows.Add(bool(setting.get('use',True)),layer,'{0:g}'.format(width),wall_multi.type_name(wall_type)+(' (new)' if isinstance(wall_type,wall_multi.PlannedType) else ''),unicode(setting.get('top','0')),'Ready')
            self._loading=False
        except Exception as error:
            self.source=None
            self._status(unicode(error),True)
        finally:
            self._loading=False
            self._busy_state(False)
        if self.source is not None:
            if self.mapping.Rows.Count==0:
                self._status('No wall layers with a thickness suffix were found. Use names such as NCP_Wall-250mm.',True)
            else:
                self._refresh()

    def _save(self):
        for row in self.mapping.Rows:
            self.saved[unicode(row['Layer'])]={'top':unicode(row['TopOffset']),'use':bool(row['Use'])}
        try:
            with open(os.path.join(self.folder,'wall_settings.json'),'w') as stream:
                json.dump(self.saved,stream,indent=2)
        except IOError:
            pass

    def _create(self,sender,event):
        if self._busy or self.source is None:
            return
        try:
            self.Mapping.CommitEdit()
            self._refresh()
            if not self.Create.IsEnabled:
                return
            self._save()
            self._status('Creating walls and matching types...')
            self._busy_state(True)
            ids=wall_multi.create_all(self.doc,self.source,self.batches,self.levels[unicode(self.BaseLevel.SelectedItem)],self.levels[unicode(self.TopLevel.SelectedItem)],bool(self.Unjoin.IsChecked),bool(self.CreateTypes.IsChecked))
            self._refresh()
            self._status('Created {0} walls. All changes are one Ctrl+Z undo operation.'.format(len(ids)))
        except Exception as error:
            self._status(unicode(error),True)
        finally:
            self._busy_state(False)

    def _drag(self,sender,event):
        if not self._busy:
            self.window.DragMove()

    def _close(self,sender,event):
        if not self._busy:
            self._save()
            self.window.Close()

    def show(self):
        self.window.ShowDialog()
