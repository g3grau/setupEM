# Portable path defaults

Keep machine-specific browse locations and tool installations in a small JSON
snippet, independently of simulation settings. A ready-to-edit Rocky server
example is [examples/paths-ems-server.json](examples/paths-ems-server.json).

```json
{
  "schema": "setupEM.paths.v1",
  "directories": {
    "gds": "/eda/designs",
    "stackup": "/eda/openSource/gds2openEMS/XML_stackup",
    "touchstone": "/eda/designs",
    "project": "/eda/designs",
    "stream_map": "/eda/designs",
    "output": "/eda/designs"
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
Rocky example uses absolute paths and needs no extra variables. Restart setupEM
after importing to initialize tool fields from the new defaults; browse dialogs
read updated defaults directly.

## Priority and scope

- An explicit current file/directory stays the starting location of its dialog.
  Otherwise, a configured directory is used if it exists, followed by the normal
  application fallback.
- File → Load Config / Import / Edit uses `project` when no project/layout is
  already selected. GDS/raw GDS uses `gds`; XML uses `stackup`; SP/result files
  use `touchstone`; map selectors use `stream_map`; run/comparison output-parent
  dialogs use `output`.
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

The snippet does not modify project GDS/stackup paths, simulation parameters,
solver binaries, PATH, or conda packages. Invalid active JSON produces a warning
and normal defaults remain available. Importing invalid JSON leaves the previous
snippet intact. A server copy can therefore use the same project files with its
own browse locations and default tool paths.
