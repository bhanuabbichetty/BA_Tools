# BA_Tools for pyRevit

BA_Tools is a pyRevit extension by Bhanu Prakash A for automating Revit modeling, annotation, assembly documentation, project setup, and sheet workflows.

[![pyRevit](https://img.shields.io/badge/pyRevit-extension-1976D2)](https://github.com/pyrevitlabs/pyRevit)
[![Revit](https://img.shields.io/badge/Autodesk-Revit-0696D7)](https://www.autodesk.com/products/revit/overview)

## Tools

The ribbon is organized under `BA_Tools.tab`:

- **Modeling:** create walls and slabs from lines, place hollow-core slabs and detailing families, and create wall openings from linked electrical and HVAC models.
- **Annotation:** dimension elevations, grids, and levels; renumber elements; and toggle datum bubbles.
- **Assemblies and views:** create assemblies and assembly views, align origins, and transfer view templates and filters.
- **Project setup and data:** acquire linked-model coordinates, create worksets, update parameters, title blocks, and revisions.
- **Views and export:** create workset 3D views, rename view titles, and export sheets or 3D views.

Each pushbutton has a `bundle.yaml` manifest with its ribbon label and usage tooltip. Check the tooltip for the button's selection, view, and version requirements.

## Requirements

- Autodesk Revit and a compatible pyRevit installation.
- Revit version support varies by tool; check the button manifest.
- Some tools use WPF dialogs and the Python engine configured in pyRevit.

## Install

1. Clone or download this repository.
2. Place the extension folder in pyRevit's extension search path. For the default user extension folder, use `%APPDATA%\pyRevit\Extensions\BA_Tools.extension` (rename the downloaded folder to `BA_Tools.extension`).
3. In Revit, reload pyRevit and open the **BA_Tools** tab.

## Shared interface resources

The extension includes a shared dark WPF theme in [`Resources/BAWindowStyles.xaml`](Resources/BAWindowStyles.xaml). See [`Resources/README.md`](Resources/README.md) for usage guidance when building dialogs for new tools.

## Development

Keep each tool in its `.pushbutton` bundle, provide a clear `bundle.yaml` tooltip, and test model-changing tools on a saved test model first. Bug reports are most useful when they include the button name, Revit and pyRevit versions, steps to reproduce, and the error message.

## License

This repository does not currently specify a license. Contact the author before reusing or redistributing its code.

## Author

**Bhanu Prakash A** · [GitHub profile](https://github.com/bhanuabbichetty)
