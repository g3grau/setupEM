# Execution settings

The **Settings** tab contains runtime parallelism. It follows the target solver
chosen in Input Files. Mesh and Boundaries retains geometry and discretization
controls; process and thread counts no longer live there.

## openEMS

- **Device threads per excitation → Automatic (solver default)** stores `numThreads: null` in the
  project and omits the setting in exported Python. gds2openEMS then uses its
  default of zero, which delegates thread selection/tuning to openEMS. No `-1`
  sentinel is passed to the solver. Automatic is available with the shared
  budget disabled; budgeted jobs need explicit positive thread counts.
- A positive value requests that fixed thread count.
- **Execution engine** selects the default CPU engine or GPU. GPU requires a
  suitable openEMS build; it is not enabled by changing the UI alone.

These controls are independent of the FEM parallel settings. The energy-decay
criterion and frequency-sample count remain with the FDTD controls.

### Concurrent FDTD scheduling

The defaults are **16 device threads**, **4 calibration threads**, a **32-thread
total budget**, and at most **8 concurrent jobs**. Existing positive device
thread settings are retained. Both the thread budget and job limit apply: these
defaults allow eight calibration excitations or two device excitations at once.
Calibration standards finish before the device phase starts. Independent port
excitations within each phase run in separate processes and output directories.

These controls apply to ordinary via/in-plane port runs as well as calibrated
boxwall runs. Ordinary models schedule their device excitations directly; boxwall
models first complete calibration standards. Set the total budget to **0** for
sequential execution with the ordinary solver thread setting. Concurrent GPU jobs
are not supported; select CPU or set maximum jobs to 1.

The GUI writes `openems_execution` into the project and generated openEMS script.
Update **both setupEM and gds2openEMS** on the server and regenerate older
ordinary model scripts to enable scheduling. Job-labelled progress is
streamed to the GUI; each excitation retains `sub-*/fdtd_solver.log` for ordinary runs or
`sub-*/boxwall_solver.log` for calibrated runs. A failed
job stops remaining work and terminates active workers. GUI Stop also terminates
workers. Completed excitation data remain available under the existing cache
rules. Cross-project calibration reuse is not introduced here.

Memory is allocated separately for each solver job. Reduce maximum jobs if the
thread budget would allow too many large models to run at once. The budget counts
reserved solver threads; ancillary BLAS pools in workers are limited to one thread.

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
