# Raw Cadence GDS preparation

The **Input Files** tab contains a Raw Input section for the workflow:

    Cadence GDS → cleaned GDS → reviewed EM pins → _ems.gds → simulation inputs

This uses `gds_prepare_for_EM` 1.8 or newer through its stackup-driven Python API.
The standalone IHP-specific layer tables are not used. On a machine with a local
checkout, install it into the Python environment running setupEM:

```bash
python -m pip install /path/to/gds_prepare_for_EM
```

## Workflow

1. Select an **XML stackup** directly below **Target solver**, above preprocessing.
   Its variables/overrides are honored during preprocessing.
2. Choose the **Raw GDS**, optionally a **Cadence stream map**, and a new
   **Cleaned GDS** path. The suggested filename is `<raw>_cleaned.gds`.
3. Open **Simplification options** to set the cell, fill-size/repeat limits,
   cutout limit, excluded layers and any filler datatypes to remove.
4. Click **1. Simplify raw GDS**. A background process streams its log. This
   writes the cleaned GDS, `.prep.json` provenance and `.prep.log`; the existing
   simulation input stays unchanged. If outputs already exist, choose **Replace
   generated files**, **Choose another filename**, or **Cancel**.
5. Click **2. Create EM-port GDS…**. The existing named-port dialog
   receives the verified cleaned GDS, resolved cell and stream map. Load or edit
   pin/drawing/label mappings if needed, **Find pins**, review/select shapes and
   their names, then **Create _ems.gds and use it**. The suggested output is
   `<raw>_ems.gds` in the cleaned GDS directory.
6. The prepared layout is selected in the **Active simulation input — GDS used by the solver** group and the
   port table is populated. The input datatype filter is set to the physical
   drawing datatypes identified during preprocessing plus marker datatype 0.
   Configure port directions, return conductors and impedances on **Ports**.

The Input Files page scrolls when expanded options or stackup variables need
more space. Existing already-prepared GDS files can still be selected directly;
the **Tools → Prepare named EM ports from active GDS…** and **Tools → Simplify GDS** workflows
remain available.

Each GDS row has **Browse** and **Show** controls. After simplification, use
**Show** next to Cleaned GDS to inspect it immediately. The EM-port GDS row
below it names the final output and previews its named ports. These previews
show the saved files without changing the active input or applying model-time
via merging. **Use for simulation** selects an existing final file and restores
ports from its matching `.ports.json` manifest when available.

The Raw GDS field displays **Please choose a file ===>** until an original input
is selected. Preview legends and polygon tooltips show physical stackup names;
other layers use the selected stream map's names, already before port finding.
Port-prepared files can also recover their layer names from the matching manifest.
Layers with no name in either source retain their numeric GDS identifier.

Port preparation creates a file; the active simulation input group identifies
which file the solver uses. It does not repeat preparation.

## Layer and geometry handling

- Physical metal/via layer numbers and via adjacency come from the XML stackup.
- With a stream map, only its `drawing` layer/datatype pairs on physical stackup
  layers are candidates for geometry operations. Without a map, the explicit
  drawing datatype filter is used, default 0. No filler-purpose numbers are
  assumed; enter technology-specific datatypes in **Remove polygon datatypes**.
- Drawing layer/datatype pairs are isolated during simplification, so a pin
  purpose on the same physical layer cannot accidentally be merged with drawing
  or deleted as floating fill. Mapped pin shapes and all text labels are retained.
  Removing a datatype containing mapped pins is rejected. Ambiguous drawing/pin
  assignments to the same pair must be resolved or that layer excluded.
- Existing drawing overlap under mapped pins is checked after cleanup. If a
  repeated terminal was classified as floating fill, publication stops with
  guidance to disable fill removal, adjust limits or exclude that layer.
- Floating-fill removal defaults to minimum size 1 µm, maximum 20 µm, at least
  20 repeats. It already merges touching drawing shapes. Density cutouts default
  to a maximum area of 1 µm². Repeated ground-plane openings are optional.
- Via merging defaults to **off**. Preprocessing vias into solid shapes loses
  the original via fill factor. For accurate resistance, prefer model-time via
  merging with fill-factor correction on original via arrays.
- Operations run in µm internally, then restore the source GDS unit and precision.
  A named cell must exist. Blank cell selects the largest design top-level cell,
  ignoring KLayout context metadata. The derivative contains that cell flattened,
  with paths represented as polygons and labels transformed to the selected cell's
  coordinates; unrelated top-level cells are omitted. The raw file is unchanged.

## Traceability and saved settings

`.prep.json` records input/stackup/map paths and SHA-256 hashes, actual options,
resolved cell, units, selected drawing pairs, protected pin pairs, output hash
and simplification tool identity. Before port preparation, setupEM verifies that
the inputs, settings and cleaned output still match that report. Changed inputs
require preprocessing again. Existing outputs require confirmation by default.
Under **Preferences → Files**, enable **Replace generated GDS files and their
sidecars without asking** to allow automatic replacement. This also applies to
EM-port preparation and **Tools → Simplify GDS**. Original input files remain
protected. Generation uses staged files so a failed generation retains the
previous outputs; ordinary publication failures restore replaced files.

The `_ems.ports.json` manifest includes the full raw-preparation report, linking
the prepared EM markers back through the cleaned layout to the original Cadence
export. Raw settings are saved separately as `raw_input` in native simcfg files,
including linked-script sidecars. They do not become solver settings or alter
generated solver scripts except for selecting the final `_ems.gds` and datatypes.
An unused Raw Input section adds no configuration keys to existing models.
