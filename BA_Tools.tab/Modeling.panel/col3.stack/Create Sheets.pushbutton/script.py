# -*- coding: utf-8 -*-
__title__ = "Sheet Generator"
__doc__ = """Version = 2.0  -  BA Tools
_____________________________________________________________________
Description:
Create new Sheets with Sheet Number, Sheet Name and a selected Title Block.
No views are placed - sheets only.
_____________________________________________________________________
How-to:
-> Select a Title Block from the dropdown
-> Fill in Sheet Number and Sheet Name on each card
-> Click [+] to add more sheet cards
-> Click [GENERATE SHEETS] to create all sheets in the project
_____________________________________________________________________"""

# IMPORTS
from Autodesk.Revit.DB import *
from pyrevit import forms, script
import wpf, os, clr

clr.AddReference("System")
from System.Windows import Window, Thickness, CornerRadius
from System.Windows.Controls import (Orientation, DockPanel, Button, ComboBoxItem,
                                     TextBox, StackPanel, TextBlock, Border, Grid)
from System.Windows import HorizontalAlignment, VerticalAlignment
from System.Windows.Input import MouseButtonState, Cursors
from System.Windows.Media import SolidColorBrush, ColorConverter
import System

# VARIABLES
PATH_SCRIPT = os.path.dirname(__file__)

# BA Tools palette (matches SheetGeneratorUI.xaml / SheetReportUI.xaml)
CLR_ACCENT      = "#1976D2"
CLR_ACCENT_LITE = "#59BAFF"
CLR_PEACH       = "#F2B77C"
CLR_BG_CARD     = "#0E0E1A"
CLR_BG_INPUT    = "#101018"
CLR_TEXT        = "#DCDCEC"
CLR_TEXT_MUTED  = "#A0A0C0"
CLR_BORDER      = "#252535"

uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document
output = script.get_output()


def brush(hex_color):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_color))


# FUNCTIONS
def rename_sheet(sheet, sheet_name, sheet_number):
    """Rename ViewSheet, auto-appending * to avoid number conflicts."""
    forbidden = r'\:{}[]|;<>?`~'
    sheet_name   = ''.join(c for c in sheet_name   if c not in forbidden).strip()
    sheet_number = ''.join(c for c in sheet_number if c not in forbidden).strip()

    sheet.Name = sheet_name if sheet_name else "Unnamed Sheet"
    for _ in range(50):
        try:
            sheet.SheetNumber = sheet_number
            break
        except Exception:
            sheet_number += '*'


class BorderSheetCardReader:
    """Reads sheet_number and sheet_name from a card Border element."""
    def __init__(self, border_element):
        if not isinstance(border_element, Border):
            raise TypeError("Expected a Border element.")
        self.border = border_element
        self._parse()

    def _content_stack(self):
        """Card root may be a StackPanel or a Grid wrapping the StackPanel."""
        root = self.border.Child
        if isinstance(root, StackPanel):
            return root
        if isinstance(root, Grid):
            for child in root.Children:
                if isinstance(child, StackPanel):
                    return child
        raise ValueError("Could not find sheet card content.")

    def _parse(self):
        """Find the DockPanel that holds the two TextBoxes (not the label row)."""
        main_stack = self._content_stack()
        boxes = None
        for child in main_stack.Children:
            if not isinstance(child, DockPanel):
                continue
            text_boxes = [c for c in child.Children if isinstance(c, TextBox)]
            if len(text_boxes) >= 2:
                boxes = text_boxes
                break
        if boxes is None:
            raise ValueError("Could not find sheet number/name fields on this card.")
        self.sheet_number = boxes[0].Text.strip()
        self.sheet_name   = boxes[1].Text.strip()


