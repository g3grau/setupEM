# openEMS FDTD target

setupEM can export and run openEMS models from the shared layout, stackup and port
controls. This backend contains no process-specific layer names, conductivities,
stackup filenames or installation paths. Supply a GDS and an openEMS-compatible
XML stackup. Changing the target solver does not translate a FEM stackup.

## Installation

Install openEMS and its CSXCAD Python bindings for the Python environment running
setupEM, then install the optional backend package:

```bash
python -m pip install '.[openems]'
python -c 'import openEMS, CSXCAD, gds2openEMS'
```

openEMS/CSXCAD installation depends on the platform; the Python package alone may
not supply the native solver. The Palace/Elmer dependencies of setupEM remain
unchanged. Exporting a script does not import the openEMS bindings; previewing,
preparing or running it does.

## Configure and run

1. In **Input Files**, choose **Target solver → openEMS FDTD** (or start with
   `setupEM --openems`). Choose the layout and compatible stackup. The existing
   layout preview and port table remain available. Stackup reading for the GUI
   uses the selected solver's reader.
2. Define consecutively numbered ports starting at 1. Each uses a separate marker
   layer. Vertical ports specify their two metal names; in-plane ports specify
   one target metal. The exporter normalizes direction names to openEMS syntax.
   Full S-matrix generation requires nonzero excitation voltage on every port.
3. In **Frequencies**, enter the broadband excitation's start and stop frequency.
   Output sample count belongs to the FDTD settings; it does not require an
   additional time-domain solve per frequency.
4. In **Mesh and Boundaries**, set conductor-region resolution, cells per
   wavelength, residual energy and output sample count. In **Settings**, select
   automatic or fixed solver threads and optional GPU execution. GPU execution
   requires a suitable openEMS build.
   Choose all six boundaries explicitly: PEC, PMC, MUR or PML_8. FDTD defaults to
   PEC; this is reflective, not an absorbing substitute for Palace ABC.
5. **Preview** builds the mesh and opens AppCSXCAD for the first excitation, without
   solving. **Prepare** writes geometry/mesh XML for all excitations without a
   viewer or solver. **Start Simulation** generates the current model and launches
   it with setupEM's Python, runs each port excitation, then writes Touchstone.
   The existing S-parameter viewer discovers these files.

The exported script works independently:

```bash
python model.py --preview-only
python model.py --prepare-only
python -u model.py
```

Results are written by gds2openEMS to `output/<model>_data/` beside the script,
with one `sub-<n>` directory per excitation and `<model>.sNp` after evaluation.
Solver errors propagate as a nonzero exit status; no external combine_snp step is
used. gds2openEMS's own model-hash checks control result reuse.

## Shared controls and limitations

Via merging and fill-factor conductivity correction are exported to gds2openEMS;
merging is performed by its reader, and material correction by its setup code.
The exporter does not rewrite or pre-merge the source GDS. Keep original via arrays
in the input if conductivity correction is needed.

FEM and FDTD boundary choices are stored separately. FEM settings survive switching
targets but are not emitted into openEMS scripts. Palace surface-impedance/skin
presets, polynomial order, AMR, port-wall calibration, per-layer FEM mesh overrides,
FEM maximum cell size and FEM field dumps are not exported. Their controls are
hidden or disabled in FDTD mode. Spatial field-dump configuration and the FEM model
fit button are not part of this initial backend. The common margin and air padding
are reused; differing margins on individual sides are rejected at export because
the FDTD exporter currently accepts one uniform dielectric margin.

Native .simcfg files preserve the target solver. Old configurations without a
solver key retain their Palace/Elmer behavior. openEMS scripts can be imported as
new models, keeping the original script protected; FDTD workflow scripts are not
edited in place by the existing FEM preserve-mode patcher.

## Palace conformality

**Conformal mesh / refinement** is visible in the main mesh settings for Palace,
independently of the AMR iteration count. Yes exports
`settings['adaptive_mesh_conformal'] = True`, resulting in
`Model.Refinement.Nonconformal = false`. This changes Palace/MFEM mesh handling,
not Gmsh's initial mesh. It cannot repair collapsed elements in a .msh file.

See [Execution settings](execution-settings.md) for automatic thread selection and MPI/OpenMP controls.
