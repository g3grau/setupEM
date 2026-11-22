# Portable path defaults

Keep machine-specific browse locations and tool installations in a small JSON
snippet, independently of simulation settings. A ready-to-edit Rocky server
example is [examples/paths-ems-server.json](examples/paths-ems-server.json).

```json
{
  "schema": "setupEM.paths.v1",
  "directories": {
    "gds": "./generated_gds",
    "stackup": "/eda/openSource/gds2openEMS/XML_stackup",
    "touchstone": "./SP",
    "project": "/eda/designs",
    "stream_map": "/eda/designs",
    "output": "./plots",
    "models": "./models",
    "fdtd": "./fdtd",
    "fem": "./fem"
  },
  "tools": {
    "lumpedmodel": "/eda/openSource/lumpedmodel",
    "broadband_python": "/eda/openSource/setupEM/.tools/snp2le-env/bin/python"
  }
}
```

Every section and key is optional. Unknown keys and non-string path values are
rejected. This is a data-only file, not an executable Python config.

## Install or select a snippet

Use **File → Preferences → Files → Import path snippet…**, or run in the setupEM
environment:

```bash
python -m setupEM.path_config --install /path/to/paths-ems-server.json
```

The destination is `$XDG_CONFIG_HOME/setupEM/paths.json`, normally
`~/.config/setupEM/paths.json`. Existing defaults are backed up before replacement.
The import validates the entire file before writing. Run the module without
arguments to print the active config path.

Alternatively point to a centrally maintained snippet without copying it:

```bash
export SETUPEM_PATH_CONFIG=/eda/config/setupem-paths.json
setupEM
```

When this variable is set, imports replace that selected file, so use the normal
user destination if the central file should remain read-only.

Paths support `~` and environment variables such as `${HOME}` or `${EMS_ROOT}`.
Variables expand when a path is used, not when imported. If using a custom
variable, define it persistently in your shell or conda environment. The supplied
Rocky example mixes absolute installation/project-browser paths with relative
project output directories and needs no extra environment variables. Restart setupEM
after importing to initialize tool fields from the new defaults; browse dialogs
read updated defaults directly.

## Project-relative directories

Absolute presets keep their absolute meaning. Other directory presets, including
`./generated_gds`, `./SP` and `./models`, resolve against the current project:

1. The loaded/saved simcfg directory. Generated solver snapshots carry a relative
   `project_root` link so opening a snapshot also finds the original project.
2. Before a config is opened, the original Raw GDS directory, then the active GDS
   directory or imported model-script directory.
3. Before any input is selected, the absolute `project` preset is the initial root.

Each window resolves its own project. Neither the shell's current directory nor
the path snippet's location becomes the project once a project is selected.
A relative `project` preset itself, or a relative tool installation path, resolves
against the snippet directory. Environment variables expand before deciding
whether a path is relative or absolute.

The example gives this layout for newly generated artifacts:

```text
project/
  original.gds
  coil.simcfg
  generated_gds/     cleaned and port-prepared layouts plus manifests/logs
  fdtd/             generated openEMS scripts, snapshots and solver data
  fem/              generated Palace/Elmer scripts, meshes and solver data
  SP/               copies of completed device Touchstone results; DC derivatives
  models/           lumped and broadband fitting run folders
  plots/            comparison plots and extracted-parameter exports
```

`models` means fitted circuit models. Generated simulator Python scripts go into
`fdtd` or `fem`. Solver-specific subdirectories inside them retain their normal
structure. A simcfg snapshot remains beside each generated script for provenance;
a linked project simcfg stays beside the original layout. Existing explicitly
chosen destinations and imported scripts are not relocated. With no `fdtd`/`fem`
preset, the original solver destination behavior remains available.

Directories are created when an output action needs them. Browsing alone does not
create folders; if a relative browse directory is missing, the dialog starts at
its nearest existing parent. XML and stream-map presets may also name a specific
file instead of a directory.

After a successful simulation, device `.sNp` results are copied to `touchstone`.
Calibration standards and AMR iteration snapshots are excluded. Solver originals
remain available for the normal result viewer and postprocessing. An identical
copy is reused; a differing prior network is retained and the new copy receives
a content-hash suffix. Existing result archives are not reorganized automatically.

## Priority and scope

- An explicit current file/directory stays the starting location of its dialog.
  Otherwise, a configured directory (or XML/map file) is used if it exists,
  followed by the normal application fallback.
- File → Load Config / Import / Edit uses `project` when no project/layout is
  already selected. Raw GDS browsing starts in `project`; prepared GDS uses
  `gds`; XML uses `stackup`; SP/result files use `touchstone`; map selectors
  use `stream_map`. Fitting output-parent dialogs use `models` (falling back to
  `output`); comparison/parameter exports use `output`.
- The existing **XML file browser starts from** preference takes precedence over
  the snippet's stackup directory when explicitly set.
- `tools.lumpedmodel` supplies the default repository field. An explicit saved
  project override still wins. A matching default tool path is no longer written
  into a simcfg simply because another lumped-model option changed, keeping new
  projects portable between machines.
- `tools.broadband_python` supplies the engine Python default. An explicit project
  override wins, while `EMS_BROADBAND_PYTHON` takes precedence over this default.
  Without either default the local isolated backend/current Python is discovered
  as before.

The snippet does not rewrite existing project input selections or simulation parameters,
solver binaries, PATH, or conda packages. Invalid active JSON produces a warning
and normal defaults remain available. Importing invalid JSON leaves the previous
snippet intact. A server copy can therefore use the same project files with its
own browse locations and default tool paths.
