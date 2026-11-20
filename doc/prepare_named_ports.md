# Preparing named EM ports

On **Input Files**, choose the original GDS and compatible XML stackup, then
click **Prepare named EM ports…**. This preprocessing works independently of the
selected EM solver and contains no technology-specific layer numbers.

1. Load the PDK stream mapfile, or enter four-column mappings:
   `metal purpose GDS-layer datatype`. Include each metal's `pin` and `drawing`
   rows; `label`, `text` and `net` rows can provide additional label locations.
2. Select a cell if the GDS has several top-level cells, then **Find pins**.
   Pin polygons and labels in referenced cells are inspected with their transforms.
3. Review the shape, original metal and layer/datatype, proposed net name and match
   status. Only a unique name inside a pin is preselected. Nearest-label matches,
   ambiguous names and unnamed shapes need explicit selection/name review.
4. Select the desired shapes and edit names as needed. Every selected shape becomes
   a distinct port; equal net names do not combine separate polygons. Port numbers
   follow the selected rows in inventory order.
5. Choose a start layer (default 240) and a new output filename. Occupied layers in
   the full GDS hierarchy, stream map and selected XML are skipped. Existing files
   and all original inputs are protected.
6. **Create _ems.gds and use it** writes marker polygons and net-name text on unique
   layers/datatype 0, with a `.ports.json` manifest carrying names, original metal,
   pin identification, drawing-layer mapping, cell, units and source/output hashes.
   Original geometry, pins and hierarchy are preserved. The original file is unchanged.

The generated GDS becomes the selected layout and replaces the current Ports table
with the selected markers. Configure port direction, return, polarity and impedance
there; physical pin metal is offered as target only when its XML mapping is
unambiguous. Preprocessing does not infer a return or create feed geometry.

Port row headers and layout-preview annotations show the net names beside their
numbers. Keep `.ports.json` beside the GDS when transferring to another machine.
Names are matched by marker layer, not by an assumed relationship between GDS layer
numbers and port numbers. For new manifests, changed GDS content invalidates name
metadata until regenerated. GDS has no universal per-layer name field; labels and
this manifest retain the design names without requiring a KLayout layer-properties
file.
