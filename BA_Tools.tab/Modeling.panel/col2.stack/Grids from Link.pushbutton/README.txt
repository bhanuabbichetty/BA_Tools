Grids from Link

Location: Automation > Modelling > Grids from Link.

Open a plan and click the button. The BA Tools-style setup window contains source selection, CAD axis layers, minimum segment length, naming, preview and results. A selected linked CAD or Revit file is preselected. Click READ GRIDS, review the preview and then CREATE GRIDS. Naming changes refresh the preview; source or CAD-setting changes require another read. Preserve source labels retains leading zeros, letters and suffixes. Results and errors appear inside the same window.

CAD: requires installed AutoCAD Core Console and a locally accessible DWG. Reads a temporary copy without saving the source. Supports planar LINE/LWPOLYLINE grid axes with circular TEXT/MTEXT/attribute-labelled bubbles, including nested blocks. Grid axis layers containing grid/axis/axes are detected when unique; otherwise select the axis layers. Segments shorter than 1000 mm are excluded as leaders. Exploded text outlines, elliptical bubbles, curved CAD axes, nested external references, and non-planar CAD are not supported. The tool stops if coordinate or label matching fails. Verify names and positions after the first run on a new drawing standard.

Revit: copies straight, circular and connected multi-segment grids from a loaded link using its instance transform. Host grid graphics use the current project grid type. Workset and copy/monitor relationships are not copied.

Existing axes are skipped when their names and positions match. Name/location conflicts stop the operation before any grids are created. Each placement is a single undo operation. The command does not save or synchronize the project.

Uninstall: remove only the Grids from Link.pushbutton folder and reload pyRevit.