# MAIN FORM
class SheetGeneratorUI(Window):
    def __init__(self):
        path_xaml = os.path.join(PATH_SCRIPT, 'SheetGeneratorUI.xaml')
        wpf.LoadComponent(self, path_xaml)

        self.confirmed        = False
        self.sheet_data       = []      # [(number, name), ...] collected on Generate
        self.title_block_type = None

        self._populate_title_blocks()
        self._update_status()
        self.ShowDialog()

    # setup helpers
    def _populate_title_blocks(self):
        self.UI_combo_title_blocks.Items.Clear()
        tb_types = (FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_TitleBlocks)
                    .WhereElementIsElementType()
                    .ToElements())

        items = []
        for tb in tb_types:
            label = '[{}]  {}'.format(tb.FamilyName, Element.Name.GetValue(tb))
            items.append((label, tb))
        items.sort(key=lambda x: x[0].lower())

        last_item = None
        for label, tb in items:
            tb_text            = TextBlock()
            tb_text.Text       = label
            tb_text.Foreground = brush(CLR_TEXT)
            item               = ComboBoxItem()
            item.Content       = tb_text
            item.Tag           = tb
            self.UI_combo_title_blocks.Items.Add(item)
            last_item = item

        if last_item:
            last_item.IsSelected = True

    def _update_status(self):
        try:
            n = len(self.sheet_cards)
            self.UI_txt_count.Text    = "{} sheet{}".format(n, "" if n == 1 else "s")
            self.UI_status_main.Text  = "{} sheet{} ready to create".format(n, "" if n == 1 else "s")
            item = self.UI_combo_title_blocks.SelectedItem
            if item is not None:
                self.UI_status_info.Text = "Title block: {}".format(item.Content.Text)
            else:
                self.UI_status_info.Text = "Title block: none selected"
        except Exception:
            pass

    def _create_remove_icon_button(self, outer_border):
        btn = Button()
        btn.Content = u"\u2715"
        btn.Width = 22
        btn.Height = 22
        btn.Padding = Thickness(0)
        btn.Margin = Thickness(0, 6, 6, 0)
        btn.Cursor = Cursors.Hand
        btn.Tag = outer_border
        btn.FontSize = 11
        btn.FontWeight = System.Windows.FontWeights.Bold
        btn.Foreground = brush(CLR_TEXT)
        btn.Background = brush(CLR_BG_INPUT)
        btn.BorderBrush = brush(CLR_ACCENT)
        btn.BorderThickness = Thickness(1)
        btn.HorizontalAlignment = HorizontalAlignment.Right
        btn.VerticalAlignment = VerticalAlignment.Top
        btn.Click += self._remove_card
        return btn

    def _create_sheet_card(self):
        """Card = Border > Grid > [StackPanel(labels + TextBoxes), remove button]."""
        outer = Border()
        outer.Tag = "sheet_card"
        outer.CornerRadius = CornerRadius(8)
        outer.Background = brush(CLR_BG_CARD)
        outer.BorderBrush = brush(CLR_BORDER)
        outer.BorderThickness = Thickness(1)
        outer.Margin = Thickness(0, 0, 10, 10)
        outer.MinWidth = 260

        stack = StackPanel()
        stack.Margin = Thickness(10, 8, 28, 10)

        lbl_row = DockPanel()
        lbl_row.Margin = Thickness(0, 0, 0, 3)

        num_lbl = TextBlock()
        num_lbl.Text = "Sheet Number"
        num_lbl.Width = 118
        num_lbl.Foreground = brush(CLR_ACCENT_LITE)
        num_lbl.FontSize = 10

        name_lbl = TextBlock()
        name_lbl.Text = "Sheet Name"
        name_lbl.Foreground = brush(CLR_ACCENT_LITE)
        name_lbl.FontSize = 10

        lbl_row.Children.Add(num_lbl)
        lbl_row.Children.Add(name_lbl)

        dock = DockPanel()

        num_box = TextBox()
        num_box.Text = "A-001"
        num_box.Width = 110
        num_box.Margin = Thickness(0, 0, 8, 0)
        num_box.SetValue(System.Windows.Controls.DockPanel.DockProperty,
                         System.Windows.Controls.Dock.Left)

        name_box = TextBox()
        name_box.Text = "Sheet Name"

        dock.Children.Add(num_box)
        dock.Children.Add(name_box)

        stack.Children.Add(lbl_row)
        stack.Children.Add(dock)

        root = Grid()
        root.Children.Add(stack)
        root.Children.Add(self._create_remove_icon_button(outer))

        outer.Child = root
        return outer

    # properties
    @property
    def sheet_cards(self):
        return [c for c in self.UI_sheet_grid.Children
                if isinstance(c, Border) and c.Tag == "sheet_card"]

    @property
    def selected_title_block(self):
        item = self.UI_combo_title_blocks.SelectedItem
        return item.Tag if item else None

    # event handlers
    def UIe_header_btn_close(self, sender, e):
        self.confirmed = False
        self.Close()

    def UIe_header_drag(self, sender, e):
        if e.LeftButton == MouseButtonState.Pressed:
            self.DragMove()

    def UIe_title_block_changed(self, sender, e):
        self._update_status()

    def UIe_add_sheet_card(self, sender, e):
        card = self._create_sheet_card()
        grid = self.UI_sheet_grid
        idx  = max(0, grid.Children.Count - 1)   # insert before the [+] tile
        grid.Children.Insert(idx, card)
        self._update_status()

    def _remove_card(self, sender, e):
        self.UI_sheet_grid.Children.Remove(sender.Tag)
        self._update_status()

    def UIe_btn_run(self, sender, e):
        tb = self.selected_title_block
        if tb is None:
            forms.alert("Please select a Title Block first.", exitscript=False)
            return
        if not self.sheet_cards:
            forms.alert("Please add at least one sheet card.", exitscript=False)
            return

        # collect everything now, so nothing touches WPF after the window closes
        data = []
        for card in self.sheet_cards:
            try:
                r = BorderSheetCardReader(card)
                data.append((r.sheet_number, r.sheet_name))
            except Exception:
                continue

        self.title_block_type = tb
        self.sheet_data       = data
        self.confirmed        = True
        self.Close()


