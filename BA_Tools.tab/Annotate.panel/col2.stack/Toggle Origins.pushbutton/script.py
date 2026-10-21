# -*- coding: utf-8 -*-
__title__ = "Toggle\nOrigins"
__author__ = "Bhanu Prakash A"
__doc__ = """Show or hide the Survey Point, Project Base Point and Internal
Origin in the active view. One click reveals all three; the next hides them."""

from Autodesk.Revit.DB import Category, BuiltInCategory, Transaction
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = uidoc.ActiveView
output = script.get_output()

# label, BuiltInCategory — Internal Origin lives under OST_CoordinateSystem
TARGETS = [
    ("Survey Point",       BuiltInCategory.OST_SharedBasePoint),
    ("Project Base Point", BuiltInCategory.OST_ProjectBasePoint),
    ("Internal Origin",    BuiltInCategory.OST_CoordinateSystem),
]


def notify(message):
    try:
        forms.toast(message, title="Toggle Origins")
    except Exception:
        output.print_md(message)


def get_toggleable_categories():
    cats = []
    for label, bic in TARGETS:
        try:
            cat = Category.GetCategory(doc, bic)
        except Exception:
            cat = None
        if cat is None:
            continue
        try:
            if view.CanCategoryBeHidden(cat.Id):
                cats.append((label, cat))
        except Exception:
            pass
    return cats


def main():
    if view is None:
        forms.alert("No active view.", exitscript=True)

    cats = get_toggleable_categories()
    if not cats:
        forms.alert(
            "The Survey Point / Project Base Point / Internal Origin "
            "categories can't be toggled in the active view.",
            exitscript=True)

    # If any of the three is currently visible, hide them all; otherwise show.
    any_visible = False
    for _, cat in cats:
        try:
            if not view.GetCategoryHidden(cat.Id):
                any_visible = True
                break
        except Exception:
            pass
    hide = any_visible

    t = Transaction(doc, "Toggle Survey / Base Points")
    t.Start()
    changed = []
    try:
        for label, cat in cats:
            try:
                view.SetCategoryHidden(cat.Id, hide)
                changed.append(label)
            except Exception:
                pass
        t.Commit()
    except Exception:
        t.RollBack()
        forms.alert("Failed to change visibility.", exitscript=True)

    state = "hidden" if hide else "shown"
    notify("{} {} in '{}'.".format(", ".join(changed), state, view.Name))


main()
