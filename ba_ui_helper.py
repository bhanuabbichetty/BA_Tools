# -*- coding: utf-8 -*-
"""
BA_Tools UI helper: merge shared ResourceDictionary (BAWindowStyles.xaml) into a
loaded WPF window. Use this when loading XAML in pyRevit, where pack:// URIs fail
because Assembly.GetEntryAssembly() returns null.
"""
import os
import sys

try:
    import clr
except ImportError:
    clr = None

def get_extension_root(script_dir):
    """Return the extension root directory (containing Resources/BAWindowStyles.xaml)."""
    d = os.path.abspath(script_dir)
    for _ in range(15):
        parent = os.path.dirname(d)
        if not parent or parent == d:
            return None
        if os.path.isfile(os.path.join(parent, "Resources", "BAWindowStyles.xaml")):
            return parent
        d = parent
    return None


def _find_ba_styles_path(script_dir):
    """Resolve path to Resources/BAWindowStyles.xaml by walking up from script_dir."""
    root = get_extension_root(script_dir)
    if not root:
        return None
    path = os.path.join(root, "Resources", "BAWindowStyles.xaml")
    return path if os.path.isfile(path) else None


def merge_ba_window_styles(window, script_dir):
    """
    Merge the shared BA_Tools ResourceDictionary (BAWindowStyles.xaml) into
    window.Resources so PrimaryButton, SecondaryButton, CloseButton, etc. resolve.
    Call this after XamlReader.Load(stream) and before using the window.
    """
    if clr:
        try:
            clr.AddReference("PresentationFramework")
            clr.AddReference("System.Xaml")
        except Exception:
            pass
    from System.Windows.Markup import XamlReader
    from System.IO import StreamReader

    path = _find_ba_styles_path(script_dir)
    if not path:
        return
    with StreamReader(path) as stream:
        rd = XamlReader.Load(stream.BaseStream)
        if rd and hasattr(window, 'Resources') and window.Resources:
            window.Resources.MergedDictionaries.Insert(0, rd)