# SHOW UI
try:
    UI = SheetGeneratorUI()
except Exception:
    import traceback
    output.print_md('**Error has occurred**')
    print(traceback.format_exc())
    script.exit()

if not UI.confirmed:
    script.exit()

sheet_data       = UI.sheet_data
title_block_type = UI.title_block_type


# CREATE SHEETS
report_data = []

t = Transaction(doc, "Sheet Generator - Create Sheets")
t.Start()
try:
    with forms.ProgressBar(title="Creating Sheets...") as pb:
        total = len(sheet_data)
        for n, (s_num, s_name) in enumerate(sheet_data):
            pb.update_progress(n, total)
            if not s_num:
                continue   # skip cards without a sheet number
            try:
                new_sheet = ViewSheet.Create(doc, title_block_type.Id)
                rename_sheet(new_sheet, s_name, s_num)
                report_data.append(new_sheet)
            except Exception as ex:
                output.print_md("Skipped card {}: `{}`".format(n + 1, ex))
    t.Commit()
except Exception as outer:
    t.RollBack()
    forms.alert("Sheet creation failed - all changes rolled back.\n\n{}".format(outer),
                title="Sheet Generator")
    script.exit()


# REPORT WINDOW
class SheetReportUI(Window):
    """Report window - click any row to open that sheet."""
    def __init__(self, sheets):
        path_xaml = os.path.join(PATH_SCRIPT, 'SheetReportUI.xaml')
        wpf.LoadComponent(self, path_xaml)
        self._populate(sheets)
        self.ShowDialog()

    def _populate(self, sheets):
        stack = self.UI_main_stack
        stack.Children.Clear()

        for sheet in sheets:
            b              = Border()
            b.Padding      = Thickness(14, 8, 14, 8)
            b.Margin       = Thickness(2, 3, 2, 0)
            b.CornerRadius = CornerRadius(6)
            b.Background   = brush(CLR_BG_CARD)
            b.BorderBrush  = brush(CLR_BORDER)
            b.BorderThickness = Thickness(1)
            b.Cursor       = Cursors.Hand
            b.Tag          = sheet
            b.MouseDown   += self._open_sheet

            row = StackPanel()
            row.Orientation = Orientation.Horizontal

            num_tb            = TextBlock()
            num_tb.Text       = sheet.SheetNumber + "   "
            num_tb.Foreground = brush(CLR_ACCENT_LITE)
            num_tb.FontWeight = System.Windows.FontWeights.Bold
            num_tb.FontSize   = 12

            name_tb            = TextBlock()
            name_tb.Text       = sheet.Name
            name_tb.Foreground = brush(CLR_TEXT)
            name_tb.FontSize   = 12

            row.Children.Add(num_tb)
            row.Children.Add(name_tb)
            b.Child = row
            stack.Children.Add(b)

        n = len(sheets)
        self.UI_status_count.Text = "{} sheet{} created".format(n, "" if n == 1 else "s")

    def _open_sheet(self, sender, e):
        try:
            __revit__.ActiveUIDocument.ActiveView = sender.Tag
        except Exception:
            pass

    def UIe_header_drag(self, sender, e):
        if e.LeftButton == MouseButtonState.Pressed:
            self.DragMove()

    def button_close(self, sender, e):
        self.Close()


if report_data:
    output.print_md("### {} Sheet(s) Created Successfully".format(len(report_data)))
    SheetReportUI(report_data)
else:
    output.print_md("### No sheets were created.")
