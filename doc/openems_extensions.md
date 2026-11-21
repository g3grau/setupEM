# Optional openEMS geometry workflows

These options apply only to openEMS. Existing Palace/Elmer exports are unchanged.
Save a new model/configuration name for each physical comparison. Native simcfg
files retain the settings; the GDS and technology XML are not rewritten.

## GPU-capable build

The gds2openEMS `install_ems_conda_hooks.py` installer can select a GPU-capable
openEMS prefix and source checkouts for normal conda commands. Both CPU and GPU
use the same selected native build; select the execution engine on Settings.
Changing conda activation does not update an already running GUI: restart it.

## Calibrated box-wall feeds (Ports tab)

Expand/check **openEMS: calibrated box-wall feeds**. Choose an outward wall side,
signal metal, return kind/layer, feed length, launch gap, and width. Width zero
uses each rectangular terminal marker's transverse width. GDS geometry does not
specify intended access direction, so choose it explicitly. All terminal outward
edges must align and generated feeds must remain separated. Other geometries
require manually prepared feeds, not guessed routing.

Existing terminal via-port definitions may remain in the Ports table: this
workflow uses their marker polygons and turns them into wall launches. All ports
must be excited and use 50 ohms. The output is a new physical fixture with added
feeds, return geometry, and a PEC wall. These are visible in the 3D preview.

- **Individual metal returns**: copy each generated signal feed's footprint to
  the selected return layer, extending the return continuously across the signal
  excitation gap to the PEC wall. In the generated fixture, trim any connected
  return patch protruding outward beyond the terminal plane before adding the
  strips. Device-side metal and disconnected islands are retained; the source
  GDS is unchanged.
- **Conductive backside**: uses an existing conductive background stackup layer
  (e.g. backside metal), not the lossy substrate itself. Existing drawn geometry
  is retained. Remove an artificial M1 patch from a separate source layout if it
  would interrupt the uniform feed before the requested reference plane.

Prepare geometry first. Preparation also writes L/2L coupled standards for each
wall. Run calculates standards before the device and writes a separate calibrated
Touchstone plus diagnostics. Known geometry warnings stop before expensive solves;
calibration diagnostics can also stop calibrated-file generation. See gds2openEMS
`doc/calibrated_boxwall_ports.md` for validity assumptions.

The **Reference plane setback toward wall** defaults to zero (the terminal plane).
No setback is needed to compensate for a connected M1 patch protruding into the
generated metal-return fixture: the generator now trims that protrusion to the
terminal plane and creates uniform strips. A positive setback is an explicit
choice to retain part of the generated feed in the measured device, not a repair
for an invalid calibration. Reset any prior 14 um workaround to zero when using
the corrected generator.

**Preview saved openEMS solver geometry** is the bottom button in the Actions
group. It opens an existing solver XML without regenerating the geometry.

A deep return can require long standards and reduce valid calibration bandwidth.
Preparation checks both the effective-index wavelength criterion and the
maximum-permittivity half-wave criterion for the 2L standard. The latter is the
same deterministic phase bound used after solving. Standard lengths are capped
to satisfy both where possible; if the minimum settling length (2 D) cannot fit,
preparation reports the lower limit before a simulation starts. This does not
replace post-solve checks of reciprocity, phase branches and launch parameters.

Use **Check calibration limits / geometry (no simulation)** in the Ports tab to
read the current GDS/stackup and show the actual planned L/2L lengths, both
wavelength/phase limits, the small-port limit and uniform-feed requirement.
The report explains which setting to change: feed length for straight-section
failures; a reviewed reference-plane setback or removal of an artificial patch
for feed transitions; a lower stop frequency or closer return for bandwidth
failures. Dielectric oversize does not move the PEC port wall.

Preview, Prepare and Start repeat the check automatically. The report is visible
in Ports and directly below the Actions buttons in Create Model. Start is blocked
on failed checks before writing/running the model; Preview/Prepare may inspect
geometry with band warnings, but cannot proceed through a geometry failure.
Changing the feed, band, layout selection or ports marks the report stale.

For the roughly 200 um backside-return trial, previously generated standards
L=944.345 um have a maximum-permittivity phase limit of about 23.01 GHz, despite
the older effective-index-only planning estimate accepting 25 GHz. A 22 GHz
subset of completed networks can be calibrated without repeating those solves;
changing standards instead requires new standard data. This fixture is not
equivalent to the nearby M1-return fixture. Feed/ground/
wall interaction with the device cannot be calibrated away. No correction makes
an arbitrary characterization geometry physically identical to another one.

## RDL air-valley approximation (Mesh and Boundaries tab)

Expand/check the RDL air-valley option and select the actual RDL source metal.
Set the valley coating height above that metal's bottom, and a lateral coating
width. The cut removes dielectric outside the grown RDL footprint, between the
valley height and the existing planar dielectric top. Original dielectric below
that height and material over the RDL are retained. This is an assumed stepped
profile; it does not reconstruct multiple conformal films or etch angles.

When there are no RDL polygons, the stack remains planar. In particular, do not
infer valleys beside embedded copper just because a thick copper layer exists.
The generated air material is exactly epsilon=1, conductivity=0. It is added
AFTER real-via merging, so via merging need not be disabled for this recipe.
The 3D preview shows the result; the stackup editor's one-dimensional display
cannot show local topography. Check minimum dz and inspect geometry before a run.

For now, box-wall calibration and patterned air cuts are separate experiments:
the calibration standards do not yet reproduce patterned dielectric cross-sections.
The exporter rejects enabling both rather than calibrating mismatched media.
