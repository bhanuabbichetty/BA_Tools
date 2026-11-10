Walls from CAD - multiple layers

Automation > Modelling > Walls from CAD

Name each CAD outline layer with one thickness in millimetres, for example NCP_Wall-290mm, NCP_Wall-250mm, NCP_Wall-180mm, NCP_Wall-150mm or NCP_Wall-120mm. Other thicknesses from 20 to 2000 mm are accepted. Click READ CAD to discover matching layers.

The layer table automatically matches existing basic wall types by actual width, preferring NCP Wall - [width]mm. If no matching type exists and Create missing wall types is checked, the tool previews a new type and creates it only when creating walls. New types copy an existing single-layer basic wall material and construction and adjust its thickness. Existing types are never resized.

Choose common base and top levels. Base offset is fixed at +16 mm. Edit the Top offset cell for each layer; initial value is 0 mm. Negative values lower the top. Uncheck Use to exclude a layer. Top offsets and inclusion settings are remembered per layer when you create walls or close the tool with Close.

CAD must contain paired, straight orthogonal wall faces at the layer thickness. Rotated planar links are supported. Curved and diagonal source outlines are not supported. Keyway gap defaults to 80 mm; set 0 to preserve all gaps. Only gaps of the specified size within 1 mm are filled. Runs shorter than the wall width are omitted. The tool uses installed AutoCAD Core Console on a temporary saved-DWG copy. It does not reload or save the CAD link. Coordinate mapping is verified against cached link geometry.

Matching existing walls are skipped; conflicting types, constraints or overlaps block the batch. Existing walls are not changed. Disallow joins at both ends applies to new walls. All selected layers and new types are committed together as one Ctrl+Z undo operation, or rolled back together on error. The project is never saved or synchronized.

Installed folder: %APPDATA%\pyRevit\Extensions\Automation.extension\Automation.tab\Modelling.panel\Walls from CAD.pushbutton. Remove only that folder and reload pyRevit to uninstall.

ERECTION_MARK exterior face update

All wall thicknesses, including 120 / 150 / 180 mm, require ERECTION_MARK face markers. The saved DWG must contain connected LINE or straight LWPOLYLINE symbols on ERECTION_MARK (nested CAD layer prefixes are accepted). A triangle tip or line endpoint must touch the intended wall side face, with the rest of that marker outside the outline. A straight line from the wall centerline through the intended side is also accepted. Line drawing order does not matter.

Each derived run needs a clear marker on one side. Multiple markers on the same side are allowed. Missing or opposite-side markers block that layer and report the run coordinates. If separate panels on one merged run need different face directions, split their outlines into separate runs.

Marked walls use Finish Face: Exterior and the actual exterior face is checked against the marked CAD face. The physical wall remains within its CAD outline. Existing walls with the wrong exterior or location-line setting are reported as conflicts and are not automatically moved or flipped. Preview includes the face rule. Base +16 mm, per-layer top offsets and end-join options remain available.
