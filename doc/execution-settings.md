# Execution settings

The **Settings** tab contains runtime parallelism. It follows the target solver
chosen in Input Files. Mesh and Boundaries retains geometry and discretization
controls; process and thread counts no longer live there.

## openEMS

- **Solver threads → Automatic (solver default)** stores `numThreads: null` in the
  project and omits the setting in exported Python. gds2openEMS then uses its
  default of zero, which delegates thread selection/tuning to openEMS. No `-1`
  sentinel is passed to the solver. Old projects with `numThreads: 0` also select
  Automatic.
- A positive value requests that fixed thread count.
- **Execution engine** selects the default CPU engine or GPU. GPU requires a
  suitable openEMS build; it is not enabled by changing the UI alone.

These controls are independent of the FEM parallel settings. The energy-decay
criterion and frequency-sample count remain with the FDTD controls.

## Palace

Separate controls select **MPI processes**, **OpenMP threads per process**, and
**OpenBLAS threads per process**. Zero is displayed as **Launcher default (unset)**
or **Library default (unset)**; no override is written for it. An explicit count
is stored in the .simcfg and written into a marked block in the generated run_sim:

```bash
# BEGIN setupEM parallel settings
export PALACE_NP=32
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
# END setupEM parallel settings
```

The example requests 32 MPI processes with one OpenMP thread per process. Counts
are not inferred from a particular machine or technology. Use an allocation that
fits the machine/job. OpenMP requires an OpenMP-enabled Palace build, and the
OpenBLAS setting has no parallelizing effect on a serial BLAS build.

The `run_palace` launcher must honor PALACE_NP (for example,
`palace -np "${PALACE_NP:-8}" "$@"`). The native launcher supplied with our
current gds2openEMS checkout already does. A third-party wrapper with a hardcoded
MPI count must be adapted to honor this standard variable; setupEM cannot override
an arbitrary wrapper's internal command. No paths to Spack, conda, or a machine
are embedded by these controls.

Start Simulation updates only the marked block in run_sim before launching it.
Existing calibration and custom commands remain in place. Clearing a setting
removes its old assignment. Exported Python creates the same block when generating
its run script, without requiring setupEM at runtime. Native configs and Python
imports retain the settings.

## Elmer

The existing MPI process selection is moved from Mesh and Boundaries to Settings.
Its model setting remains ELMER_MPI_THREADS for compatibility with existing
projects and gds2palace. The choices and solver launching behavior are unchanged.
